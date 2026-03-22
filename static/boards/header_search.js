// boards/static/boards/header_search.js
// Header search overlay (board) — abre no toggle, fecha no ESC e ao clicar fora (igual popover)
// - Usa capture=true para não depender de bubbling
// - Não fecha ao clicar dentro do painel
// - Não “briga” com o clique do toggle
// - Mantém is-typing (backdrop) sincronizado e reseta ao fechar

(function () {
  const toggle = document.getElementById("header-search-toggle");
  const overlay = document.getElementById("board-search-overlay");

  if (!toggle || !overlay) return;

  function isOpen() {
    return !overlay.classList.contains("hidden");
  }

  function open() {
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
  }

  function close() {
    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
    overlay.classList.remove("is-typing"); // reset do backdrop ao fechar
  }

  // Toggle abre/fecha
  toggle.addEventListener("click", function (e) {
    e.preventDefault();
    e.stopPropagation();

    if (isOpen()) close();
    else open();
  });

  // Clique fora (igual popover) — CAPTURE
  document.addEventListener(
    "click",
    function (e) {
      if (!isOpen()) return;

      const panel =
        overlay.querySelector(".search-panel") ||
        overlay.querySelector("[data-search-panel]");

      // clique no toggle não fecha (toggle já gerencia)
      if (toggle.contains(e.target)) return;

      // clique dentro do painel não fecha
      if (panel && panel.contains(e.target)) return;

      // qualquer clique fora fecha
      close();
    },
    true
  );

  // ESC fecha
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

  // reset ao fechar (quando ESC)
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      overlay.classList.remove("is-typing");
    }
  });
})();
