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
// Inicializa Quill da descrição
// =====================================================
function initQuillDesc(body) {
  const hiddenDesc = qs("#description-input", body);
  const quillDescEl = qs("#quill-editor", body);

  if (!hiddenDesc || !quillDescEl) return;

  if (quillDescEl.dataset.quillReady === "1") return;
  quillDescEl.dataset.quillReady = "1";

  quillDesc = new Quill("#quill-editor", {
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

  quillDesc.root.innerHTML = hiddenDesc.value || "";

  quillDesc.on("text-change", () => {
    hiddenDesc.value = quillDesc.root.innerHTML;
    markDirty();
  });

  quillDesc.root.addEventListener("paste", (e) => {
    const cd = e.clipboardData;
    if (!cd?.items?.length) return;

    const item = Array.from(cd.items).find(
      (it) => it.kind === "file" && it.type?.startsWith("image/")
    );
    if (!item) return;

    const file = item.getAsFile();
    if (!file) return;

    e.preventDefault();
    insertBase64ImageIntoQuill(quillDesc, file);
  });
}

// =====================================================
// Inicializa Quill da atividade
// =====================================================
function initQuillAtividade(body) {
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
            const currentCount = htmlImageCount(quillAtiv?.root?.innerHTML || "");
            if (currentCount >= 1) {
              toastError("No momento, cada atividade aceita no máximo 1 imagem.");
              return;
            }

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

  quillAtiv.root.addEventListener("paste", (e) => {
    const cd = e.clipboardData;
    if (!cd?.items?.length) return;

    const imgItems = Array.from(cd.items).filter(
      (it) => it.kind === "file" && it.type?.startsWith("image/")
    );

    if (!imgItems.length) return;

    const currentCount = htmlImageCount(quillAtiv.root.innerHTML);
    if (currentCount + imgItems.length > 1) {
      e.preventDefault();
      toastError("No momento, cada atividade aceita no máximo 1 imagem. Cole apenas uma.");
      return;
    }

    e.preventDefault();
    const file = imgItems[0].getAsFile();
    if (file) insertBase64ImageIntoQuill(quillAtiv, file);
  });
}

// =====================================================
// Atividade (sub-tabs): Nova atividade / Histórico / Mover Card
// - Força show/hide via JS (não depende de Tailwind/CSS antigo)
// =====================================================
function initAtivSubtabs3(body) {
  const wrap = qs(".ativ-subtab-wrap", body);
  if (!wrap) return;

  const rNew  = qs("#ativ-tab-new",  wrap);
  const rHist = qs("#ativ-tab-hist", wrap);
  const rMove = qs("#ativ-tab-move", wrap);

  const vNew  = qs(".ativ-view-new",  wrap);
  const vHist = qs(".ativ-view-hist", wrap);
  const vMove = qs(".ativ-view-move", wrap);

  function show(which) {
    // Força aparecer mesmo se vier com .hidden no HTML
    if (vNew) {
      vNew.style.display = (which === "new") ? "block" : "none";
      vNew.classList.toggle("hidden", which !== "new");
    }
    if (vHist) {
      vHist.style.display = (which === "hist") ? "block" : "none";
      vHist.classList.toggle("hidden", which !== "hist");
    }
    if (vMove) {
      vMove.style.display = (which === "move") ? "block" : "none";
      vMove.classList.toggle("hidden", which !== "move");
    }

    if (which === "move" && window.currentCardId && typeof window.loadMoveCardOptions === "function") {
      window.loadMoveCardOptions(window.currentCardId);
    }
  }

  function showFromChecked() {
    if (rMove?.checked) show("move");
    else if (rHist?.checked) show("hist");
    else show("new");
  }

  // expõe helpers (submitActivity / cardOpenTab etc)
  wrap.__ativShow = show;
  wrap.__ativShowFromChecked = showFromChecked;

  // aplica imediatamente (sempre)
  showFromChecked();

  // evita listeners duplicados
  if (wrap.dataset.ativ3Ready === "1") return;
  wrap.dataset.ativ3Ready = "1";

  if (rNew)  rNew.addEventListener("change",  () => { if (rNew.checked)  show("new");  });
  if (rHist) rHist.addEventListener("change", () => { if (rHist.checked) show("hist"); });
  if (rMove) rMove.addEventListener("change", () => { if (rMove.checked) show("move"); });

  // clique no label às vezes não dispara "change"
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

  // tenta capturar cardId do root do modal (fallback do click-capture)
  const root = qs("#card-modal-root");
  const cid = root?.getAttribute?.("data-card-id");
  if (cid) window.currentCardId = Number(cid);

  bindDelegatedDirtyTracking();
  clearDirty();

  initQuillDesc(body);
  initQuillAtividade(body);
  initAtivSubtabs3(body);

  if (window.Prism) Prism.highlightAll();
};

// =====================================================
// Captura cardId antes do HTMX disparar (delegação)
// =====================================================
function bindCardIdCapture() {
  if (document.body.dataset.cardIdCaptureBound) return;
  document.body.dataset.cardIdCaptureBound = "1";

  document.body.addEventListener("click", (ev) => {
    const trigger = ev.target.closest('[hx-target="#modal-body"][hx-get]');
    if (!trigger) return;

    openModal();
    
    const li = trigger.closest("li[data-card-id]");
    if (li?.dataset?.cardId) {
      window.currentCardId = Number(li.dataset.cardId);
      return;
    }
    


    const url = trigger.getAttribute("hx-get") || "";
    const m = url.match(/\/card\/(\d+)\//);
    if (m?.[1]) window.currentCardId = Number(m[1]);
  });
}

bindCardIdCapture();

// =====================================================
// HTMX – após swap do modal-body
// =====================================================
document.body.addEventListener("htmx:afterSwap", function (e) {
  if (!e.detail?.target || e.detail.target.id !== "modal-body") return;

  openModal();
  initCardModal();

  const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
  window.cardOpenTab(active);
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

  initCardModal();

  const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
  window.cardOpenTab(active);
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
    toastError("No momento, cada atividade aceita no máximo 1 imagem. Remova uma das imagens e tente novamente.");
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

  // backend devolve o painel inteiro (card_activity_panel.html)
  const panel = qs("#card-activity-panel", body);
  if (panel) {
    panel.outerHTML = html;
  } else {
    const wrapper = qs("#activity-panel-wrapper", body);
    if (wrapper) wrapper.innerHTML = html;
  }

  window.clearActivityEditor();

  // FIX: marcar checked não dispara change → então a aba não “abre”
  const histRadio = document.getElementById("ativ-tab-hist");
  if (histRadio) {
    histRadio.checked = true;
    histRadio.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // fallback adicional: se por algum motivo listeners não existirem
  const wrap = qs(".ativ-subtab-wrap", body);
  if (wrap?.__ativShow) wrap.__ativShow("hist");

  if (window.Prism) Prism.highlightAll();
};

// =====================================================
// Mover Card (sub-aba em Atividade)
// - carrega opções via GET /card/<id>/move/options/
// - move via POST /move-card/ (JSON)
// - após mover: atualiza DOM (sem F5) e fecha modal
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
    target.querySelectorAll("[data-card-id], li[id^='card-'], #card-" + cardId + ", .card")
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

  // Exposto pro template
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
          "Accept": "application/json",
        },
        credentials: "same-origin",
      });

      status = r.status;

      // Para diagnosticar VM: pode vir HTML/redirect. Então lemos text e parseamos.
      raw = await r.text();

      if (!r.ok) throw new Error(raw || `HTTP ${status}`);

      try {
        data = JSON.parse(raw);
      } catch (e) {
        throw new Error(`Resposta não é JSON (HTTP ${status}). Início: ${raw.slice(0, 120)}`);
      }
    } catch (e) {
      console.error("[move/options] erro:", e);
      setCurrentLocationText("—");
      setMoveError(
        `Falha ao carregar opções de mover. ${status ? `HTTP ${status}. ` : ""}${String(e?.message || "").slice(0, 180)}`
      );
      fillSelect(boardSel, `<option value="">Erro ao carregar</option>`);
      return;
    }

    const cur = data.current || {};
    const boards = Array.isArray(data.boards) ? data.boards : [];
    const columnsByBoard = data.columns_by_board || {};

    setCurrentLocationText(
      `${cur.board_name || "—"} > ${cur.column_name || "—"} > Posição ${cur.position || "—"}`
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

      const opts = Array.from({ length: max }, (_, i) => {
        const v = i + 1; // UX 1-based
        return `<option value="${v}">${v}</option>`;
      }).join("");

      fillSelect(posSel, opts, `<option value="">Selecione…</option>`);
    };

    // Pré-seleção
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

  // Exposto pro template
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

    // 1) Atualiza DOM na board (sem F5)
    const currentBoardId = getCurrentBoardIdFromUrl();
    const targetBoardId = Number(boardId);

    // Mover para outro quadro: reload garante consistência (card some do quadro atual)
    if (currentBoardId && targetBoardId && currentBoardId !== targetBoardId) {
      closeModal();
      window.location.reload();
      return;
    }

    // tenta mover nó do card pra coluna/posição nova
    const moved = moveCardDom(cardId, Number(columnId), payload.new_position);

    // refresh do snippet garante update de labels/título/etc
    if (moved) {
      window.refreshCardSnippet(cardId);
    } else {
      closeModal();
      window.location.reload();
      return;
    }

    // 2) Fecha modal (move = ação final)
    closeModal();
  };
})();



// ===== Modal Theme: glass | dark (persistente) =====
(function () {
  function apply(theme) {
    const modal = document.getElementById("modal");
    const root  = document.getElementById("card-modal-root");
    if (!modal || !root) return;

    const isDark = theme === "dark";

    modal.classList.toggle("theme-dark",  isDark);
    modal.classList.toggle("theme-glass", !isDark);

    root.classList.toggle("theme-dark",  isDark);
    root.classList.toggle("theme-glass", !isDark);

    // se você quiser manter o “aero” no glass:
    root.classList.toggle("card-theme-aero", !isDark);
    root.classList.toggle("card-theme-dark", isDark);

    localStorage.setItem("modalTheme", isDark ? "dark" : "glass");
  }

  window.setModalTheme = function (theme) {
    apply(theme || "glass");
  };

  // default
  document.addEventListener("DOMContentLoaded", function () {
    apply(localStorage.getItem("modalTheme") || "glass");
  });

  // HTMX swaps: reaplica após trocar conteúdo do modal
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    const t = evt.target;
    if (t && (t.id === "modal-body" || t.closest?.("#modal"))) {
      apply(localStorage.getItem("modalTheme") || "glass");
    }
  });
})();

(function () {
  function initChecklistUX(root) {
    const scope = root || document;

    // abrir/fechar “Adicionar um item”
    scope.querySelectorAll(".checklist-add").forEach(wrap => {
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

    // DnD de checklists (card)
    new Sortable(container, {
      animation: 160,
      ghostClass: "drag-ghost",
      chosenClass: "drag-chosen",
      draggable: ".checklist-block",
      handle: ".checklist-drag",
    });

    // DnD de itens (entre checklists também)
    container.querySelectorAll(".checklist-items").forEach(list => {
      if (list.dataset.sortableApplied === "1") return;
      list.dataset.sortableApplied = "1";

      new Sortable(list, {
        group: "checklist-items",
        animation: 160,
        ghostClass: "drag-ghost",
        chosenClass: "drag-chosen",
        draggable: ".checklist-item",
        handle: ".item-drag",
      });
    });
  }

  // inicializa no load e após swaps HTMX do modal
  document.addEventListener("DOMContentLoaded", () => {
    initChecklistUX(document);
    initChecklistDnD();
  });

  document.body.addEventListener("htmx:afterSwap", (evt) => {
    // quando o checklist-list ou modal-body trocar, reinicializa
    const t = evt.target;
    if (!t) return;

    if (t.id === "checklist-list" || t.id === "modal-body" || t.closest?.("#modal-body")) {
      initChecklistUX(t);
      initChecklistDnD();
    }
  });
})();
