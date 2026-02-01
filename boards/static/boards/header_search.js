(function () {
  const toggle = document.getElementById("header-search-toggle");
  const overlay = document.getElementById("board-search-overlay");

  if (!toggle || !overlay) return;

  function open() {
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
  }

  function close() {
    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
  }

  toggle.addEventListener("click", function (e) {
    e.preventDefault();
    e.stopPropagation();
    open();
  });

  overlay.addEventListener("click", function (e) {
    if (e.target === overlay || e.target.closest(".bg-black")) {
      close();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") close();
  });
})();

(function () {
  const overlay = document.getElementById("board-search-overlay");
  if (!overlay) return;

  const input = overlay.querySelector("input");
  if (!input) return;

  function syncBackdrop() {
    const typing = input.value.trim().length > 0;
    overlay.classList.toggle("is-typing", typing);
  }

  input.addEventListener("input", syncBackdrop);
  input.addEventListener("focus", syncBackdrop);

  // reset ao fechar
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      overlay.classList.remove("is-typing");
    }
  });
})();

