// =====================================================
// modal.js — Modal do Card (HTMX + Quill)
// - Form único (Descrição + Etiquetas)
// - Savebar sticky só quando houver mudanças
// - Modal com scroll único em #modal-body.card-modal-scroll (base.html)
// - Atividade: "Incluir" atualiza histórico e limpa Quill
// - Sem listeners duplicados após HTMX swap
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
  if (modal) modal.classList.remove("hidden");
};

window.closeModal = function () {
  const modal = getModalEl();
  const modalBody = getModalBody();

  if (modal) modal.classList.add("hidden");
  if (modalBody) modalBody.innerHTML = "";

  window.currentCardId = null;
  quillDesc = null;
  quillAtiv = null;
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
// Inicializa Quill da atividade (FIX: estava solto e quebrava o modal)
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

  // Seu backend parece devolver HTML pra este wrapper (ou parcial).
  const panel = qs("#card-activity-panel", body);
  if (panel) panel.outerHTML = html;


  window.clearActivityEditor();

  const histRadio = document.getElementById("ativ-tab-hist");
  if (histRadio) histRadio.checked = true;

  if (window.Prism) Prism.highlightAll();
};


// =====================================================
// Atividade: sub-aba Histórico | Mover Card
// =====================================================

function setAtivSubtab(which) {
  const body = getModalBody();
  if (!body) return;

  const hist = qs("#ativ-panel-hist", body);
  const move = qs("#ativ-panel-move", body);
  const bHist = qs("#ativ-subtab-btn-hist", body);
  const bMove = qs("#ativ-subtab-btn-move", body);

  if (!hist || !move) return;

  const isHist = which === "hist";

  hist.classList.toggle("hidden", !isHist);
  hist.classList.toggle("block", isHist);

  move.classList.toggle("hidden", isHist);
  move.classList.toggle("block", !isHist);

  if (bHist) bHist.classList.toggle("font-semibold", isHist);
  if (bMove) bMove.classList.toggle("font-semibold", !isHist);
}

async function loadMoveCardOptions(cardId) {
  const body = getModalBody();
  if (!body) return;

  const boardSel = qs("#move-board", body);
  const colSel = qs("#move-column", body);
  const posSel = qs("#move-position", body);
  const loc = qs("#move-current-location", body);
  const err = qs("#move-error", body);

  if (!boardSel || !colSel || !posSel || !loc) return;

  if (err) {
    err.classList.add("hidden");
    err.textContent = "";
  }

  boardSel.innerHTML = `<option value="">Carregando…</option>`;
  colSel.innerHTML = `<option value="">Selecione um quadro</option>`;
  posSel.innerHTML = `<option value="">Selecione uma coluna</option>`;
  colSel.disabled = true;
  posSel.disabled = true;

  let data;
  try {
    const r = await fetch(`/card/${cardId}/move/options/`, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    data = await r.json();
  } catch (e) {
    if (err) {
      err.textContent = "Falha ao carregar opções de mover.";
      err.classList.remove("hidden");
    }
    loc.textContent = "—";
    boardSel.innerHTML = `<option value="">Erro ao carregar</option>`;
    return;
  }

  const cur = data.current || {};
  loc.textContent = `${cur.board_name || "—"} > ${cur.column_name || "—"} > Posição ${cur.position || "—"}`;

  const boards = Array.isArray(data.boards) ? data.boards : [];
  const columnsByBoard = data.columns_by_board || {};

  boardSel.innerHTML =
    `<option value="">Selecione…</option>` +
    boards.map((b) => `<option value="${b.id}">${b.name}</option>`).join("");

  boardSel.onchange = () => {
    const bid = boardSel.value;
    const cols = Array.isArray(columnsByBoard[String(bid)]) ? columnsByBoard[String(bid)] : [];

    colSel.disabled = !bid;
    posSel.disabled = true;

    colSel.innerHTML = bid
      ? `<option value="">Selecione…</option>` +
        cols
          .map(
            (c) =>
              `<option value="${c.id}" data-pos-max="${c.positions_total_plus_one}">${c.name}</option>`
          )
          .join("")
      : `<option value="">Selecione um quadro</option>`;

    posSel.innerHTML = `<option value="">Selecione uma coluna</option>`;
  };

  colSel.onchange = () => {
    const opt = colSel.selectedOptions?.[0];
    const max = Number(opt?.getAttribute("data-pos-max") || 0);

    posSel.disabled = !opt || !max;
    if (!max) {
      posSel.innerHTML = `<option value="">Selecione uma coluna</option>`;
      return;
    }

    posSel.innerHTML =
      `<option value="">Selecione…</option>` +
      Array.from({ length: max }, (_, i) => `<option value="${i + 1}">${i + 1}</option>`).join("");
  };

  // pré-seleção (melhor UX)
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
}

async function refreshActivityPanel(cardId) {
  const body = getModalBody();
  if (!body) return;

  let html = "";
  try {
    const r = await fetch(`/card/${cardId}/activity/panel/`, { credentials: "same-origin" });
    if (!r.ok) return;
    html = await r.text();
  } catch (e) {
    return;
  }

  const panel = qs("#card-activity-panel", body);
  if (panel) panel.outerHTML = html;
}

async function submitMoveCard(cardId) {
  const body = getModalBody();
  if (!body) return;

  const boardSel = qs("#move-board", body);
  const colSel = qs("#move-column", body);
  const posSel = qs("#move-position", body);
  const err = qs("#move-error", body);

  const boardId = boardSel?.value;
  const columnId = colSel?.value;
  const position1 = posSel?.value;

  if (err) {
    err.classList.add("hidden");
    err.textContent = "";
  }

  if (!boardId || !columnId || !position1) {
    if (err) {
      err.textContent = "Selecione quadro, coluna e posição.";
      err.classList.remove("hidden");
    }
    return;
  }

  // Seu move_card espera JSON e new_position 0-based
  const payload = {
    card_id: Number(cardId),
    new_column_id: Number(columnId),
    new_position: Number(position1) - 1,
  };

  let r;
  try {
    r = await fetch(`/move-card/`, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCsrfToken(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      credentials: "same-origin",
    });
  } catch (e) {
    if (err) {
      err.textContent = "Falha de rede ao mover.";
      err.classList.remove("hidden");
    }
    return;
  }

  if (!r.ok) {
    const msg = await r.text().catch(() => "");
    if (err) {
      err.textContent = msg || `Falha ao mover (HTTP ${r.status}).`;
      err.classList.remove("hidden");
    }
    return;
  }

  // Atualiza histórico para aparecer o CardLog do move e volta pro Histórico
  await refreshActivityPanel(cardId);
  setAtivSubtab("hist");

  if (window.Prism) Prism.highlightAll();
}

(function bindAtivMoveOnce() {
  if (window.__ativMoveBound) return;
  window.__ativMoveBound = true;

  document.body.addEventListener("click", (ev) => {
    const t = ev.target.closest("[data-ativ-subtab]");
    if (t) {
      const which = t.getAttribute("data-ativ-subtab");
      setAtivSubtab(which);

      if (which === "move" && window.currentCardId) {
        loadMoveCardOptions(window.currentCardId);
      }
      return;
    }

    const btnMove = ev.target.closest("#btn-move-card");
    if (btnMove && window.currentCardId) {
      submitMoveCard(window.currentCardId);
    }
  });

  // default: manter Histórico selecionado quando re-renderiza painel
  document.body.addEventListener("htmx:afterSwap", (e) => {
    if (!e.detail?.target || e.detail.target.id !== "modal-body") return;
    setAtivSubtab("hist");
  });
})();
