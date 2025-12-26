// =====================================================
// modal.js — Modal do Card (HTMX + Quill)
// Objetivo deste arquivo:
// 1) Abrir modal do card sem “cliques vazando” (toggle/menus não quebram)
// 2) Evitar “reabrir chato” do modal quando você clica em ações dentro do card
// 3) Manter compatibilidade LEGADO + CM (#cm-root)
// 4) Ter comentários didáticos em TUDO (arquivo-escola)
//
// ✅ PATCH DEFINITIVO (reabre ao mover):
// - Quando você ARRASTA um card (Sortable / drag & drop), o browser quase sempre dispara um "click"
//   no mouseup/touchend. Como o open do modal está em CAPTURE, ele pegava esse click e reabria.
// - Solução: detector global de "drag recente" (mouse/pointer/touch) + heurística de classes do Sortable.
//   Se houve movimento acima do threshold, ignoramos o click por ~800ms.
// =====================================================

// =====================================================
// Estado global do modal / editores
// =====================================================
window.currentCardId = null; // card atualmente aberto no modal (se houver)

// Referências globais do Quill (legado e/ou CM). Em CM usamos variáveis locais,
// mas manter referências pode ajudar para debug / limpeza.
let quillDesc = null;
let quillAtiv = null;

// Abas do modal LEGADO que suportam “savebar”
const tabsWithSave = new Set(["card-tab-desc", "card-tab-tags"]);

// =====================================================
// Helpers básicos (DOM, segurança, CSRF)
// =====================================================

/**
 * Lê CSRF token do <meta name="csrf-token" ...>
 * Obs: em Django geralmente o CSRF vai no cookie + hidden input;
 * aqui você usa meta, então mantemos.
 */
function getCsrfToken() {
  return document.querySelector("meta[name='csrf-token']")?.content || "";
}

/**
 * querySelector curto
 */
function qs(sel, root = document) {
  return root.querySelector(sel);
}

/**
 * querySelectorAll curto (array)
 */
function qsa(sel, root = document) {
  return Array.from(root.querySelectorAll(sel));
}

/**
 * Escapa HTML para evitar injeção ao montar strings com dados do backend
 */
function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// =====================================================
// Mention UI (Quill mention)
// =====================================================

/**
 * Gera iniciais para fallback de avatar (ex: "Cristiano Souza" => "CS")
 */
function initialsFrom(item) {
  const name = (item.display_name || item.value || item.email || "").trim();
  const parts = name.split(/\s+/).filter(Boolean);
  const a = (parts[0] || "")[0] || "";
  const b = (parts[1] || "")[0] || "";
  const out = (a + b).toUpperCase();
  return out || "@";
}

/**
 * Renderiza o “cardzinho” do mention na lista do autocomplete
 */
function renderMentionCard(item) {
  const name =
    (item.display_name || "").trim() ||
    (item.value || "").replace(/^@/, "").trim() ||
    (item.email || "").trim() ||
    `user${item.id}`;

  const handle = (item.handle || "").trim();
  const email = (item.email || "").trim();
  const avatar = (item.avatar_url || "").trim();

  const wrap = document.createElement("div");
  wrap.className = "mention-item mention-card";

  const avatarHtml = avatar
    ? `<img class="mention-avatar" src="${escapeHtml(
        avatar
      )}" alt="" loading="lazy">`
    : `<div class="mention-avatar mention-avatar-fallback">${escapeHtml(
        initialsFrom(item)
      )}</div>`;

  wrap.innerHTML = `
    ${avatarHtml}
    <div class="mention-meta">
      <div class="mention-name">${escapeHtml(name)}</div>
      <div class="mention-handle">${handle ? "@" + escapeHtml(handle) : ""}</div>
      <div class="mention-email">${email ? escapeHtml(email) : ""}</div>
    </div>
  `.trim();

  return wrap;
}

// =====================================================
// URL / contexto (board, modal)
// =====================================================

/**
 * Extrai boardId do path: /board/123/...
 */
function getBoardIdFromUrl() {
  const m = (window.location.pathname || "").match(/\/board\/(\d+)\//);
  return m?.[1] ? Number(m[1]) : null;
}

/**
 * Elemento raiz do modal global
 */
function getModalEl() {
  return document.getElementById("modal");
}

/**
 * Body do modal (onde o HTMX injeta o HTML)
 */
function getModalBody() {
  return document.getElementById("modal-body");
}

/**
 * Form “principal” (LEGADO) — usado no savebar/dirtiness
 * Obs: Em CM o form é outro (#cm-main-form) e o save é por botão #cm-save-btn.
 */
function getMainForm() {
  const body = getModalBody();
  if (!body) return null;
  return qs("#card-desc-form", body);
}

/**
 * Elementos do savebar do LEGADO
 */
function getSavebarElements() {
  const form = getMainForm();
  if (!form) return { bar: null, saveBtn: null };

  const bar = qs("#desc-savebar", form);
  const saveBtn = qs("button[type='submit']", form);
  return { bar, saveBtn };
}

// =====================================================
// ✅ Anti-reopen por DRAG (Sortable / DnD)
// =====================================================

/**
 * Quando você arrasta um card, no mouseup/touchend vem um CLICK "fantasma".
 * Como o binder de abrir modal está em CAPTURE, ele pegava esse click e reabria.
 *
 * Solução:
 * - Capturar pointer/mouse/touch e marcar "dragDetected" se mover mais que um threshold.
 * - Após detectar, criar um "cooldown" (window.__cardDragCooldownUntil).
 * - shouldIgnoreClick respeita esse cooldown.
 */
(function installDragClickShieldOnce() {
  if (document.body.dataset.dragClickShieldBound === "1") return;
  document.body.dataset.dragClickShieldBound = "1";

  // Estado
  let startX = 0;
  let startY = 0;
  let moved = false;
  let tracking = false;

  // Threshold bem pequeno (drag real) e cooldown suficiente pro Sortable finalizar
  const MOVE_PX = 6;
  const COOLDOWN_MS = 900;

  function markCooldown() {
    try {
      window.__cardDragCooldownUntil = Date.now() + COOLDOWN_MS;
    } catch (_e) {}
  }

  function onStart(clientX, clientY, target) {
    // Só nos interessa se começou dentro de um card
    const cardEl = target?.closest?.("li[data-card-id]");
    if (!cardEl) return;

    tracking = true;
    moved = false;
    startX = Number(clientX || 0);
    startY = Number(clientY || 0);
  }

  function onMove(clientX, clientY) {
    if (!tracking) return;
    const dx = Math.abs(Number(clientX || 0) - startX);
    const dy = Math.abs(Number(clientY || 0) - startY);
    if (dx > MOVE_PX || dy > MOVE_PX) moved = true;
  }

  function onEnd() {
    if (!tracking) return;
    tracking = false;

    // Se moveu acima do threshold, considera drag e ativa cooldown
    if (moved) markCooldown();

    moved = false;
  }

  // Pointer events (melhor suporte moderno)
  document.body.addEventListener(
    "pointerdown",
    (e) => {
      // Se é clique no modal, ignora (modal não abre card)
      if (e.target?.closest?.("#modal")) return;
      onStart(e.clientX, e.clientY, e.target);
    },
    { passive: true, capture: true }
  );

  document.body.addEventListener(
    "pointermove",
    (e) => onMove(e.clientX, e.clientY),
    { passive: true, capture: true }
  );

  document.body.addEventListener(
    "pointerup",
    () => onEnd(),
    { passive: true, capture: true }
  );

  document.body.addEventListener(
    "pointercancel",
    () => onEnd(),
    { passive: true, capture: true }
  );

  // Fallbacks (alguns browsers/embeds ainda geram mouse/touch separados)
  document.body.addEventListener(
    "mousedown",
    (e) => {
      if (e.target?.closest?.("#modal")) return;
      onStart(e.clientX, e.clientY, e.target);
    },
    { passive: true, capture: true }
  );

  document.body.addEventListener(
    "mousemove",
    (e) => onMove(e.clientX, e.clientY),
    { passive: true, capture: true }
  );

  document.body.addEventListener(
    "mouseup",
    () => onEnd(),
    { passive: true, capture: true }
  );

  document.body.addEventListener(
    "touchstart",
    (e) => {
      if (e.target?.closest?.("#modal")) return;
      const t = e.touches?.[0];
      if (!t) return;
      onStart(t.clientX, t.clientY, e.target);
    },
    { passive: true, capture: true }
  );

  document.body.addEventListener(
    "touchmove",
    (e) => {
      const t = e.touches?.[0];
      if (!t) return;
      onMove(t.clientX, t.clientY);
    },
    { passive: true, capture: true }
  );

  document.body.addEventListener(
    "touchend",
    () => onEnd(),
    { passive: true, capture: true }
  );

  document.body.addEventListener(
    "touchcancel",
    () => onEnd(),
    { passive: true, capture: true }
  );
})();

// =====================================================
// CM modal (tabs) — funciona após HTMX swap (sem script inline)
// =====================================================

/**
 * Inicializa tabs internas do modal CM (#cm-root).
 * - Alterna painéis por data-cm-tab/data-cm-panel
 * - Mostra/oculta botão “Salvar” dependendo da aba
 * - Salva última aba em sessionStorage (cmActiveTab)
 */
function initCmModal(body) {
  const root = body?.querySelector?.("#cm-root");
  if (!root) return;

  const tabs = Array.from(root.querySelectorAll("[data-cm-tab]"));
  const panels = Array.from(root.querySelectorAll("[data-cm-panel]"));
  if (!tabs.length || !panels.length) return;

  const saveBtn = root.querySelector("#cm-save-btn");
  const form = root.querySelector("#cm-main-form");

  // Decide se o botão salvar fica visível ou não (CM)
  function setSaveVisibility(activeName) {
    const shouldShowSave = activeName === "desc" || activeName === "tags";
    if (!saveBtn) return;

    saveBtn.classList.toggle("hidden", !shouldShowSave);
    saveBtn.style.display = shouldShowSave ? "" : "none";
    saveBtn.disabled = !shouldShowSave;
  }

  // Ativa aba/painel por “name”
  function activate(name) {
    root.dataset.cmActive = name;

    tabs.forEach((b) =>
      b.classList.toggle("is-active", b.getAttribute("data-cm-tab") === name)
    );
    panels.forEach((p) =>
      p.classList.toggle("is-active", p.getAttribute("data-cm-panel") === name)
    );

    setSaveVisibility(name);
  }

  // Binda cliques nas tabs apenas 1x por elemento
  tabs.forEach((b) => {
    if (b.dataset.cmBound === "1") return;
    b.dataset.cmBound = "1";

    b.addEventListener("click", (ev) => {
      // Evita submit/navegação e evita click “vazar”
      ev.preventDefault();
      ev.stopPropagation();

      const name = b.getAttribute("data-cm-tab");
      sessionStorage.setItem("cmActiveTab", name);
      activate(name);
    });
  });

  // Aba padrão: última usada ou desc
  activate(sessionStorage.getItem("cmActiveTab") || "desc");

  // Botão salvar do CM: pede submit do form (sem depender de <button type="submit"> dentro do form)
  if (saveBtn && form && saveBtn.dataset.cmBound !== "1") {
    saveBtn.dataset.cmBound = "1";
    saveBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();

      const active = root.dataset.cmActive || "desc";
      if (active !== "desc" && active !== "tags") return;

      try {
        form.requestSubmit();
      } catch (_e) {
        form.submit();
      }
    });
  }
}

// =====================================================
// CM modal — extras (cores de tags + erros anexos/atividade + capa)
// =====================================================

/**
 * Pega root CM atual. O root muda a cada HTMX swap.
 */
function cmGetRoot(body) {
  return body?.querySelector?.("#cm-root") || document.getElementById("cm-root");
}

/**
 * Garante que o dataset.tagColors exista (estado local da UI)
 */
function cmEnsureTagColorsState(root) {
  if (!root) return;
  if (!root.dataset.tagColors) {
    root.dataset.tagColors = root.getAttribute("data-tag-colors") || "{}";
  }
}

/**
 * Aplica as cores salvas nas tags do modal (UI)
 */
function cmApplySavedTagColors(root) {
  if (!root) return;

  let colors = {};
  try {
    const raw =
      root.dataset.tagColors || root.getAttribute("data-tag-colors") || "{}";
    colors = JSON.parse(raw);
    if (!colors || typeof colors !== "object") colors = {};
  } catch (_e) {
    colors = {};
  }

  const wrap = root.querySelector("#cm-tags-wrap");
  if (!wrap) return;

  wrap.querySelectorAll("button[data-tag]").forEach((btn) => {
    const tag = btn.getAttribute("data-tag");
    const c = colors[tag];
    if (!c) return;

    btn.style.backgroundColor = c + "20";
    btn.style.color = c;
    btn.style.borderColor = c;
  });
}

/**
 * Inicia popover de cor das tags no CM
 */
function cmInitTagColorPicker(root) {
  if (!root) return;

  // Binda 1x por root (como o root troca, vai rebinding seguro)
  if (root.dataset.cmTagColorBound === "1") return;
  root.dataset.cmTagColorBound = "1";

  const wrap = root.querySelector("#cm-tags-wrap");
  const picker = root.querySelector("#cm-tag-color-picker");
  const pop = root.querySelector("#cm-tag-color-popover");
  const save = root.querySelector("#cm-tag-color-save");
  const cancel = root.querySelector("#cm-tag-color-cancel");
  const form = root.querySelector("#cm-tag-color-form");
  const inpTag = root.querySelector("#cm-tag-color-tag");
  const inpCol = root.querySelector("#cm-tag-color-value");

  if (
    !wrap ||
    !picker ||
    !pop ||
    !save ||
    !cancel ||
    !form ||
    !inpTag ||
    !inpCol
  )
    return;

  let currentBtn = null;

  // Clique em uma tag => abre popover junto do botão
  wrap.addEventListener("click", function (e) {
    const btn = e.target.closest(".cm-tag-btn");
    if (!btn) return;

    currentBtn = btn;
    const tag = btn.dataset.tag;

    let colors = {};
    try {
      colors = JSON.parse(
        root.dataset.tagColors || root.getAttribute("data-tag-colors") || "{}"
      );
    } catch (_e) {}

    picker.value = colors[tag] || "#3b82f6";

    // Posiciona popover relativo ao modal-body (para scroll funcionar)
    const mb = document.getElementById("modal-body");
    const mbRect = mb?.getBoundingClientRect() || { top: 0, left: 0 };

    const rect = btn.getBoundingClientRect();
    const top = rect.bottom - mbRect.top + (mb?.scrollTop || 0);
    const left = rect.left - mbRect.left + (mb?.scrollLeft || 0);

    pop.style.top = top + "px";
    pop.style.left = left + "px";

    pop.classList.remove("hidden");
  });

  cancel.addEventListener("click", function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    pop.classList.add("hidden");
    currentBtn = null;
  });

  // Salva a cor: atualiza UI + faz POST no endpoint do form
  save.addEventListener("click", function (ev) {
    ev.preventDefault();
    ev.stopPropagation();

    if (!currentBtn) return;

    const tag = currentBtn.dataset.tag;
    const color = picker.value;

    // UI imediata
    currentBtn.style.backgroundColor = color + "20";
    currentBtn.style.color = color;
    currentBtn.style.borderColor = color;

    // Estado local
    let colors = {};
    try {
      colors = JSON.parse(
        root.dataset.tagColors || root.getAttribute("data-tag-colors") || "{}"
      );
    } catch (_e) {}
    colors[tag] = color;
    root.dataset.tagColors = JSON.stringify(colors);

    // Payload para o form
    inpTag.value = tag;
    inpCol.value = color;

    pop.classList.add("hidden");

    // Persistência
    fetch(form.action, {
      method: "POST",
      credentials: "same-origin",
      body: new FormData(form),
      headers: {
        "X-CSRFToken": form.querySelector('[name=csrfmiddlewaretoken]').value,
      },
    })
      .then((r) => {
        if (!r.ok) throw new Error("Falha ao salvar cor da tag");
        return r.json();
      })
      .then((data) => {
        // Atualiza tags no modal
        const wrapEl = document.getElementById("cm-tags-wrap");
        if (wrapEl && data.modal) wrapEl.innerHTML = data.modal;

        // Atualiza snippet do card na board
        const cardEl = document.getElementById("card-" + data.card_id);
        if (cardEl && data.snippet) cardEl.outerHTML = data.snippet;

        applyBoardTagColorsNow();

        // Rebind seguro (novo HTML)
        const rootNow = document.getElementById("cm-root");
        cmEnsureTagColorsState(rootNow);
        cmApplySavedTagColors(rootNow);
        cmInitTagColorPicker(rootNow);
      })
      .catch((err) => console.error(err));
  });
}

/**
 * Instala listeners globais 1x para erros de anexos do CM
 */
function cmInstallAttachmentErrorsOnce() {
  if (document.body.dataset.cmAttachErrBound === "1") return;
  document.body.dataset.cmAttachErrBound = "1";

  function getRoot() {
    return document.getElementById("cm-root");
  }
  function fileEl(root) {
    return root?.querySelector?.("#attachment-file");
  }
  function descEl(root) {
    return root?.querySelector?.("#attachment-desc");
  }

  function showErr(root, msg) {
    const box = root?.querySelector?.("#attachments-error");
    if (!box) return;
    box.textContent = msg;
    box.classList.remove("hidden");
  }

  function clearErr(root) {
    const box = root?.querySelector?.("#attachments-error");
    if (!box) return;
    box.textContent = "";
    box.classList.add("hidden");
  }

  function resetFields(root) {
    const f = fileEl(root);
    const d = descEl(root);
    if (f) f.value = "";
    if (d) d.value = "";
  }

  // Antes do upload: marca estado “uploading” e guarda descrição
  document.body.addEventListener("htmx:beforeRequest", function (evt) {
    const root = getRoot();
    const elt = evt.detail?.elt;
    if (
      !root ||
      !elt ||
      !elt.matches?.("#attachment-file") ||
      !root.contains(elt)
    )
      return;

    root.dataset.cmUploading = "1";
    root.dataset.cmLastAttachmentDesc = (descEl(root)?.value || "").trim();
    clearErr(root);
  });

  // Após o swap do attachments-list: limpa inputs e cola a desc no último item
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    const root = getRoot();
    const target = evt.target;
    if (!root || !target || target.id !== "attachments-list") return;
    if (root.dataset.cmUploading !== "1") return;

    resetFields(root);
    clearErr(root);

    const desc = (root.dataset.cmLastAttachmentDesc || "").trim();
    if (desc) {
      const last = target.lastElementChild;
      if (last && !last.querySelector(".cm-attach-desc")) {
        const div = document.createElement("div");
        div.className = "cm-muted cm-attach-desc";
        div.style.marginTop = "4px";
        div.textContent = desc;
        last.appendChild(div);
      }
    }

    root.dataset.cmUploading = "0";
    root.dataset.cmLastAttachmentDesc = "";
  });

  // Erros HTMX (ex: 413)
  document.body.addEventListener("htmx:responseError", function (evt) {
    const root = getRoot();
    const elt = evt.detail?.elt;
    const xhr = evt.detail?.xhr;
    if (
      !root ||
      !elt ||
      !elt.matches?.("#attachment-file") ||
      !root.contains(elt)
    )
      return;

    if (xhr && xhr.status === 413) {
      showErr(
        root,
        "Arquivo acima de 50MB. O limite de anexo é 50MB. Comprima o arquivo ou envie um link (Drive/Dropbox) e tente novamente."
      );
    } else {
      showErr(root, "Não foi possível enviar o anexo agora. Tente novamente.");
    }

    resetFields(root);
    root.dataset.cmUploading = "0";
    root.dataset.cmLastAttachmentDesc = "";
  });

  // Pós-request: se OK, limpa também
  document.body.addEventListener("htmx:afterRequest", function (evt) {
    const root = getRoot();
    const elt = evt.detail?.elt;
    const xhr = evt.detail?.xhr;
    if (
      !root ||
      !elt ||
      !elt.matches?.("#attachment-file") ||
      !root.contains(elt)
    )
      return;

    if (xhr && xhr.status >= 200 && xhr.status < 300) {
      resetFields(root);
      clearErr(root);
      root.dataset.cmUploading = "0";
      root.dataset.cmLastAttachmentDesc = "";
    }
  });
}

/**
 * Instala listener global 1x para erro de atividade (CM)
 */
function cmInstallActivityErrorsOnce() {
  if (document.body.dataset.cmActivityErrBound === "1") return;
  document.body.dataset.cmActivityErrBound = "1";

  document.body.addEventListener("htmx:responseError", function (evt) {
    const elt = evt.detail?.elt;
    const xhr = evt.detail?.xhr;

    if (!elt || !elt.matches?.('form[hx-post*="add_activity"]')) return;

    const box = document.getElementById("activity-error");
    if (box) {
      box.textContent =
        xhr && xhr.responseText
          ? xhr.responseText
          : "Não foi possível incluir a atividade.";
      box.classList.remove("hidden");
    }

    try {
      elt.reset();
    } catch (_e) {}
  });
}

/**
 * Instala listeners globais 1x para:
 * - selecionar capa via click (trigger)
 * - upload via change no input file
 * - upload via paste (fora do Quill)
 *
 * ✅ IMPORTANTE: Este bloco é onde frequentemente “toggle para de abrir”
 * se o listener de abrir card capturar o clique.
 * Aqui, a solução é marcar trigger/menu com [data-no-modal] no HTML.
 * Como nem sempre isso existe, também tratamos atributos comuns (aria-haspopup etc)
 * no shouldIgnoreClick.
 */
function cmInstallCoverPasteAndUploadOnce() {
  if (document.body.dataset.cmCoverBound === "1") return;
  document.body.dataset.cmCoverBound = "1";

  function showCoverErr(msg) {
    const box = document.getElementById("cm-cover-error");
    if (!box) return;
    if (!msg) {
      box.textContent = "";
      box.classList.add("hidden");
    } else {
      box.textContent = msg;
      box.classList.remove("hidden");
    }
  }

  function getRoot() {
    return document.getElementById("cm-root");
  }

  function getCoverForm(root) {
    if (!root) return null;
    return (
      root.querySelector("#cm-cover-form") ||
      root.querySelector("form[data-cm-cover-form]") ||
      root.querySelector('form[action*="cover"]') ||
      null
    );
  }

  function getCoverInput(root) {
    if (!root) return null;
    return (
      root.querySelector("#cm-cover-file") ||
      root.querySelector('input[name="cover"][type="file"]') ||
      root.querySelector('input[type="file"][accept*="image"]') ||
      root.querySelector('input[type="file"]') ||
      null
    );
  }

  // Detecta se o paste aconteceu “dentro do Quill”
  function isPastingInsideQuill(e) {
    const ae = document.activeElement;
    if (
      ae &&
      ae.closest &&
      ae.closest(
        ".ql-editor, .ql-container, #quill-editor, #quill-editor-ativ, #cm-quill-editor-ativ, #cm-quill-editor-desc"
      )
    ) {
      return true;
    }

    const t = e.target;
    if (
      t &&
      t.closest &&
      t.closest(".ql-editor, .ql-container, #quill-editor, #quill-editor-ativ")
    ) {
      return true;
    }

    const path = typeof e.composedPath === "function" ? e.composedPath() : [];
    if (
      path &&
      path.some(
        (n) =>
          n &&
          n.classList &&
          (n.classList.contains("ql-editor") ||
            n.classList.contains("ql-container"))
      )
    ) {
      return true;
    }

    return false;
  }

  // Faz POST da capa e re-renderiza modal-body
  async function uploadCover(file) {
    const root = getRoot();
    if (!root) return;

    const form = getCoverForm(root);
    if (!form) {
      console.warn("[cover] form não encontrado dentro de #cm-root");
      return;
    }

    showCoverErr(null);

    const fd = new FormData(form);
    fd.set("cover", file); // garante name esperado no backend

    let r;
    try {
      r = await fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        body: fd,
        headers: {
          "X-CSRFToken":
            form.querySelector('[name=csrfmiddlewaretoken]')?.value || "",
        },
      });
    } catch (_e) {
      showCoverErr("Falha de rede ao enviar a capa.");
      return;
    }

    if (!r.ok) {
      const t = await r.text().catch(() => "");
      showCoverErr(t || `Não foi possível salvar a capa (HTTP ${r.status}).`);
      return;
    }

    const html = await r.text();
    const modalBody = document.getElementById("modal-body");
    if (modalBody) modalBody.innerHTML = html;

    // Após trocar HTML do modal, precisa reinicializar JS
    if (typeof window.initCardModal === "function") window.initCardModal();
  }

  // 1) Clique no trigger “Escolher imagem…”
  // capture=true para pegar mesmo se alguém tentar parar propagação antes
  document.body.addEventListener(
    "click",
    (e) => {
      const root = getRoot();
      if (!root) return;

      const pick =
        e.target.closest("#cm-cover-pick-btn") ||
        e.target.closest("[data-cm-cover-pick]") ||
        e.target.closest(".cm-cover-pick");

      if (!pick) return;

      // Dica didática: se esse trigger estiver dentro do card na board,
      // você DEVE ter data-no-modal nele para não disparar o open do card.
      // Ex: <button data-no-modal ...>
      const inp = getCoverInput(root);
      if (!inp) return;

      inp.click(); // abre file picker
    },
    true
  );

  // 2) Change no input file (somente capa)
  document.body.addEventListener(
    "change",
    (e) => {
      const root = getRoot();
      if (!root) return;

      const inp = e.target;
      if (!inp || inp.type !== "file") return;

      const isCoverInput =
        inp.matches?.("#cm-cover-file") ||
        inp.matches?.('input[name="cover"][type="file"]') ||
        !!inp.closest?.("#cm-cover-form");

      if (!isCoverInput) return;

      const file = inp.files?.[0];
      if (!file) return;

      // Validação defensiva: só imagem
      if (!(file.type || "").startsWith("image/")) {
        showCoverErr("Arquivo inválido: envie uma imagem.");
        try {
          inp.value = "";
        } catch (_e) {}
        return;
      }

      uploadCover(file);
      try {
        inp.value = "";
      } catch (_e) {}
    },
    true
  );

  // 3) Ctrl+V (fora do Quill) na aba desc => vira capa
  document.body.addEventListener(
    "paste",
    (e) => {
      const root = getRoot();
      if (!root) return;

      const active = root.dataset.cmActive || "desc";
      if (active !== "desc") return;

      if (isPastingInsideQuill(e)) return;

      const cd = e.clipboardData;
      if (!cd?.items?.length) return;

      const imgItem = Array.from(cd.items).find(
        (it) => it.kind === "file" && (it.type || "").startsWith("image/")
      );
      if (!imgItem) return;

      const file = imgItem.getAsFile();
      if (!file) return;

      e.preventDefault();
      uploadCover(file);
    },
    true
  );
}

/**
 * Boot do CM: roda a cada initCardModal (pois HTML troca)
 */
function cmBoot(body) {
  const root = cmGetRoot(body);
  if (!root) return;

  cmEnsureTagColorsState(root);
  cmApplySavedTagColors(root);
  cmInitTagColorPicker(root);

  cmInstallAttachmentErrorsOnce();
  cmInstallActivityErrorsOnce();
  cmInstallCoverPasteAndUploadOnce();
}

// =====================================================
// Abrir / Fechar modal (visual + limpeza)
// =====================================================

/**
 * Abre modal (aplica classes de animação)
 */
window.openModal = function () {
  const modal = getModalEl();
  if (!modal) return;

  modal.classList.remove("hidden");
  modal.classList.remove("modal-closing");

  // Força layout para o browser “ver” o estado inicial antes do transition
  void modal.offsetHeight;

  modal.classList.add("modal-open");
};

/**
 * Fecha modal com animação, limpa HTML e estado global
 */
window.closeModal = function () {
  const modal = getModalEl();
  const modalBody = getModalBody();

  // Se tiver ?card, remove da URL ao fechar
  // Remove ?card= da URL ao fechar (SEM criar histórico)
  // + marca um “cooldown” para evitar re-open por clique capturado
    try {
    const until = Date.now() + 350; // ligeiramente > sua animação
    const prev = Number(window.__modalCloseCooldownUntil || 0);
    window.__modalCloseCooldownUntil = Math.max(prev, until);
    clearUrlCard({ replace: true });
  } catch (_e) {}


  if (!modal) return;

  modal.classList.remove("modal-open");
  modal.classList.add("modal-closing");

  // Tempo alinhado com CSS (220ms)
  setTimeout(() => {
    modal.classList.add("hidden");
    modal.classList.remove("modal-closing");

    if (modalBody) modalBody.innerHTML = "";

    window.currentCardId = null;
    quillDesc = null;
    quillAtiv = null;
  }, 230);
};

// =====================================================
// Atualiza snippet do card na board
// =====================================================

/**
 * Pede snippet atualizado do card e troca o HTML do card na board
 */
window.refreshCardSnippet = function (cardId) {
  if (!cardId) return;

  htmx.ajax("GET", `/card/${cardId}/snippet/`, {
    target: `#card-${cardId}`,
    swap: "outerHTML",
  });
};

// =====================================================
// Savebar helpers (LEGADO)
// =====================================================

function hideSavebar() {
  const { bar, saveBtn } = getSavebarElements();
  if (!bar) return;

  bar.classList.add("hidden");
  bar.style.display = "none";
  if (saveBtn) saveBtn.disabled = true;
}

function showSavebar() {
  const { bar, saveBtn } = getSavebarElements();
  if (!bar) return;

  bar.classList.remove("hidden");
  bar.style.display = "";
  if (saveBtn) saveBtn.disabled = false;
}

/**
 * Aplica cores das tags na board (se você tem essa função global no projeto)
 */
function applyBoardTagColorsNow() {
  if (typeof window.applySavedTagColorsToBoard === "function") {
    window.applySavedTagColorsToBoard(document);
  }
}

/**
 * Marca o form como “sujo” e decide se o savebar aparece
 */
function markDirty() {
  const form = getMainForm();
  if (!form) return;

  form.classList.add("is-dirty");

  const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
  if (tabsWithSave.has(active)) showSavebar();
}

function clearDirty() {
  const form = getMainForm();
  if (!form) return;

  form.classList.remove("is-dirty");
  hideSavebar();
}

function maybeShowSavebar() {
  const form = getMainForm();
  if (!form) return;

  if (form.classList.contains("is-dirty")) showSavebar();
  else hideSavebar();
}

// =====================================================
// Helpers gerais
// =====================================================

/**
 * Conta quantas <img> tem dentro de um HTML
 * (usado para limitar imagens em atividade)
 */
function htmlImageCount(html) {
  const tmp = document.createElement("div");
  tmp.innerHTML = html || "";
  return tmp.querySelectorAll("img").length;
}

function toastError(msg) {
  alert(msg);
}

// =====================================================
// Alternar abas do modal LEGADO
// =====================================================

/**
 * Ativa painel do modal LEGADO pelo id (ex: card-tab-desc)
 */
window.cardOpenTab = function (panelId) {
  const modal = getModalEl();
  if (!modal) return;

  // Botões de abas
  qsa(".card-tab-btn", modal).forEach((btn) => {
    btn.classList.toggle(
      "card-tab-active",
      btn.getAttribute("data-tab-target") === panelId
    );
  });

  const body = getModalBody();
  if (!body) return;

  // Painéis
  qsa(".card-tab-panel", body).forEach((panel) => {
    const isTarget = panel.id === panelId;
    panel.classList.toggle("block", isTarget);
    panel.classList.toggle("hidden", !isTarget);
  });

  sessionStorage.setItem("modalActiveTab", panelId);

  if (!tabsWithSave.has(panelId)) hideSavebar();
  else maybeShowSavebar();

  // Ao entrar na aba atividade, re-aplica sub-aba correta
  if (panelId === "card-tab-ativ") {
    const wrap = qs(".ativ-subtab-wrap", body);
    if (wrap?.__ativShowFromChecked) wrap.__ativShowFromChecked();
  }
};

// =====================================================
// Quill helpers (inserir imagem base64)
// =====================================================

/**
 * Insere imagem base64 no Quill, e marca dirty
 */
function insertBase64ImageIntoQuill(quill, file) {
  if (!quill || !file) return;

  const reader = new FileReader();
  reader.onload = () => {
    const dataUrl = reader.result;
    const range = quill.getSelection(true) || { index: quill.getLength() };

    quill.insertEmbed(range.index, "image", dataUrl, "user");
    quill.setSelection(range.index + 1, 0, "user");
    markDirty();
  };
  reader.readAsDataURL(file);
}

// =====================================================
// Dirty tracking por delegação (1x por modal-body)
// =====================================================

/**
 * Binda listeners de input/change/submit no modal-body.
 * - Isso evita ter que bindar em cada campo individual.
 */
function bindDelegatedDirtyTracking() {
  const body = getModalBody();
  if (!body || body.dataset.dirtyDelegationBound) return;

  body.dataset.dirtyDelegationBound = "1";

  body.addEventListener("input", (ev) => {
    const form = getMainForm();
    if (!form) return;
    if (!form.contains(ev.target)) return;
    markDirty();
  });

  body.addEventListener("change", (ev) => {
    const form = getMainForm();
    if (!form) return;
    if (!form.contains(ev.target)) return;
    markDirty();
  });

  body.addEventListener("submit", (ev) => {
    const form = getMainForm();
    if (!form || ev.target !== form) return;
    const { saveBtn } = getSavebarElements();
    if (saveBtn) saveBtn.disabled = true;
  });
}

// =====================================================
// Quill: descrição (LEGADO + CM)
// =====================================================

/**
 * Inicializa editor de descrição:
 * 1) Se existir host legado (#quill-editor / #quill-editor-desc / [data-quill-desc]) => usa Quill ali
 * 2) Senão, se existir CM (#cm-root) e textarea[name=description] => cria Quill e sincroniza no textarea escondido
 */
function initQuillDesc(body) {
  if (!body) return;

  // 1) LEGADO
  const legacyHost =
    qs("#quill-editor", body) ||
    qs("#quill-editor-desc", body) ||
    qs("[data-quill-desc]", body);

  if (legacyHost) {
    if (legacyHost.dataset.quillReady === "1") return;
    legacyHost.dataset.quillReady = "1";

    // Campo hidden/textarea que recebe HTML
    const hidden =
      qs("#desc-input", body) ||
      qs("#description-input", body) ||
      qs('input[name="description"]', body) ||
      qs('textarea[name="description"]', body) ||
      qs('textarea[name="desc"]', body) ||
      qs('input[name="desc"]', body);

    // Se host não tem id, cria para o Quill conseguir selecionar
    const selector =
      legacyHost.id
        ? `#${legacyHost.id}`
        : (() => {
            legacyHost.id = "quill-editor-desc";
            return "#quill-editor-desc";
          })();

    // Cria Quill
    quillDesc = new Quill(selector, {
      theme: "snow",
      modules: {
        toolbar: {
          container: [
            [{ header: [1, 2, 3, false] }],
            ["bold", "italic", "underline"],
            ["link", "image"],
            [{ list: "ordered" }, { list: "bullet" }],
          ],
          handlers: {
            image: function () {
              const fileInput = document.createElement("input");
              fileInput.type = "file";
              fileInput.accept = "image/*";
              fileInput.onchange = () => {
                const file = fileInput.files?.[0];
                if (!file) return;
                insertBase64ImageIntoQuill(quillDesc, file);
              };
              fileInput.click();
            },
          },
        },
      },
    });

    // Conteúdo inicial
    const initialHtml = (hidden?.value || "").trim();
    quillDesc.root.innerHTML = initialHtml || "";

    // Sync Quill => hidden + dirty
    quillDesc.on("text-change", () => {
      if (hidden) hidden.value = quillDesc.root.innerHTML;
      markDirty();
    });

    // Paste de imagens
    quillDesc.root.addEventListener("paste", (e) => {
      const cd = e.clipboardData;
      if (!cd?.items?.length) return;

      const imgItems = Array.from(cd.items).filter(
        (it) => it.kind === "file" && (it.type || "").startsWith("image/")
      );
      if (!imgItems.length) return;

      e.preventDefault();
      imgItems.forEach((it) => {
        const file = it.getAsFile();
        if (file) insertBase64ImageIntoQuill(quillDesc, file);
      });
    });

    return;
  }

  // 2) CM
  const cmRoot = qs("#cm-root", body);
  if (!cmRoot) return;

  const descPanel = cmRoot.querySelector('[data-cm-panel="desc"]');
  if (!descPanel) return;

  const textarea = descPanel.querySelector('textarea[name="description"]');
  if (!textarea) return;

  if (textarea.dataset.cmQuillReady === "1") return;
  textarea.dataset.cmQuillReady = "1";

  // Cria host do Quill antes do textarea
  const host = document.createElement("div");
  host.id = "cm-quill-editor-desc";
  host.className = "border rounded mb-2";
  host.style.minHeight = "220px";
  textarea.parentNode.insertBefore(host, textarea);

  // Esconde textarea (mas mantém para POST)
  textarea.style.display = "none";

  const boardId = getBoardIdFromUrl();

  // Cria Quill CM
  const q = new Quill("#" + host.id, {
    theme: "snow",
    modules: {
      toolbar: {
        container: [
          [{ header: [1, 2, 3, false] }],
          ["bold", "italic", "underline"],
          ["link", "image"],
          [{ list: "ordered" }, { list: "bullet" }],
        ],
        handlers: {
          image: function () {
            const fileInput = document.createElement("input");
            fileInput.type = "file";
            fileInput.accept = "image/*";
            fileInput.onchange = () => {
              const file = fileInput.files?.[0];
              if (!file) return;
              insertBase64ImageIntoQuill(q, file);
            };
            fileInput.click();
          },
        },
      },

      // Mention no CM
      mention: {
        allowedChars: /^[A-Za-zÀ-ÖØ-öø-ÿ0-9_ .-]*$/,
        mentionDenotationChars: ["@"],
        showDenotationChar: true,
        spaceAfterInsert: true,

        renderItem: function (item) {
          return renderMentionCard(item);
        },

        // Quando seleciona, garante atributos data-id/data-value no span.mention
        onSelect: function (item, insertItem) {
          const range = q.getSelection(true);
          if (!range) return;

          insertItem(item);

          setTimeout(() => {
            const root = q.root;
            const mentions = root.querySelectorAll("span.mention");
            const last = mentions[mentions.length - 1];
            if (!last) return;

            last.setAttribute("data-id", String(item.id));
            last.setAttribute("data-value", String(item.value));
            if (!last.textContent?.startsWith("@"))
              last.textContent = "@" + item.value;

            textarea.value = q.root.innerHTML;
          }, 0);
        },

        // Busca mentions no backend
        source: async function (searchTerm, renderList) {
          try {
            const qtxt = (searchTerm || "").trim();
            if (!boardId) return renderList([], searchTerm);

            const res = await fetch(
              `/board/${boardId}/mentions/?q=${encodeURIComponent(qtxt)}`,
              {
                method: "GET",
                credentials: "same-origin",
                headers: { Accept: "application/json" },
              }
            );

            if (!res.ok) return renderList([], searchTerm);

            const data = await res.json();
            renderList(
              Array.isArray(data) ? data : data.results || [],
              searchTerm
            );
          } catch (_e) {
            renderList([], searchTerm);
          }
        },
      },
    },
  });

  // Conteúdo inicial
  q.root.innerHTML = (textarea.value || "").trim() || "";

  // Sync Quill => textarea + dirty
  q.on("text-change", () => {
    textarea.value = q.root.innerHTML;
    markDirty();
  });

  // Paste de imagem (capture) — impede conflito com outros handlers de paste
  const onPaste = (e) => {
    const cd = e.clipboardData;
    if (!cd?.items?.length) return;

    const imgItems = Array.from(cd.items).filter(
      (it) => it.kind === "file" && (it.type || "").startsWith("image/")
    );
    if (!imgItems.length) return;

    e.preventDefault();
    e.stopPropagation();
    if (typeof e.stopImmediatePropagation === "function")
      e.stopImmediatePropagation();

    imgItems.forEach((it) => {
      const file = it.getAsFile();
      if (file) insertBase64ImageIntoQuill(q, file);
    });
  };

  // Rebind seguro caso reabra modal e o elemento exista por algum motivo
  if (q.root.__onPasteCmDesc) {
    q.root.removeEventListener("paste", q.root.__onPasteCmDesc, true);
  }
  q.root.__onPasteCmDesc = onPaste;
  q.root.addEventListener("paste", onPaste, true);

  quillDesc = q;
}

// =====================================================
// Quill: atividade (LEGADO + CM)
// =====================================================

/**
 * Inicializa editor de atividade:
 * - CM: textarea[name="content"] vira Quill e sincroniza
 * - LEGADO: #quill-editor-ativ + #activity-input
 */
function initQuillAtividade(body) {
  if (!body) return;

  // 1) CM
  const cmRoot = qs("#cm-root", body);
  if (cmRoot) {
    const ativPanel = cmRoot.querySelector('[data-cm-panel="ativ"]');
    if (!ativPanel) return;

    const form = ativPanel.querySelector('form[hx-post*="add_activity"], form');
    const textarea = ativPanel.querySelector('textarea[name="content"]');
    if (!form || !textarea) return;

    if (textarea.dataset.cmQuillReady === "1") return;
    textarea.dataset.cmQuillReady = "1";

    const host = document.createElement("div");
    host.id = "cm-quill-editor-ativ";
    host.className = "border rounded mb-2";
    host.style.minHeight = "140px";
    textarea.parentNode.insertBefore(host, textarea);

    textarea.style.display = "none";

    const boardId = getBoardIdFromUrl();

    const q = new Quill("#" + host.id, {
      theme: "snow",
      modules: {
        toolbar: {
          container: [
            [{ header: [1, 2, 3, false] }],
            ["bold", "italic", "underline"],
            ["link", "image"],
            [{ list: "ordered" }, { list: "bullet" }],
          ],
          handlers: {
            image: function () {
              const fileInput = document.createElement("input");
              fileInput.type = "file";
              fileInput.accept = "image/*";
              fileInput.onchange = () => {
                const file = fileInput.files?.[0];
                if (!file) return;
                insertBase64ImageIntoQuill(q, file);
              };
              fileInput.click();
            },
          },
        },

        mention: {
          allowedChars: /^[A-Za-zÀ-ÖØ-öø-ÿ0-9_ .-]*$/,
          mentionDenotationChars: ["@"],
          showDenotationChar: true,
          spaceAfterInsert: true,

          renderItem: function (item) {
            return renderMentionCard(item);
          },

          onSelect: function (item, insertItem) {
            const range = q.getSelection(true);
            if (!range) return;

            insertItem(item);

            setTimeout(() => {
              const root = q.root;
              const mentions = root.querySelectorAll("span.mention");
              const last = mentions[mentions.length - 1];
              if (!last) return;

              last.setAttribute("data-id", String(item.id));
              last.setAttribute("data-value", String(item.value));
              if (!last.textContent?.startsWith("@"))
                last.textContent = "@" + item.value;

              textarea.value = q.root.innerHTML;
            }, 0);
          },

          source: async function (searchTerm, renderList) {
            try {
              const qtxt = (searchTerm || "").trim();
              if (!boardId) return renderList([], searchTerm);

              const res = await fetch(
                `/board/${boardId}/mentions/?q=${encodeURIComponent(qtxt)}`,
                {
                  method: "GET",
                  credentials: "same-origin",
                  headers: { Accept: "application/json" },
                }
              );

              if (!res.ok) return renderList([], searchTerm);

              const data = await res.json();
              renderList(
                Array.isArray(data) ? data : data.results || [],
                searchTerm
              );
            } catch (_e) {
              renderList([], searchTerm);
            }
          },
        },
      },
    });

    // Ajuda a garantir foco/click estáveis
    try {
      q.root.setAttribute("tabindex", "0");
    } catch (_e) {}

    q.root.innerHTML = (textarea.value || "").trim() || "";

    // Sync Quill => textarea
    q.on("text-change", () => {
      textarea.value = q.root.innerHTML;
    });

    // Paste de imagens (capture)
    const onPasteCmAtiv = (e) => {
      const cd = e.clipboardData;
      if (!cd?.items?.length) return;

      const imgItems = Array.from(cd.items).filter(
        (it) => it.kind === "file" && (it.type || "").startsWith("image/")
      );
      if (!imgItems.length) return;

      e.preventDefault();
      e.stopPropagation();
      if (typeof e.stopImmediatePropagation === "function")
        e.stopImmediatePropagation();

      imgItems.forEach((it) => {
        const file = it.getAsFile();
        if (file) insertBase64ImageIntoQuill(q, file);
      });
    };

    if (q.root.__onPasteCmAtiv) {
      q.root.removeEventListener("paste", q.root.__onPasteCmAtiv, true);
    }
    q.root.__onPasteCmAtiv = onPasteCmAtiv;
    q.root.addEventListener("paste", onPasteCmAtiv, true);

    // Se o form for resetado (ex: hx-on::after-request="this.reset()"), limpa o Quill
    if (form.dataset.cmQuillResetBound !== "1") {
      form.dataset.cmQuillResetBound = "1";
      form.addEventListener("reset", () => {
        try {
          q.setText("");
        } catch (_e) {}
        textarea.value = "";
      });
    }

    return; // CM tratado
  }

  // 2) LEGADO
  const activityHidden = qs("#activity-input", body);
  const quillAtivEl = qs("#quill-editor-ativ", body);
  if (!activityHidden || !quillAtivEl) return;

  if (quillAtivEl.dataset.quillReady === "1") return;
  quillAtivEl.dataset.quillReady = "1";

  quillAtiv = new Quill("#quill-editor-ativ", {
    theme: "snow",
    modules: {
      toolbar: {
        container: [
          [{ header: [1, 2, 3, false] }],
          ["bold", "italic", "underline"],
          ["link", "image"],
          [{ list: "ordered" }, { list: "bullet" }],
        ],
        handlers: {
          image: function () {
            const fileInput = document.createElement("input");
            fileInput.type = "file";
            fileInput.accept = "image/*";

            fileInput.onchange = () => {
              const file = fileInput.files?.[0];
              if (!file) return;
              insertBase64ImageIntoQuill(quillAtiv, file);
            };

            fileInput.click();
          },
        },
      },
    },
  });

  quillAtiv.root.innerHTML = "";
  activityHidden.value = "";

  quillAtiv.on("text-change", () => {
    activityHidden.value = quillAtiv.root.innerHTML;
  });

  const onPasteAtiv = (e) => {
    const cd = e.clipboardData;
    if (!cd?.items?.length) return;

    const imgItems = Array.from(cd.items).filter(
      (it) => it.kind === "file" && (it.type || "").startsWith("image/")
    );
    if (!imgItems.length) return;

    e.preventDefault();
    e.stopPropagation();
    if (typeof e.stopImmediatePropagation === "function")
      e.stopImmediatePropagation();

    imgItems.forEach((it) => {
      const file = it.getAsFile();
      if (file) insertBase64ImageIntoQuill(quillAtiv, file);
    });
  };

  if (quillAtiv.root.__onPasteAtiv) {
    quillAtiv.root.removeEventListener(
      "paste",
      quillAtiv.root.__onPasteAtiv,
      true
    );
  }
  quillAtiv.root.__onPasteAtiv = onPasteAtiv;
  quillAtiv.root.addEventListener("paste", onPasteAtiv, true);
}

// =====================================================
// Atividade (sub-tabs): Nova atividade / Histórico / Mover Card
// =====================================================

/**
 * Controla as sub-abas de atividade (new/hist/move) via radio + show/hide.
 * Nota: isso evita depender de CSS antigo (Tailwind etc).
 */
function initAtivSubtabs3(body) {
  const wrap = qs(".ativ-subtab-wrap", body);
  if (!wrap) return;

  const rNew = qs("#ativ-tab-new", wrap);
  const rHist = qs("#ativ-tab-hist", wrap);
  const rMove = qs("#ativ-tab-move", wrap);

  const vNew = qs(".ativ-view-new", wrap);
  const vHist = qs(".ativ-view-hist", wrap);
  const vMove = qs(".ativ-view-move", wrap);

  function show(which) {
    if (vNew) {
      vNew.style.display = which === "new" ? "block" : "none";
      vNew.classList.toggle("hidden", which !== "new");
    }
    if (vHist) {
      vHist.style.display = which === "hist" ? "block" : "none";
      vHist.classList.toggle("hidden", which !== "hist");
    }
    if (vMove) {
      vMove.style.display = which === "move" ? "block" : "none";
      vMove.classList.toggle("hidden", which !== "move");
    }

    // Ao entrar em “move”, carregar opções (se existir)
    if (
      which === "move" &&
      window.currentCardId &&
      typeof window.loadMoveCardOptions === "function"
    ) {
      window.loadMoveCardOptions(window.currentCardId);
    }
  }

  function showFromChecked() {
    if (rMove?.checked) show("move");
    else if (rHist?.checked) show("hist");
    else show("new");
  }

  // Expondo helpers no wrapper (usado por cardOpenTab)
  wrap.__ativShow = show;
  wrap.__ativShowFromChecked = showFromChecked;

  showFromChecked();

  // Bind 1x
  if (wrap.dataset.ativ3Ready === "1") return;
  wrap.dataset.ativ3Ready = "1";

  rNew?.addEventListener("change", () => rNew.checked && show("new"));
  rHist?.addEventListener("change", () => rHist.checked && show("hist"));
  rMove?.addEventListener("change", () => rMove.checked && show("move"));

  qsa(".ativ-subtab-btn", wrap).forEach((lbl) => {
    lbl.addEventListener("click", () => setTimeout(showFromChecked, 0));
  });
}

// =====================================================
// Inicializa modal (pós HTMX swap)
// =====================================================

/**
 * Inicializa tudo que depende do HTML atual do modal-body:
 * - currentCardId
 * - delegated dirty tracking
 * - Quill desc + atividade
 * - subtabs atividade
 * - Prism (se existir)
 * - CM tabs + boot
 */
window.initCardModal = function () {
  const body = getModalBody();
  if (!body) return;

  const cmRoot = qs("#cm-root", body);
  const legacyRoot = qs("#card-modal-root", body) || qs("#card-modal-root");

  const cid =
    cmRoot?.getAttribute?.("data-card-id") ||
    legacyRoot?.getAttribute?.("data-card-id");

  if (cid) window.currentCardId = Number(cid);

  bindDelegatedDirtyTracking();
  clearDirty();

  initQuillDesc(body);
  initQuillAtividade(body);
  initAtivSubtabs3(body);

  if (window.Prism) Prism.highlightAll();

  initCmModal(body);
  cmBoot(body);
};

// =====================================================
// ✅ Abertura do modal pelo clique no card (RADICAL + MOBILE)
// Aqui fica o “toggle e reabrir chato”.
// =====================================================

/**
 * Regra de ouro:
 * - O listener abaixo roda em CAPTURE (true) para garantir consistência
 * - Logo, ele NÃO pode interceptar cliques de menus/toggles
 *
 * Solução robusta:
 * - shouldIgnoreClick cobre:
 *   - elementos interativos (button, input, etc.)
 *   - qualquer coisa marcada com data-no-modal (recomendado no HTML)
 *   - toggles de menu comuns (aria-haspopup, aria-expanded, role=menu, etc.)
 *   - containers de menu/popover (dropdown-menu, menu, popover, etc.)
 *   - heurística “kebab/ellipsis/more”
 *   - ✅ DRAG COOLDOWN (Sortable / DnD)
 */
(function bindCardOpenRadical() {
  // Garante que esse binder roda uma única vez
  if (document.body.dataset.cardOpenRadicalBound === "1") return;
  document.body.dataset.cardOpenRadicalBound = "1";

  /**
   * Decide se um clique deve ser ignorado (não abrir modal).
   * Se retornar true => a gente NÃO chama preventDefault/stopPropagation,
   * e deixa o clique seguir normal (toggle/menu abre).
   */
  function shouldIgnoreClick(ev) {
    const t = ev.target;

    // ✅ Se acabou de ARRASTAR card, ignorar clique "fantasma"
    if (window.__cardDragCooldownUntil && Date.now() < window.__cardDragCooldownUntil) {
      return true;
    }

    // Cooldown: acabou de fechar modal, não reabrir por clique “atravessado”
    if (
      window.__modalCloseCooldownUntil &&
      Date.now() < window.__modalCloseCooldownUntil
    ) {
      return true;
    }

    // Clique dentro do modal NUNCA pode abrir card da board
    if (ev.target?.closest?.("#modal")) return true;

    // 1) Escape hatch: marcações explícitas no HTML
    if (t?.closest?.("[data-no-modal]")) return true;

    // 2) Caminho completo do clique (melhor que só closest)
    const path =
      typeof ev.composedPath === "function"
        ? ev.composedPath()
        : (function () {
            const out = [];
            let n = t;
            while (n) {
              out.push(n);
              n = n.parentNode;
            }
            return out;
          })();

    const nodes = (path || []).filter((n) => n && n.nodeType === 1);

    // ✅ Heurística Sortable (quando classes aparecem no drag)
    for (const n of nodes) {
      const cls = (n.className || "").toString();
      if (
        cls.includes("sortable-ghost") ||
        cls.includes("drag-ghost") ||
        cls.includes("drag-chosen") ||
        cls.includes("sortable-chosen") ||
        cls.includes("sortable-drag")
      ) {
        return true;
      }
    }

    // 3) Interativos padrão (clique é ação, não abrir card)
    // IMPORTANTE: NÃO ignorar <a> e <label> aqui, porque em muitos layouts
    // o card inteiro ou grandes áreas ficam dentro de um <a> (ou label) — e aí
    // o modal nunca abre. Ações de menu/toggle continuam cobertas por:
    // - [data-no-modal]
    // - aria-haspopup/aria-expanded
    // - containers .dropdown/.menu/.card-actions etc
    const interactiveSelectors = [
      "button",
      "input",
      "textarea",
      "select",
      "form",
      "[role='menuitem']",
      "[contenteditable='true']",
    ];

    for (const n of nodes) {
      if (interactiveSelectors.some((sel) => n.matches?.(sel))) return true;
    }

    // 4) Toggles/menus semânticos comuns
    const menuToggleSelectors = [
      "[aria-haspopup='menu']",
      "[aria-haspopup='true']",
      "[aria-expanded]",
      "[data-bs-toggle]",
      "[data-toggle]",
      "[data-dropdown]",
      "[data-menu]",
      "[data-action='menu']",
      "[data-action='toggle']",
    ];
    for (const n of nodes) {
      if (menuToggleSelectors.some((sel) => n.matches?.(sel))) return true;
    }

    // 5) Clique dentro de menu/popover não pode abrir card
    const menuContainerSelectors = [
      "[role='menu']",
      ".dropdown-menu",
      ".dropdown",
      ".menu",
      ".popover",
      ".popper",
      ".tooltip",
      ".card-actions",
      ".card-actions-menu",
      ".card-more",
      ".ellipsis",
    ];
    for (const n of nodes) {
      if (menuContainerSelectors.some((sel) => n.matches?.(sel))) return true;
    }

    // 6) Heurística: “kebab/ellipsis/more/toggle”
    // (resolve quando o toggle é um <div>/<span> sem aria/role)
    for (const n of nodes) {
      const cls = (n.className || "").toString().toLowerCase();
      if (
        cls.includes("ellipsis") ||
        cls.includes("kebab") ||
        cls.includes("dots") ||
        cls.includes("more") ||
        cls.includes("menu") ||
        cls.includes("toggle") ||
        cls.includes("actions")
      ) {
        return true;
      }

      const ariaLabel = (n.getAttribute?.("aria-label") || "").toLowerCase();
      const title = (n.getAttribute?.("title") || "").toLowerCase();
      if (
        ariaLabel.includes("more") ||
        ariaLabel.includes("menu") ||
        ariaLabel.includes("opç") ||
        ariaLabel.includes("opc") ||
        ariaLabel.includes("acao") ||
        ariaLabel.includes("ação") ||
        title.includes("more") ||
        title.includes("menu") ||
        title.includes("opç") ||
        title.includes("opc")
      ) {
        return true;
      }
    }

    // 7) Caso específico defensivo
    if (t?.closest?.(".delete-card-btn")) return true;

    return false;
  }

  // ----- MOBILE (touch) -----
  let touchStartY = 0;
  let touchMoved = false;

  document.body.addEventListener(
    "touchstart",
    (ev) => {
      const cardEl = ev.target.closest("li[data-card-id]");
      if (!cardEl) return;

      touchStartY = ev.touches[0].clientY;
      touchMoved = false;
    },
    { passive: true }
  );

  document.body.addEventListener(
    "touchmove",
    (ev) => {
      const deltaY = Math.abs(ev.touches[0].clientY - touchStartY);
      if (deltaY > 10) touchMoved = true;
    },
    { passive: true }
  );

  document.body.addEventListener(
    "touchend",
    (ev) => {
      const cardEl = ev.target.closest("li[data-card-id]");
      if (!cardEl) return;

      // Se virou scroll, não é “tap”
      if (touchMoved) return;

      // Se é clique em toggle/menu/ação, NÃO intercepta
      if (shouldIgnoreClick(ev)) return;

      const cardId = Number(cardEl.dataset.cardId || 0);
      if (!cardId) return;

      // Só bloqueia quando vamos abrir o modal
      ev.preventDefault();
      ev.stopPropagation();

      openCardModalAndLoad(cardId, { replaceUrl: false });
    },
    true
  );

  // ----- DESKTOP (click) -----
  document.body.addEventListener(
    "click",
    (ev) => {
      const cardEl = ev.target.closest("li[data-card-id]");
      if (!cardEl) return;

      // Toggle/menu/ação/drag: deixa o clique passar
      if (shouldIgnoreClick(ev)) return;

      const cardId = Number(cardEl.dataset.cardId || 0);
      if (!cardId) return;

      // Só bloqueia quando vamos abrir o modal (evita “reabrir chato”)
      ev.preventDefault();
      ev.stopPropagation();

      openCardModalAndLoad(cardId, { replaceUrl: false });
    },
    true
  );
})();

// =====================================================
// HTMX – após swap do modal-body
// =====================================================

/**
 * Quando o HTMX termina de trocar #modal-body, abrimos o modal e iniciamos scripts.
 */
document.body.addEventListener("htmx:afterSwap", function (e) {
  if (!e.detail?.target || e.detail.target.id !== "modal-body") return;

  openModal();
  initCardModal();

  // Se for modal novo (CM), não aplicar tabs do modal antigo
  if (!document.querySelector("#cm-root")) {
    const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
    window.cardOpenTab(active);
  }
});

// =====================================================
// Remover TAG (instantâneo)
// =====================================================

window.removeTagInstant = async function (cardId, tag) {
  const formData = new FormData();
  formData.append("tag", tag);

  const response = await fetch(`/card/${cardId}/remove_tag/`, {
    method: "POST",
    headers: { "X-CSRFToken": getCsrfToken() },
    body: formData,
    credentials: "same-origin",
  });

  if (!response.ok) return;

  const data = await response.json();

  const modalBody = getModalBody();
  if (modalBody) modalBody.innerHTML = data.modal;

  const card = document.querySelector(`#card-${data.card_id}`);
  if (card) card.outerHTML = data.snippet;

  applyBoardTagColorsNow();

  initCardModal();

  if (!document.querySelector("#cm-root")) {
    const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
    window.cardOpenTab(active);
  }
};

// =====================================================
// ALTERAR COR DA TAG (instantâneo)
// =====================================================

window.setTagColorInstant = async function (cardId, tag, color) {
  const formData = new FormData();
  formData.append("tag", tag);
  formData.append("color", color);

  const response = await fetch(`/card/${cardId}/set_tag_color/`, {
    method: "POST",
    headers: { "X-CSRFToken": getCsrfToken() },
    body: formData,
    credentials: "same-origin",
  });

  if (!response.ok) {
    console.error("Erro ao salvar cor da tag");
    return;
  }

  const data = await response.json();

  const modalBody = getModalBody();
  if (modalBody) modalBody.innerHTML = data.modal;

  const card = document.querySelector(`#card-${data.card_id}`);
  if (card) card.outerHTML = data.snippet;

  initCardModal();
};

// =====================================================
// Atividade helpers (LEGADO)
// =====================================================

window.clearActivityEditor = function () {
  const body = getModalBody();
  if (!body) return;

  const activityHidden = qs("#activity-input", body);
  if (quillAtiv) quillAtiv.setText("");
  if (activityHidden) activityHidden.value = "";
};

window.submitActivity = async function (cardId) {
  const body = getModalBody();
  if (!body) return;

  const activityInput = qs("#activity-input", body);
  if (!activityInput) return;

  const content = (activityInput.value || "").trim();
  if (!content) return;

  const imgCount = htmlImageCount(content);
  if (imgCount > 1) {
    toastError(
      "No momento, cada atividade aceita no máximo 1 imagem. Remova uma das imagens e tente novamente."
    );
    return;
  }

  const formData = new FormData();
  formData.append("content", content);

  let response;
  try {
    response = await fetch(`/card/${cardId}/activity/add/`, {
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() },
      body: formData,
      credentials: "same-origin",
    });
  } catch (_err) {
    toastError("Falha de rede ao incluir atividade.");
    return;
  }

  if (!response.ok) {
    const msg = await response.text().catch(() => "");
    toastError(msg || `Falha ao incluir atividade (HTTP ${response.status}).`);
    return;
  }

  const html = await response.text();

  const panel = qs("#card-activity-panel", body);
  if (panel) {
    panel.outerHTML = html;
  } else {
    const wrapper = qs("#activity-panel-wrapper", body);
    if (wrapper) wrapper.innerHTML = html;
  }

  window.clearActivityEditor();

  const histRadio = document.getElementById("ativ-tab-hist");
  if (histRadio) {
    histRadio.checked = true;
    histRadio.dispatchEvent(new Event("change", { bubbles: true }));
  }

  const wrap = qs(".ativ-subtab-wrap", body);
  if (wrap?.__ativShow) wrap.__ativShow("hist");

  if (window.Prism) Prism.highlightAll();
};

// =====================================================
// Mover Card (DOM + backend)
// =====================================================

function getCurrentBoardIdFromUrl() {
  const m = (window.location.pathname || "").match(/\/board\/(\d+)\//);
  return m?.[1] ? Number(m[1]) : null;
}

function findColumnContainer(columnId) {
  const selectors = [
    `#column-${columnId} .cards`,
    `#column-${columnId} ul`,
    `#column-${columnId}`,
    `#col-${columnId} .cards`,
    `#col-${columnId} ul`,
    `#col-${columnId}`,
    `[data-column-id="${columnId}"] .cards`,
    `[data-column-id="${columnId}"] ul`,
    `[data-column-id="${columnId}"]`,
  ];

  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) return el;
  }
  return null;
}

function moveCardDom(cardId, newColumnId, newPosition0) {
  const cardEl = document.getElementById(`card-${cardId}`);
  if (!cardEl) return false;

  const target = findColumnContainer(newColumnId);
  if (!target) return false;

  const items = Array.from(
    target.querySelectorAll(
      "[data-card-id], li[id^='card-'], #card-" + cardId + ", .card"
    )
  );

  const idx = Math.max(0, Number(newPosition0 || 0));

  if (items[idx]) target.insertBefore(cardEl, items[idx]);
  else target.appendChild(cardEl);

  return true;
}

(function bindMoveCardOnce() {
  if (window.__moveCardHookInstalled) return;
  window.__moveCardHookInstalled = true;

  function setMoveError(msg) {
    const body = getModalBody();
    if (!body) return;
    const err = qs("#move-error", body);
    if (!err) return;

    if (!msg) {
      err.textContent = "";
      err.classList.add("hidden");
    } else {
      err.textContent = msg;
      err.classList.remove("hidden");
    }
  }

  function setCurrentLocationText(txt) {
    const body = getModalBody();
    if (!body) return;
    const loc = qs("#move-current-location", body);
    if (loc) loc.textContent = txt || "—";
  }

  function fillSelect(sel, optionsHtml, placeholderHtml) {
    if (!sel) return;
    sel.innerHTML = (placeholderHtml || "") + (optionsHtml || "");
  }

  function getMoveEls() {
    const body = getModalBody();
    if (!body) return {};
    return {
      body,
      boardSel: qs("#move-board", body),
      colSel: qs("#move-column", body),
      posSel: qs("#move-position", body),
    };
  }

  // =====================================================
  // ✅ URL scrub forte: remove ?card= e reaplica por alguns frames
  // Motivo: algum handler pode recolocar o ?card= logo após o move.
  // =====================================================
  function removeCardParamOnce() {
    try {
      const u = new URL(window.location.href);
      if (u.searchParams.has("card")) {
        u.searchParams.delete("card");
        history.replaceState({}, "", u.toString()); // não dispara popstate
      }
    } catch (_e) {}
  }

  function scrubCardParamFor(ms = 700) {
    const until = Date.now() + ms;

    const tick = () => {
      removeCardParamOnce();
      if (Date.now() < until) {
        // requestAnimationFrame pega a “janela” onde outros handlers re-setam URL
        window.requestAnimationFrame(tick);
      }
    };

    tick();
  }

  // =====================================================
  // ✅ Fechamento consistente do modal + limpeza de URL
  // =====================================================
  function closeModalHardAndCleanUrl() {
  //blindagem extra no fechamento “hard” do move
    try {
      const until = Date.now() + 900;
      const prev = Number(window.__modalCloseCooldownUntil || 0);
      window.__modalCloseCooldownUntil = Math.max(prev, until);
    } catch (_e) {}

    // 1) já inicia scrub (garantia)
    scrubCardParamFor(700);

    // 2) fecha modal
    try {
      if (typeof window.closeModal === "function") window.closeModal();
      else {
        const modal = document.getElementById("modal");
        if (modal) {
          modal.classList.remove("modal-open");
          modal.classList.add("hidden");
        }
      }
    } catch (_e) {}

    window.closeModalHardAndCleanUrl = closeModalHardAndCleanUrl;

    // 3) hard reset do body (evita swap residual disparar coisas)
    try {
      const mb = document.getElementById("modal-body");
      if (mb) mb.innerHTML = "";
    } catch (_e) {}

    // 4) estado
    try {
      window.currentCardId = null;
    } catch (_e) {}
  }

  window.loadMoveCardOptions = async function (cardId) {
    const { boardSel, colSel, posSel } = getMoveEls();
    if (!boardSel || !colSel || !posSel) return;

    setMoveError(null);

    fillSelect(boardSel, `<option value="">Carregando…</option>`);
    fillSelect(colSel, `<option value="">Selecione um quadro</option>`);
    fillSelect(posSel, `<option value="">Selecione uma coluna</option>`);
    colSel.disabled = true;
    posSel.disabled = true;

    setCurrentLocationText("carregando…");

    let data;
    let status = 0;
    let raw = "";

    try {
      const r = await fetch(`/card/${cardId}/move/options/`, {
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "application/json",
        },
        credentials: "same-origin",
      });

      status = r.status;
      raw = await r.text();

      if (!r.ok) throw new Error(raw || `HTTP ${status}`);

      try {
        data = JSON.parse(raw);
      } catch (_e) {
        throw new Error(
          `Resposta não é JSON (HTTP ${status}). Início: ${raw.slice(0, 120)}`
        );
      }
    } catch (e) {
      console.error("[move/options] erro:", e);
      setCurrentLocationText("—");
      setMoveError(
        `Falha ao carregar opções de mover. ${
          status ? `HTTP ${status}. ` : ""
        }${String(e?.message || "").slice(0, 180)}`
      );
      fillSelect(boardSel, `<option value="">Erro ao carregar</option>`);
      return;
    }

    const cur = data.current || {};
    const boards = Array.isArray(data.boards) ? data.boards : [];
    const columnsByBoard = data.columns_by_board || {};

    setCurrentLocationText(
      `${cur.board_name || "—"} > ${cur.column_name || "—"} > Posição ${
        cur.position || "—"
      }`
    );

    fillSelect(
      boardSel,
      boards.map((b) => `<option value="${b.id}">${b.name}</option>`).join(""),
      `<option value="">Selecione…</option>`
    );

    boardSel.onchange = () => {
      const bid = String(boardSel.value || "");
      const cols = Array.isArray(columnsByBoard[bid]) ? columnsByBoard[bid] : [];

      colSel.disabled = !bid;
      posSel.disabled = true;

      if (!bid) {
        fillSelect(colSel, `<option value="">Selecione um quadro</option>`);
        fillSelect(posSel, `<option value="">Selecione uma coluna</option>`);
        return;
      }

      fillSelect(
        colSel,
        cols
          .map(
            (c) =>
              `<option value="${c.id}" data-pos-max="${c.positions_total_plus_one}">${c.name}</option>`
          )
          .join(""),
        `<option value="">Selecione…</option>`
      );

      fillSelect(posSel, `<option value="">Selecione uma coluna</option>`);
    };

    colSel.onchange = () => {
      const opt = colSel.selectedOptions?.[0];
      const max = Number(opt?.getAttribute("data-pos-max") || 0);

      posSel.disabled = !opt || !max;

      if (!max) {
        fillSelect(posSel, `<option value="">Selecione uma coluna</option>`);
        return;
      }

      const opts = Array.from({ length: max }, (_x, i) => {
        const v = i + 1; // UX 1-based
        return `<option value="${v}">${v}</option>`;
      }).join("");

      fillSelect(posSel, opts, `<option value="">Selecione…</option>`);
    };

    if (cur.board_id) {
      boardSel.value = String(cur.board_id);
      boardSel.onchange();
    }
    if (cur.column_id) {
      colSel.value = String(cur.column_id);
      colSel.onchange();
    }
    if (cur.position) {
      posSel.value = String(cur.position);
    }
  };

  window.submitMoveCard = async function (cardId, ev) {
    // corta o clique na origem (importantíssimo com CAPTURE global)
    try {
      ev?.preventDefault?.();
      ev?.stopPropagation?.();
      ev?.stopImmediatePropagation?.();
    } catch (_e) {}

    setMoveError(null);
    const { boardSel, colSel, posSel } = getMoveEls();
    if (!boardSel || !colSel || !posSel) {
      setMoveError("UI de mover não encontrada no modal.");
      return;
    }

    const boardId = (boardSel.value || "").trim();
    const columnId = (colSel.value || "").trim();
    const position1 = (posSel.value || "").trim(); // 1-based na UI

    if (!boardId || !columnId || !position1) {
      setMoveError("Selecione quadro, coluna e posição.");
      return;
    }

    const payload = {
      card_id: Number(cardId),
      new_column_id: Number(columnId),
      new_position: Number(position1) - 1, // backend 0-based
    };

    let r;
    try {
      r = await fetch(`/move-card/`, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken(),
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify(payload),
        credentials: "same-origin",
      });
    } catch (_e) {
      setMoveError("Falha de rede ao mover.");
      return;
    }

    if (!r.ok) {
      const t = await r.text().catch(() => "");
      setMoveError(t || `Falha ao mover (HTTP ${r.status}).`);
      return;
    }

    const currentBoardId = getCurrentBoardIdFromUrl();
    const targetBoardId = Number(boardId);

    // =================================================
    // ✅ CASO 1: moveu para outro board
    // - fecha + limpa ?card=
    // - vai para o board destino (colunas)
    // =================================================
    if (currentBoardId && targetBoardId && currentBoardId !== targetBoardId) {
      closeModalHardAndCleanUrl();
      window.location.href = `/board/${targetBoardId}/`;
      return;
    }

    try {
      window.__modalCloseCooldownUntil = Date.now() + 800;
    } catch (_e) {}

    // =================================================
    // ✅ CASO 2: moveu dentro do mesmo board
    // - move DOM
    // - atualiza snippet
    // - fecha + limpa ?card= (sem reabrir)
    // =================================================
    const moved = moveCardDom(cardId, Number(columnId), payload.new_position);

    if (moved) {
      // Faz scrub ANTES e DEPOIS do refresh (porque HTMX pode disparar algo)
      scrubCardParamFor(700);
      window.refreshCardSnippet(cardId);
      closeModalHardAndCleanUrl();
      // scrub final defensivo (garante URL limpa após swaps)
      scrubCardParamFor(700);
      return;
    }

    // Fallback: estado consistente
    closeModalHardAndCleanUrl();
    window.location.reload();
  };
})();

// =====================================================
// Modal Theme: glass | dark (persistente)
// =====================================================

(function () {
  function apply(theme) {
    const modal = document.getElementById("modal");
    const root = document.getElementById("card-modal-root");
    if (!modal || !root) return;

    const isDark = theme === "dark";

    modal.classList.toggle("theme-dark", isDark);
    modal.classList.toggle("theme-glass", !isDark);

    root.classList.toggle("theme-dark", isDark);
    root.classList.toggle("theme-glass", !isDark);

    root.classList.add("modal-glass");

    root.classList.toggle("card-theme-aero", !isDark);
    root.classList.toggle("card-theme-dark", isDark);

    localStorage.setItem("modalTheme", isDark ? "dark" : "glass");
  }

  window.setModalTheme = function (theme) {
    apply(theme || "glass");
  };

  document.addEventListener("DOMContentLoaded", function () {
    apply(localStorage.getItem("modalTheme") || "glass");
  });

  document.body.addEventListener("htmx:afterSwap", function (evt) {
    const t = evt.target;
    if (t && (t.id === "modal-body" || t.closest?.("#modal"))) {
      apply(localStorage.getItem("modalTheme") || "glass");
    }
  });
})();

// =====================================================
// Checklist UX + DnD (Sortable)
// =====================================================

(function () {
  function initChecklistUX(root) {
    const scope = root || document;

    scope.querySelectorAll(".checklist-add").forEach((wrap) => {
      if (wrap.dataset.binded === "1") return;
      wrap.dataset.binded = "1";

      const openBtn = wrap.querySelector(".checklist-add-open");
      const form = wrap.querySelector(".checklist-add-form");
      const cancel = wrap.querySelector(".checklist-add-cancel");
      const input = wrap.querySelector(".checklist-add-input");

      openBtn?.addEventListener("click", () => {
        form?.classList.remove("hidden");
        openBtn?.classList.add("hidden");
        setTimeout(() => input?.focus(), 0);
      });

      cancel?.addEventListener("click", () => {
        form?.classList.add("hidden");
        openBtn?.classList.remove("hidden");
        if (input) input.value = "";
      });
    });
  }

  function initChecklistDnD() {
    const container = document.getElementById("checklists-container");
    if (!container || container.dataset.sortableApplied === "1") return;
    container.dataset.sortableApplied = "1";

    new Sortable(container, {
      animation: 160,
      ghostClass: "drag-ghost",
      chosenClass: "drag-chosen",
      draggable: ".checklist-block",
      handle: ".checklist-drag",
    });

    container.querySelectorAll(".checklist-items").forEach((list) => {
      if (list.dataset.sortableApplied === "1") return;
      list.dataset.sortableApplied = "1";

      new Sortable(list, {
        group: "checklist-items",
        animation: 160,
        ghostClass: "drag-ghost",
        chosenClass: "drag-chosen",
        draggable: ".checklist-item",
        handle: ".checklist-item-handle",
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initChecklistUX(document);
    initChecklistDnD();
  });

  document.body.addEventListener("htmx:afterSwap", (evt) => {
    const t = evt.target;
    if (!t) return;

    if (
      t.id === "checklist-list" ||
      t.id === "modal-body" ||
      t.closest?.("#modal-body")
    ) {
      initChecklistUX(t);
      initChecklistDnD();
    }
  });
})();

// =====================================================
// URL do Card no board: /board/X/?card=ID
// =====================================================

function getCardIdFromUrl() {
  const u = new URL(window.location.href);
  const v = u.searchParams.get("card");
  const id = v ? parseInt(v, 10) : null;
  return Number.isFinite(id) ? id : null;
}

function setUrlCard(cardId, { replace = false } = {}) {
  const u = new URL(window.location.href);
  u.searchParams.set("card", String(cardId));
  if (replace) history.replaceState({ cardId }, "", u.toString());
  else history.pushState({ cardId }, "", u.toString());
}

function clearUrlCard({ replace = false } = {}) {
  const u = new URL(window.location.href);
  u.searchParams.delete("card");
  if (replace) history.replaceState({}, "", u.toString());
  else history.pushState({}, "", u.toString());
}

/**
 * Abre modal + carrega HTML via HTMX
 */
function openCardModalAndLoad(cardId, { replaceUrl = false } = {}) {
  if (!cardId) return;

  setUrlCard(cardId, { replace: !!replaceUrl });

  window.currentCardId = cardId;
  if (typeof window.openModal === "function") window.openModal();

  htmx.ajax("GET", `/card/${cardId}/modal/`, {
    target: "#modal-body",
    swap: "innerHTML",
  });
}

/**
 * Fecha modal e limpa URL
 */
function closeCardModalAndUrl({ replaceUrl = false } = {}) {
  if (typeof window.closeModal === "function") window.closeModal();
  clearUrlCard({ replace: !!replaceUrl });
}

// Auto-open ao carregar /board/X/?card=ID
(function bindCardUrlBootOnce() {
  if (document.body.dataset.cardUrlBootBound === "1") return;
  document.body.dataset.cardUrlBootBound = "1";

  document.addEventListener("DOMContentLoaded", () => {
    const cardId = getCardIdFromUrl();
    if (cardId) {
      openCardModalAndLoad(cardId, { replaceUrl: true });
    }
  });

  // Back/Forward: abre/fecha conforme URL
  window.addEventListener("popstate", () => {
    const cardId = getCardIdFromUrl();
    const modal = document.getElementById("modal");
    const modalIsOpen = modal && modal.classList.contains("modal-open");

    if (cardId) {
      openCardModalAndLoad(cardId, { replaceUrl: true });
    } else if (modalIsOpen) {
      if (typeof window.closeModal === "function") window.closeModal();
    }
  });
})();

// =====================================================
// User Settings Modal (Conta) — abre no mesmo modal global
// =====================================================

(function bindUserSettingsModalOnce() {
  if (document.body.dataset.userSettingsBound === "1") return;
  document.body.dataset.userSettingsBound = "1";

  // Clique no avatar
  document.body.addEventListener(
    "click",
    function (ev) {
      const btn = ev.target.closest("#open-user-settings");
      if (!btn) return;

      ev.preventDefault();
      ev.stopPropagation();

      if (typeof window.openModal === "function") window.openModal();

      htmx.ajax("GET", "/account/modal/", {
        target: "#modal-body",
        swap: "innerHTML",
      });
    },
    true
  );

  // Evento disparado via HX-Trigger (avatar atualizado)
  document.body.addEventListener("userAvatarUpdated", function (ev) {
    const url = ev.detail && ev.detail.url ? String(ev.detail.url) : "";
    if (!url) return;

    const img = document.querySelector("#open-user-settings img");
    if (img) img.src = url;
  });
})();

// END modal.js
