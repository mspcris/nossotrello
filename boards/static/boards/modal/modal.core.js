// boards/static/boards/modal/modal.core.js
(() => {
  if (window.Modal) return; // evita double-load

  window.Modal = {
    state: {
      currentCardId: null,
      isOpen: false,
    },

    open() {
      const modal = document.getElementById("modal");
      if (!modal) return;

      modal.classList.remove("hidden");
      modal.classList.add("modal-open");
      this.state.isOpen = true;
    },

    close() {
      const modal = document.getElementById("modal");
      const body = document.getElementById("modal-body");

      if (!modal) return;

      modal.classList.remove("modal-open");
      modal.classList.add("hidden");

      if (body) body.innerHTML = "";

      this.state.isOpen = false;
      this.state.currentCardId = null;
    },
  };
})();
