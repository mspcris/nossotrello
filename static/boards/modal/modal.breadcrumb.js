// modal.breadcrumb.js
(() => {
  if (!window.Modal || window.Modal.breadcrumb) return;

  function qs(sel) {
    return document.querySelector(sel);
  }

  window.Modal.breadcrumb = {
    render() {
      const host = qs("#modal-breadcrumb");
      if (!host) return;

      const root     = qs("#cm-root");
      const board    = root?.dataset.board        || "";
      const column   = root?.dataset.column       || "";
      const position = root?.dataset.cardPosition || "";

      const parts = [board, column, position ? `#${position}` : ""].filter(Boolean);
      host.textContent = parts.join("  ›  ");
    },

    bind() {
      // dados vêm dos data-attributes do #cm-root, não precisam de listener
    },
  };
})();
