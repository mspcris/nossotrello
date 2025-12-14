// =====================================================
// modal.js — Modal do Card (HTMX + Quill)
// - Form único (Descrição + Etiquetas)
// - Savebar sticky só quando houver mudanças
// - Savebar aparece apenas em: Descrição e Etiquetas
// - Sem temas (fixado em aero)
// - Listeners por delegação (não duplica após HTMX swap)
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
  const modal = document.getElementById("modal");
  if (modal) modal.classList.remove("hidden");
};

window.closeModal = function () {
  const modal = document.getElementById("modal");
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
// Alternar abas do modal
// =====================================================
window.cardOpenTab = function (panelId) {
  qsa(".card-tab-btn").forEach((btn) => {
    btn.classList.toggle(
      "card-tab-active",
      btn.getAttribute("data-tab-target") === panelId
    );
  });

  qsa(".card-tab-panel").forEach((panel) => {
    const isTarget = panel.id === panelId;
    panel.classList.toggle("block", isTarget);
    panel.classList.toggle("hidden", !isTarget);
  });

  sessionStorage.setItem("modalActiveTab", panelId);

  if (!tabsWithSave.has(panelId)) hideSavebar();
  else maybeShowSavebar();
};

// =====================================================
// Tema — DESATIVADO (mantido só pra não quebrar onclick legado)
// =====================================================
window.cardSetTheme = function () {
  // temas removidos: modal fixo em aero
};

// =====================================================
// Inserir imagem no Quill como base64 (para o backend extrair na hora do Save)
// =====================================================
function insertBase64ImageIntoQuill(quill, file) {
  if (!quill || !file) return;

  const reader = new FileReader();
  reader.onload = () => {
    const dataUrl = reader.result; // "data:image/png;base64,..."
    const range = quill.getSelection(true) || { index: quill.getLength() };

    quill.insertEmbed(range.index, "image", dataUrl, "user");
    quill.setSelection(range.index + 1, 0, "user");
    markDirty();
  };
  reader.readAsDataURL(file);
}

// =====================================================
// Dirty tracking por delegação (1x)
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
// Inicializa modal (pós-swap)
// =====================================================
window.initCardModal = function () {
  const body = getModalBody();
  if (!body) return;

  // Card ID
  const root = qs("#card-modal-root", body);
  if (root) {
    const cid = root.getAttribute("data-card-id");
    window.currentCardId = cid ? Number(cid) : null;

    // FIXO: aero (sem alternância)
    root.classList.remove("card-theme-white", "card-theme-dark");
    if (!root.classList.contains("card-theme-aero")) root.classList.add("card-theme-aero");
  }

  bindDelegatedDirtyTracking();
  clearDirty();

  // Quill — Descrição
  const hiddenDesc = qs("#description-input", body);
  const quillDescEl = qs("#quill-editor", body);

  if (hiddenDesc && quillDescEl && !quillDescEl.dataset.quillReady) {
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

  const item = Array.from(cd.items).find((it) => it.kind === "file" && it.type?.startsWith("image/"));
  if (!item) return;

  const file = item.getAsFile();
  if (!file) return;

  e.preventDefault();
  insertBase64ImageIntoQuill(quillDesc, file);
});

  }

  // Quill — Atividade
  const activityHidden = qs("#activity-input", body);
  const quillAtivEl = qs("#quill-editor-ativ", body);

  if (activityHidden && quillAtivEl && !quillAtivEl.dataset.quillReady) {
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
        },
      },
    });

    quillAtiv.root.innerHTML = "";
    activityHidden.value = "";

    quillAtiv.on("text-change", () => {
      activityHidden.value = quillAtiv.root.innerHTML;
    });
  }

  // Sub-abas atividade (delegação)
  if (!body.dataset.ativSubtabsBound) {
    body.dataset.ativSubtabsBound = "1";

    body.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".ativ-subtab-btn");
      if (!btn) return;
      const target = btn.getAttribute("data-subtab");
      if (target) ativSwitchSubTab(target);
    });
  }

  if (window.Prism) Prism.highlightAll();
};

// =====================================================
// HTMX – após swap do modal-body
// =====================================================
document.body.addEventListener("htmx:afterSwap", function (e) {
  if (!e.detail?.target || e.detail.target.id !== "modal-body") return;

  openModal();
  initCardModal();

  const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
  cardOpenTab(active);
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
  cardOpenTab(active);
};

// =====================================================
// Atividade helpers
// =====================================================
window.clearActivityEditor = function () {
  const activityHidden = document.getElementById("activity-input");
  if (quillAtiv) quillAtiv.setText("");
  if (activityHidden) activityHidden.value = "";
};

window.submitActivity = async function (cardId) {
  const activityInput = document.getElementById("activity-input");
  if (!activityInput) return;

  const content = activityInput.value.trim();
  if (!content) return;

  const formData = new FormData();
  formData.append("content", content);

  const response = await fetch(`/card/${cardId}/activity/add/`, {
    method: "POST",
    headers: { "X-CSRFToken": getCsrfToken() },
    body: formData,
    credentials: "same-origin",
  });

  if (!response.ok) return;

  const html = await response.text();
  const wrapper = document.getElementById("activity-panel-wrapper");
  if (wrapper) wrapper.innerHTML = html;

  //clearActivityEditor();
  //ativSwitchSubTab("ativ-historico-panel");

  if (window.Prism) Prism.highlightAll();
};

window.ativSwitchSubTab = function (panelId) {
  qsa(".ativ-subtab-panel").forEach((p) => p.classList.add("hidden"));

  const panel = document.getElementById(panelId);
  if (panel) panel.classList.remove("hidden");

  qsa(".ativ-subtab-btn").forEach((b) => b.classList.remove("ativ-subtab-active"));

  const btn = document.querySelector(`.ativ-subtab-btn[data-subtab='${panelId}']`);
  if (btn) btn.classList.add("ativ-subtab-active");
};
