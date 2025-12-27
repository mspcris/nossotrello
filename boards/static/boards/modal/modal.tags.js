// modal.tags.js
(() => {
  if (!window.Modal || window.Modal.tags) return;

  window.Modal.tags = {
    init() {
      document.querySelectorAll("[data-tag]").forEach((el) => {
        el.onclick = () => {
          el.classList.toggle("active");
        };
      });
    },
  };
})();
