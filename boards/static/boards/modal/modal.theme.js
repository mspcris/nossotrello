// modal.theme.js
(() => {
  if (!window.Modal || window.Modal.theme) return;

  const root = document.getElementById("card-modal-root");

  window.Modal.theme = {
    set(mode) {
      if (!root) return;

      root.classList.remove("theme-dark", "theme-glass");
      root.classList.add(`theme-${mode}`);
    },
  };

  // alias de compatibilidade
  window.setModalTheme = (m) => window.Modal.theme.set(m);
})();
