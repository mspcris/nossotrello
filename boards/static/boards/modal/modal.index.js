// modal.index.js
(() => {
  if (!window.Modal || window.Modal.__BOOT__) return;
  window.Modal.__BOOT__ = true;

  window.Modal.init = function () {
    window.Modal.quill?.init();
    window.Modal.tags?.init();
    window.Modal.breadcrumb?.render();
    window.Modal.breadcrumb?.bind();
  };
})();
