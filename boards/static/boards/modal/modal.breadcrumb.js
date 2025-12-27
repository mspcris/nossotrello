// modal.breadcrumb.js
(() => {
  if (!window.Modal || window.Modal.breadcrumb) return;

  function qs(sel) {
    return document.querySelector(sel);
  }

  window.Modal.breadcrumb = {
    render() {
      const host = qs("#modal-breadcrumb");
      const title = qs("#modal-body input[name='title']");

      if (!host || !title) return;

      host.textContent = title.value || "Card";
    },

    bind() {
      const input = qs("#modal-body input[name='title']");
      if (!input || input.dataset.bcBound) return;

      input.dataset.bcBound = "1";
      input.addEventListener("input", this.render);
    },
  };
})();
