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

  // limpa o tab ativo para voltar consistente (opcional)
  // sessionStorage.removeItem("modalActiveTab");
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

  // painéis ficam dentro do modal-body (conteúdo dinâmico)
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
    const dataUrl = reader.result; // "data:image/png;base64,..."
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

  // evita duplicar init
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
      toolbar: [
        [{ header: [1, 2, 3, false] }],
        ["bold", "italic", "underline"],
        ["link", "image"],
        [{ list: "ordered" }, { list: "bullet" }],
      ],
    },
  });

  quillAtiv.root.innerHTML = "";
  activityHidden.value = "";

  quillAtiv.on("text-change", () => {
    activityHidden.value = quillAtiv.root.innerHTML;
  });
}

// =====================================================
// Inicializa modal (pós-swap)
// =====================================================
window.initCardModal = function () {
  const body = getModalBody();
  if (!body) return;

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

    // tenta achar o card na árvore
    const li = trigger.closest("li[data-card-id]");
    if (li?.dataset?.cardId) {
      window.currentCardId = Number(li.dataset.cardId);
      return;
    }

    // fallback: tenta extrair do hx-get (/card/123/...)
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
// Remover TAG (mantém seu fluxo atual)
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

function replaceActivityPanelFromHTML(html) {
  const body = getModalBody();
  if (!body) return;

  const current = qs("#activity-panel-wrapper", body);
  if (!current) return;

  const doc = new DOMParser().parseFromString(html, "text/html");
  const incoming = doc.querySelector("#activity-panel-wrapper");

  // se a resposta já vem com wrapper completo
  if (incoming) {
    current.outerHTML = incoming.outerHTML;
    return;
  }

  // senão, coloca como conteúdo interno
  current.innerHTML = html;
}

window.submitActivity = async function (cardId) {
  const body = getModalBody();
  if (!body) return;

  const activityInput = qs("#activity-input", body);
  if (!activityInput) return;

  const content = (activityInput.value || "").trim();
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

  // atualiza histórico
  replaceActivityPanelFromHTML(html);

  // limpa editor (o que você pediu)
  window.clearActivityEditor();

  // garante que o usuário continue na aba Atividade e vá pro Histórico
  window.cardOpenTab("card-tab-ativ");
  const histRadio = qs("#ativ-subtab-history", body);
  if (histRadio) histRadio.checked = true;

  if (window.Prism) Prism.highlightAll();
};
