// modal.quill.js
(() => {
  if (!window.Modal || window.Modal.quill) return;

  window.Modal.quill = {
    init() {
      if (!window.Quill) return;

      document
        .querySelectorAll("[data-quill]")
        .forEach((el) => {
          if (el.dataset.ready) return;
          el.dataset.ready = "1";

          new Quill(el, { theme: "snow" });
        });
    },
  };
})();
