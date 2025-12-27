// modal.user.js
(() => {
  if (!window.Modal || window.Modal.user) return;

  window.Modal.user = {
    open() {
      fetch("/account/modal/")
        .then((r) => r.text())
        .then((html) => {
          document.getElementById("modal-body").innerHTML = html;
          window.Modal.open();
        });
    },
  };

  document.body.addEventListener("click", (e) => {
    if (e.target.closest("#open-user-settings")) {
      e.preventDefault();
      window.Modal.user.open();
    }
  });
})();
