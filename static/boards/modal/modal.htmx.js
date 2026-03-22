// modal.htmx.js
(() => {
  if (!window.Modal || window.Modal.htmx) return;

  window.Modal.htmx = {};

  document.body.addEventListener("htmx:afterSwap", (e) => {
    if (!e.target || e.target.id !== "modal-body") return;

    if (!window.Modal.canOpen()) {
      window.Modal.close();
      return;
    }

    window.Modal.open();
    window.Modal.init?.();

    // ✅ reinit Quill após o swap do conteúdo do modal
    window.Modal.quill?.init?.();
  });
})();
//END modal.htmx.js