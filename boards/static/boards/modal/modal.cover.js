// boards/static/boards/modal/modal.cover.js
(() => {
  if (!window.Modal) return;

  window.Modal.cover = window.Modal.cover || {};

  function getRoot() {
    return document.getElementById("cm-root");
  }

  function showErr(msg) {
    const root = getRoot();
    const box = root?.querySelector?.("#cm-cover-error");
    if (!box) return;
    box.textContent = msg;
    box.classList.remove("hidden");
  }

  function hideErr() {
    const root = getRoot();
    const box = root?.querySelector?.("#cm-cover-error");
    if (!box) return;
    box.classList.add("hidden");
    box.textContent = "";
  }

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
  }

  async function refreshModalBody(cardId) {
    const url = `/card/${cardId}/modal/`;
    const r = await fetch(url, { headers: { "HX-Request": "true" } });
    if (!r.ok) return;

    const html = await r.text();
    const modalBody = document.getElementById("modal-body");
    if (modalBody) modalBody.innerHTML = html;

    // rebind depois do swap manual
    window.Modal.init?.();
  }

  async function refreshBoardCardSnippet(cardId) {
    try {
      // melhor esforço: procura o card no board pelo data-card-id
      const el = document.querySelector(`[data-card-id="${cardId}"]`);
      if (!el) return;

      const r = await fetch(`/card/${cardId}/snippet/`, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!r.ok) return;

      const html = (await r.text()).trim();
      if (!html) return;

      const tmp = document.createElement("div");
      tmp.innerHTML = html;
      const node = tmp.firstElementChild;
      if (node) el.replaceWith(node);
    } catch (_e) {}
  }

  async function uploadCover(file) {
    const root = getRoot();
    if (!root) return;

    const form = root.querySelector("#cm-cover-form");
    const action = form?.getAttribute("action");
    if (!action) {
      showErr("Form de capa não encontrado (cm-cover-form/action).");
      return;
    }

    hideErr();

    if (!(file?.type || "").startsWith("image/")) {
      showErr("Arquivo inválido: envie uma imagem.");
      return;
    }

    const cardId = root.getAttribute("data-card-id");
    if (!cardId) {
      showErr("data-card-id não encontrado no cm-root.");
      return;
    }

    const fd = new FormData();
    fd.append("cover", file);

    // CSRF (Django)
    const csrftoken = getCookie("csrftoken");

    const r = await fetch(action, {
      method: "POST",
      body: fd,
      headers: csrftoken ? { "X-CSRFToken": csrftoken } : {},
      credentials: "same-origin",
    });

    if (!r.ok) {
      showErr(`Falha ao enviar capa. HTTP ${r.status}`);
      return;
    }

    // 1) atualiza modal (capa/preview)
    await refreshModalBody(cardId);

    // 2) atualiza o card no board (thumbnail/cover)
    await refreshBoardCardSnippet(cardId);
  }

  function isPastingInsideQuill(e) {
    const path = e.composedPath?.() || [];
    return path.some((el) => el?.classList?.contains?.("ql-editor"));
  }

  window.Modal.cover.init = function () {
    if (window.Modal.cover.__BOUND__) return;
    window.Modal.cover.__BOUND__ = true;

// ABRIR PICKER: usar pointerdown em capture (mais confiável que click)
document.addEventListener(
  "pointerdown",
  (e) => {
    const root = getRoot();
    if (!root) return;

    const pick = e.target?.closest?.("#cm-cover-pick-btn");
    if (!pick) return;

    // trava o gesto aqui, antes de outros handlers do modal
    e.preventDefault();
    e.stopPropagation();

    const inp = document.getElementById("cm-cover-file");
    if (!(inp instanceof HTMLInputElement)) {
      showErr("Input de capa não encontrado (cm-cover-file).");
      return;
    }

    // garante que escolher o mesmo arquivo dispare eventos
    try { inp.value = ""; } catch (_e) {}

    // abre o picker (precisa ser síncrono e dentro do gesto)
    inp.click();
  },
  true
);

// PROCESSAR ARQUIVO: change + input (alguns browsers disparam um ou outro primeiro)
function handleFilePicked(target) {
  const root = getRoot();
  if (!root) return;

  if (!(target instanceof HTMLInputElement)) return;
  if (target.id !== "cm-cover-file") return;

  const file = target.files?.[0];
  if (!file) return;

  uploadCover(file).finally(() => {
    try { target.value = ""; } catch (_e) {}
  });
}

document.addEventListener(
  "change",
  (e) => handleFilePicked(e.target),
  true
);

document.addEventListener(
  "input",
  (e) => handleFilePicked(e.target),
  true
);

    // PASTE (Ctrl+V) na aba Descrição -> upload
    document.addEventListener(
      "paste",
      (e) => {
        const root = getRoot();
        if (!root) return;

        const active = root.dataset.cmActive || "desc";
        if (active !== "desc") return;

        if (isPastingInsideQuill(e)) return;

        const cd = e.clipboardData;
        const items = cd?.items ? Array.from(cd.items) : [];
        const imgItem = items.find((it) => (it.type || "").startsWith("image/"));
        if (!imgItem) return;

        const file = imgItem.getAsFile?.();
        if (!file) return;

        e.preventDefault();
        uploadCover(file);
      },
      true
    );
  };
})();
