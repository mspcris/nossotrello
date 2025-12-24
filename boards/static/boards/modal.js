// =====================================================
// modal.js — Modal do Card (HTMX + Quill)
// - Form único (Descrição + Etiquetas)
// - Savebar sticky só quando houver mudanças
// - Modal com scroll único em #modal-body.card-modal-scroll (base.html)
// - Atividade: "Incluir" atualiza histórico e limpa Quill
// - Abas internas Atividade: Nova atividade / Histórico / Mover Card
// - Mover: atualiza DOM sem F5 e fecha modal
// =====================================================

window.currentCardId = null;

let quillDesc = null;
let quillAtiv = null;

// Abas que suportam “savebar”
const tabsWithSave = new Set(["card-tab-desc", "card-tab-tags"]);

function getCsrfToken() {
  return document.querySelector("meta[name='csrf-token']")?.content || "";
}

function qs(sel, root = document) {
  return root.querySelector(sel);
}

function qsa(sel, root = document) {
  return Array.from(root.querySelectorAll(sel));
}
function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function getBoardIdFromUrl() {
  const m = (window.location.pathname || "").match(/\/board\/(\d+)\//);
  return m?.[1] ? Number(m[1]) : null;
}

function getModalEl() {
  return document.getElementById("modal");
}

function getModalBody() {
  return document.getElementById("modal-body");
}

function getMainForm() {
  const body = getModalBody();
  if (!body) return null;
  return qs("#card-desc-form", body);
}

function getSavebarElements() {
  const form = getMainForm();
  if (!form) return { bar: null, saveBtn: null };

  const bar = qs("#desc-savebar", form);
  const saveBtn = qs("button[type='submit']", form);
  return { bar, saveBtn };
}

// =====================================================
// CM modal (tabs) — funciona após HTMX swap (sem script inline)
// =====================================================
function initCmModal(body) {
  const root = body?.querySelector?.("#cm-root");
  if (!root) return;

  const tabs = Array.from(root.querySelectorAll("[data-cm-tab]"));
  const panels = Array.from(root.querySelectorAll("[data-cm-panel]"));
  if (!tabs.length || !panels.length) return;

  const saveBtn = root.querySelector("#cm-save-btn");
  const form = root.querySelector("#cm-main-form");

  function setSaveVisibility(activeName) {
    const shouldShowSave = activeName === "desc" || activeName === "tags";
    if (!saveBtn) return;

    saveBtn.classList.toggle("hidden", !shouldShowSave);
    saveBtn.style.display = shouldShowSave ? "" : "none";
    saveBtn.disabled = !shouldShowSave;
  }

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

  // bind tabs 1x
  tabs.forEach((b) => {
    if (b.dataset.cmBound === "1") return;
    b.dataset.cmBound = "1";

    b.addEventListener("click", (ev) => {
      // ✅ evita submit / navegação / clique vazar
      ev.preventDefault();
      ev.stopPropagation();

      const name = b.getAttribute("data-cm-tab");
      sessionStorage.setItem("cmActiveTab", name);
      activate(name);
    });
  });

  // default: último aberto, senão desc
  activate(sessionStorage.getItem("cmActiveTab") || "desc");

  // botão salvar do CM (bind 1x)
  if (saveBtn && form && saveBtn.dataset.cmBound !== "1") {
    saveBtn.dataset.cmBound = "1";
    saveBtn.addEventListener("click", () => {
      const active = root.dataset.cmActive || "desc";
      if (active !== "desc" && active !== "tags") return;

      try {
        form.requestSubmit();
      } catch (e) {
        form.submit();
      }
    });
  }
}

// =====================================================
// CM modal — extras (cores de tags + erros anexos/atividade)
// - roda a cada abertura do modal CM via initCardModal()
// - listeners globais instalados 1x
// =====================================================
function cmGetRoot(body) {
  return body?.querySelector?.("#cm-root") || document.getElementById("cm-root");
}

function cmEnsureTagColorsState(root) {
  if (!root) return;
  if (!root.dataset.tagColors) {
    root.dataset.tagColors = root.getAttribute("data-tag-colors") || "{}";
  }
}

function cmApplySavedTagColors(root) {
  if (!root) return;

  let colors = {};
  try {
    const raw =
      root.dataset.tagColors || root.getAttribute("data-tag-colors") || "{}";
    colors = JSON.parse(raw);
    if (!colors || typeof colors !== "object") colors = {};
  } catch (e) {
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

function cmInitTagColorPicker(root) {
  if (!root) return;

  // bind 1x por root (root troca a cada HTMX swap)
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
    } catch {}

    picker.value = colors[tag] || "#3b82f6";

    const mb = document.getElementById("modal-body");
    const mbRect = mb?.getBoundingClientRect() || { top: 0, left: 0 };

    const rect = btn.getBoundingClientRect();
    const top = rect.bottom - mbRect.top + (mb?.scrollTop || 0);
    const left = rect.left - mbRect.left + (mb?.scrollLeft || 0);

    pop.style.top = top + "px";
    pop.style.left = left + "px";

    pop.classList.remove("hidden");
  });

  cancel.addEventListener("click", function () {
    pop.classList.add("hidden");
    currentBtn = null;
  });

  save.addEventListener("click", function () {
    if (!currentBtn) return;

    const tag = currentBtn.dataset.tag;
    const color = picker.value;

    // UI imediata
    currentBtn.style.backgroundColor = color + "20";
    currentBtn.style.color = color;
    currentBtn.style.borderColor = color;

    // estado local
    let colors = {};
    try {
      colors = JSON.parse(
        root.dataset.tagColors || root.getAttribute("data-tag-colors") || "{}"
      );
    } catch {}
    colors[tag] = color;
    root.dataset.tagColors = JSON.stringify(colors);

    // payload
    inpTag.value = tag;
    inpCol.value = color;

    pop.classList.add("hidden");

    // persistência via endpoint do form
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
        // atualiza tags no modal
        const wrapEl = document.getElementById("cm-tags-wrap");
        if (wrapEl && data.modal) wrapEl.innerHTML = data.modal;

        // atualiza card na board
        const cardEl = document.getElementById("card-" + data.card_id);
        if (cardEl && data.snippet) cardEl.outerHTML = data.snippet;

        applyBoardTagColorsNow();

        // rebind seguro (novo HTML)
        const rootNow = document.getElementById("cm-root");
        cmEnsureTagColorsState(rootNow);
        cmApplySavedTagColors(rootNow);
        cmInitTagColorPicker(rootNow);
      })
      .catch((err) => console.error(err));
  });
}

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
    } catch (e) {}
  });
}

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
      root.querySelector('form[data-cm-cover-form]') ||
      root.querySelector('form[action*="cover"]') ||
      null
    );
  }

  function getCoverInput(root) {
    if (!root) return null;
    // tenta pelo id primeiro, depois por name, depois por tipo
    return (
      root.querySelector("#cm-cover-file") ||
      root.querySelector('input[name="cover"][type="file"]') ||
      root.querySelector('input[type="file"][accept*="image"]') ||
      root.querySelector('input[type="file"]') ||
      null
    );
  }

  function isPastingInsideQuill(e) {
    const ae = document.activeElement;
    if (
      ae &&
      ae.closest &&
      ae.closest(".ql-editor, .ql-container, #quill-editor, #quill-editor-ativ, #cm-quill-editor-ativ")
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
    // garante que o campo vai junto mesmo se o input tiver outro name
    fd.set("cover", file);

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
    } catch (e) {
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

    if (typeof window.initCardModal === "function") window.initCardModal();
  }

  // 1) Clique no botão/label “Escolher imagem…”
  // - capture=true pra pegar mesmo se alguém parar a propagação
  document.body.addEventListener(
    "click",
    (e) => {
      const root = getRoot();
      if (!root) return;

      // pega por id OU por atributos mais genéricos
      const pick =
        e.target.closest("#cm-cover-pick-btn") ||
        e.target.closest("[data-cm-cover-pick]") ||
        e.target.closest(".cm-cover-pick");

      if (!pick) return;

      console.log("[cover] clique em escolher imagem detectado");

      const inp = getCoverInput(root);
      if (!inp) {
        console.warn("[cover] input file não encontrado");
        return;
      }

      // alguns browsers exigem que o click aconteça no mesmo callstack do gesto do usuário
      inp.click();
    },
    true
  );

// 2) Selecionou no file picker (SÓ CAPA)
document.body.addEventListener(
  "change",
  (e) => {
    const root = getRoot();
    if (!root) return;

    const inp = e.target;
    if (!inp || inp.type !== "file") return;

    // ✅ Só trata como CAPA se for o input correto
    const isCoverInput =
      inp.matches?.("#cm-cover-file") ||
      inp.matches?.('input[name="cover"][type="file"]') ||
      !!inp.closest?.("#cm-cover-form");

    if (!isCoverInput) return;

    const file = inp.files?.[0];
    console.log("[cover] change file detectado", file?.name, file?.type);

    if (!file) return;

    // validação defensiva (evita DOC cair aqui)
    if (!(file.type || "").startsWith("image/")) {
      showCoverErr("Arquivo inválido: envie uma imagem.");
      try { inp.value = ""; } catch (_e) {}
      return;
    }

    uploadCover(file);
    try { inp.value = ""; } catch (_e) {}
  },
  true
);


  // 3) Ctrl+V (fora do Quill) na aba desc: vira capa
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
      console.log("[cover] paste imagem detectado", file?.name, file?.type);

      if (!file) return;

      e.preventDefault();
      uploadCover(file);
    },
    true
  );
}

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
// Abrir / Fechar modal
// =====================================================
window.openModal = function () {
  const modal = getModalEl();
  if (!modal) return;

  modal.classList.remove("hidden");
  modal.classList.remove("modal-closing");

  // força o browser a aplicar o estado inicial antes do transition
  void modal.offsetHeight;

  modal.classList.add("modal-open");
};

window.closeModal = function () {
  const modal = getModalEl();
  const modalBody = getModalBody();
  
  try {
  // só limpa se tiver ?card na URL
  const cardId = getCardIdFromUrl();
  if (cardId) clearUrlCard({ replace: false });
} catch (e) {}

  
  if (!modal) return;

  // inicia animação de saída
  modal.classList.remove("modal-open");
  modal.classList.add("modal-closing");

  // tempo alinhado com o CSS (220ms)
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
window.refreshCardSnippet = function (cardId) {
  if (!cardId) return;

  htmx.ajax("GET", `/card/${cardId}/snippet/`, {
    target: `#card-${cardId}`,
    swap: "outerHTML",
  });
};

// =====================================================
// Savebar helpers
// =====================================================
function hideSavebar() {
  const { bar, saveBtn } = getSavebarElements();
  if (!bar) return;

  bar.classList.add("hidden");
  bar.style.display = "none";
  if (saveBtn) saveBtn.disabled = true;
}

function applyBoardTagColorsNow() {
  if (typeof window.applySavedTagColorsToBoard === "function") {
    window.applySavedTagColorsToBoard(document);
  }
}

function showSavebar() {
  const { bar, saveBtn } = getSavebarElements();
  if (!bar) return;

  bar.classList.remove("hidden");
  bar.style.display = "";
  if (saveBtn) saveBtn.disabled = false;
}

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
function htmlImageCount(html) {
  const tmp = document.createElement("div");
  tmp.innerHTML = html || "";
  return tmp.querySelectorAll("img").length;
}

function toastError(msg) {
  alert(msg);
}

// =====================================================
// Alternar abas do modal (escopo: dentro do #modal)
// =====================================================
window.cardOpenTab = function (panelId) {
  const modal = getModalEl();
  if (!modal) return;

  qsa(".card-tab-btn", modal).forEach((btn) => {
    btn.classList.toggle(
      "card-tab-active",
      btn.getAttribute("data-tab-target") === panelId
    );
  });

  const body = getModalBody();
  if (!body) return;

  qsa(".card-tab-panel", body).forEach((panel) => {
    const isTarget = panel.id === panelId;
    panel.classList.toggle("block", isTarget);
    panel.classList.toggle("hidden", !isTarget);
  });

  sessionStorage.setItem("modalActiveTab", panelId);

  if (!tabsWithSave.has(panelId)) hideSavebar();
  else maybeShowSavebar();

  // ao entrar na aba "Atividade", reaplica a sub-aba correta
  if (panelId === "card-tab-ativ") {
    const wrap = qs(".ativ-subtab-wrap", body);
    if (wrap?.__ativShowFromChecked) wrap.__ativShowFromChecked();
  }
};

// =====================================================
// Inserir imagem no Quill como base64
// =====================================================
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
// ✅ CORREÇÃO: Inicializa Quill da descrição (evita initQuillDesc is not defined)
// - tenta IDs comuns (#quill-editor / #quill-editor-desc) e hidden comuns
// - sincroniza HTML -> hidden; marca dirty ao editar; suporta paste de imagens
// =====================================================
function initQuillDesc(body) {
  if (!body) return;

  // =========================
  // 1) LEGADO (já existente)
  // =========================
  const legacyHost =
    qs("#quill-editor", body) ||
    qs("#quill-editor-desc", body) ||
    qs("[data-quill-desc]", body);

  if (legacyHost) {
    if (legacyHost.dataset.quillReady === "1") return;
    legacyHost.dataset.quillReady = "1";

    const hidden =
      qs("#desc-input", body) ||
      qs("#description-input", body) ||
      qs('input[name="description"]', body) ||
      qs('textarea[name="description"]', body) ||
      qs('textarea[name="desc"]', body) ||
      qs('input[name="desc"]', body);

    const selector =
      legacyHost.id
        ? `#${legacyHost.id}`
        : (() => {
            legacyHost.id = "quill-editor-desc";
            return "#quill-editor-desc";
          })();

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

    const initialHtml = (hidden?.value || "").trim();
    quillDesc.root.innerHTML = initialHtml || "";

    quillDesc.on("text-change", () => {
      if (hidden) hidden.value = quillDesc.root.innerHTML;
      markDirty();
    });

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

  // =========================
  // 2) CM (textarea -> Quill)
  // =========================
  const cmRoot = qs("#cm-root", body);
  if (!cmRoot) return;

  const descPanel = cmRoot.querySelector('[data-cm-panel="desc"]');
  if (!descPanel) return;

  const textarea = descPanel.querySelector('textarea[name="description"]');
  if (!textarea) return;

  if (textarea.dataset.cmQuillReady === "1") return;
  textarea.dataset.cmQuillReady = "1";

  // cria host do quill logo antes do textarea
  const host = document.createElement("div");
  host.id = "cm-quill-editor-desc";
  host.className = "border rounded mb-2";
  host.style.minHeight = "220px";
  textarea.parentNode.insertBefore(host, textarea);

  // esconde textarea (mas mantém para o POST)
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
        const div = document.createElement("div");
        div.className = "mention-item";
        div.innerHTML = `<strong>@${escapeHtml(item.value)}</strong>
          <div style="font-size:12px;opacity:.7">${escapeHtml(item.email || "")}</div>`;
        return div;
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
          if (!last.textContent?.startsWith("@")) last.textContent = "@" + item.value;

          // mantém seu sync
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
          renderList(Array.isArray(data) ? data : (data.results || []), searchTerm);
        } catch (e) {
          renderList([], searchTerm);
        }
      },
    },
  },
});

  // conteúdo inicial
  q.root.innerHTML = (textarea.value || "").trim() || "";

  // sync Quill -> textarea + dirty
  q.on("text-change", () => {
    textarea.value = q.root.innerHTML;
    markDirty();
  });

  // paste de imagem (capture)
  const onPaste = (e) => {
    const cd = e.clipboardData;
    if (!cd?.items?.length) return;

    const imgItems = Array.from(cd.items).filter(
      (it) => it.kind === "file" && (it.type || "").startsWith("image/")
    );
    if (!imgItems.length) return;

    e.preventDefault();
    e.stopPropagation();
    if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();

    imgItems.forEach((it) => {
      const file = it.getAsFile();
      if (file) insertBase64ImageIntoQuill(q, file);
    });
  };

  if (q.root.__onPasteCmDesc) {
    q.root.removeEventListener("paste", q.root.__onPasteCmDesc, true);
  }
  q.root.__onPasteCmDesc = onPaste;
  q.root.addEventListener("paste", onPaste, true);

  // guarda referência global, se quiser reutilizar (opcional)
  quillDesc = q;
}































// =====================================================
// Inicializa editor da atividade
// - LEGADO: #quill-editor-ativ + #activity-input
// - CM: textarea[name="content"] dentro do painel ativ (vira Quill e sincroniza)
// =====================================================
function initQuillAtividade(body) {
  if (!body) return;

  // -----------------------------
  // 1) CM (novo modal: #cm-root)
  // -----------------------------
  const cmRoot = qs("#cm-root", body);
  if (cmRoot) {
    const ativPanel = cmRoot.querySelector('[data-cm-panel="ativ"]');
    if (!ativPanel) return;

    const form = ativPanel.querySelector('form[hx-post*="add_activity"], form');
    const textarea = ativPanel.querySelector('textarea[name="content"]');

    // Se não tem textarea, não há o que fazer
    if (!form || !textarea) return;

    // Evita reinicializar
    if (textarea.dataset.cmQuillReady === "1") return;
    textarea.dataset.cmQuillReady = "1";

    // Cria o container do Quill antes do textarea
    const host = document.createElement("div");
    host.id = "cm-quill-editor-ativ";
    host.className = "border rounded mb-2";
    host.style.minHeight = "140px";

    textarea.parentNode.insertBefore(host, textarea);

    // Esconde o textarea (mas mantém no form para HTMX enviar)
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
        const div = document.createElement("div");
        div.className = "mention-item";
        div.innerHTML = `<strong>@${escapeHtml(item.value)}</strong>
          <div style="font-size:12px;opacity:.7">${escapeHtml(item.email || "")}</div>`;
        return div;
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
          if (!last.textContent?.startsWith("@")) last.textContent = "@" + item.value;

          // mantém seu sync
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
          renderList(Array.isArray(data) ? data : (data.results || []), searchTerm);
        } catch (e) {
          renderList([], searchTerm);
        }
      },
    },
  },
});


    // Foco/click mais previsível
    try {
      q.root.setAttribute("tabindex", "0");
    } catch (e) {}

    // Conteúdo inicial (se houver)
    const initial = (textarea.value || "").trim();
    q.root.innerHTML = initial || "";

    // Sync do Quill -> textarea (para o HTMX enviar)
    q.on("text-change", () => {
      textarea.value = q.root.innerHTML;
    });

    // ✅ Paste de imagens (CAPTURE) no Quill do CM
    const onPasteCmAtiv = (e) => {
      const cd = e.clipboardData;
      if (!cd?.items?.length) return;

      const imgItems = Array.from(cd.items).filter(
        (it) => it.kind === "file" && (it.type || "").startsWith("image/")
      );
      if (!imgItems.length) return;

      e.preventDefault();
      e.stopPropagation();
      if (typeof e.stopImmediatePropagation === "function") {
        e.stopImmediatePropagation();
      }

      imgItems.forEach((it) => {
        const file = it.getAsFile();
        if (file) insertBase64ImageIntoQuill(q, file);
      });
    };

    // remove anterior, se reabrir modal
    if (q.root.__onPasteCmAtiv) {
      q.root.removeEventListener("paste", q.root.__onPasteCmAtiv, true);
    }
    q.root.__onPasteCmAtiv = onPasteCmAtiv;
    q.root.addEventListener("paste", onPasteCmAtiv, true);

    // Limpar: se o form for resetado pelo hx-on::after-request, também limpa o Quill
    // (o seu form tem hx-on::after-request="this.reset()")
    if (form.dataset.cmQuillResetBound !== "1") {
      form.dataset.cmQuillResetBound = "1";
      form.addEventListener("reset", () => {
        try {
          q.setText("");
        } catch (e) {}
        textarea.value = "";
      });
    }

    return; // CM tratado; não continuar pro legado
  }

  // -----------------------------
  // 2) LEGADO
  // -----------------------------
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
    if (typeof e.stopImmediatePropagation === "function") {
      e.stopImmediatePropagation();
    }

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
// - Força show/hide via JS (não depende de Tailwind/CSS antigo)
// =====================================================
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

  wrap.__ativShow = show;
  wrap.__ativShowFromChecked = showFromChecked;

  showFromChecked();

  if (wrap.dataset.ativ3Ready === "1") return;
  wrap.dataset.ativ3Ready = "1";

  if (rNew)
    rNew.addEventListener("change", () => {
      if (rNew.checked) show("new");
    });
  if (rHist)
    rHist.addEventListener("change", () => {
      if (rHist.checked) show("hist");
    });
  if (rMove)
    rMove.addEventListener("change", () => {
      if (rMove.checked) show("move");
    });

  qsa(".ativ-subtab-btn", wrap).forEach((lbl) => {
    lbl.addEventListener("click", () => setTimeout(showFromChecked, 0));
  });
}

// =====================================================
// Inicializa modal (pós-swap)
// =====================================================
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

  // ✅ agora existe (corrige o ReferenceError do console)
  initQuillDesc(body);

  initQuillAtividade(body);
  initAtivSubtabs3(body);

  if (window.Prism) Prism.highlightAll();

  // CM
  initCmModal(body);
  cmBoot(body);
};

// =====================================================
// ABERTURA RADICAL DO MODAL + MOBILE
// =====================================================
(function bindCardOpenRadical() {
  if (document.body.dataset.cardOpenRadicalBound === "1") return;
  document.body.dataset.cardOpenRadicalBound = "1";

  function shouldIgnoreClick(ev) {
    const ignoreSelectors = [
      ".delete-card-btn",
      "[data-no-modal]",
      "button",
      "a[href]",
      "input",
      "textarea",
      "select",
      "label",
      "form",
    ];
    return ignoreSelectors.some((sel) => ev.target.closest(sel));
  }

  let touchStartY = 0;
  let touchMoved = false;

  // 👉 MOBILE
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
      if (deltaY > 10) {
        touchMoved = true;
      }
    },
    { passive: true }
  );

  document.body.addEventListener(
    "touchend",
    (ev) => {
      const cardEl = ev.target.closest("li[data-card-id]");
      if (!cardEl) return;
      if (touchMoved) return;
      if (shouldIgnoreClick(ev)) return;

      const cardId = Number(cardEl.dataset.cardId || 0);
      if (!cardId) return;

      ev.preventDefault();
      ev.stopPropagation();

      openCardModalAndLoad(cardId, { replaceUrl: false });
    },
    true
  );

  // 👉 DESKTOP (mantém como está)
  document.body.addEventListener(
    "click",
    (ev) => {
      const cardEl = ev.target.closest("li[data-card-id]");
      if (!cardEl) return;
      if (shouldIgnoreClick(ev)) return;

      const cardId = Number(cardEl.dataset.cardId || 0);
      if (!cardId) return;

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
// Remover TAG
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

  // reativa JS do modal (CM/legado)
  initCardModal();

  // se for modal legado (não-CM), mantém a aba atual
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
// Atividade helpers
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
  } catch (err) {
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
// Mover Card
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
      } catch (e) {
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
      const cols = Array.isArray(columnsByBoard[bid])
        ? columnsByBoard[bid]
        : [];

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

      const opts = Array.from({ length: max }, (_, i) => {
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

  window.submitMoveCard = async function (cardId) {
    const { boardSel, colSel, posSel } = getMoveEls();
    if (!boardSel || !colSel || !posSel) return;

    setMoveError(null);

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
    } catch (e) {
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

    if (currentBoardId && targetBoardId && currentBoardId !== targetBoardId) {
      closeModal();
      window.location.reload();
      return;
    }

    const moved = moveCardDom(cardId, Number(columnId), payload.new_position);

    if (moved) {
      window.refreshCardSnippet(cardId);
    } else {
      closeModal();
      window.location.reload();
      return;
    }

    closeModal();
  };
})();

// ===== Modal Theme: glass | dark (persistente) =====
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

// ===== Checklist UX + DnD =====
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
// - ao abrir modal por clique: pushState (?card=ID)
// - ao abrir por URL (load/popstate): replaceState (mantém URL)
// - ao fechar modal: remove ?card
// - back/forward: abre/fecha modal conforme URL
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

// abre modal + carrega HTML (mesmo fluxo do clique)
function openCardModalAndLoad(cardId, { replaceUrl = false } = {}) {
  if (!cardId) return;

  // 1) URL
  setUrlCard(cardId, { replace: !!replaceUrl });

  // 2) modal + HTMX
  window.currentCardId = cardId;
  if (typeof window.openModal === "function") window.openModal();

  htmx.ajax("GET", `/card/${cardId}/modal/`, {
    target: "#modal-body",
    swap: "innerHTML",
  });
}

// fecha modal + limpa URL
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
      // replace pra não criar histórico extra no load
      openCardModalAndLoad(cardId, { replaceUrl: true });
    }
  });

  // Back/Forward
  window.addEventListener("popstate", () => {
    const cardId = getCardIdFromUrl();
    const modal = document.getElementById("modal");
    const modalIsOpen = modal && modal.classList.contains("modal-open");

    if (cardId) {
      openCardModalAndLoad(cardId, { replaceUrl: true });
    } else if (modalIsOpen) {
      // fecha sem empurrar nova history
      if (typeof window.closeModal === "function") window.closeModal();
    }
  });
})();

