(function () {
  function norm(s) {
    return (s || "")
      .toString()
      .trim()
      .toLowerCase();
  }

  function getAllCards() {
    return Array.from(document.querySelectorAll(".board-card[data-board-id]"));
  }

  function applyFilter(raw) {
    const q = norm(raw);
    const cards = getAllCards();

    // mostra tudo se query vazia
    if (!q) {
      cards.forEach(el => (el.style.display = ""));
      // reexibe blocos (grupos/favoritos) caso tenham sido ocultados
      document.querySelectorAll(".home-group-block, #home-favorites-block").forEach(b => (b.style.display = ""));
      return;
    }

    cards.forEach(el => {
      const name = norm(el.getAttribute("data-board-name") || el.textContent);
      el.style.display = name.includes(q) ? "" : "none";
    });

    // Oculta blocos/grupos que ficaram sem cards visíveis
    // (favoritos + cada home-group-block)
    const blocks = Array.from(document.querySelectorAll(".home-group-block, #home-favorites-block"));
    blocks.forEach(block => {
      const visible = block.querySelectorAll(".board-card[data-board-id]:not([style*='display: none'])").length > 0;
      block.style.display = visible ? "" : "none";
    });
  }

  function init() {
    const input = document.getElementById("home-board-search");
    if (!input) return;

    input.addEventListener("input", () => applyFilter(input.value));
  }

  window.HomeBoardSearch = {
    apply: applyFilter,
  };

  document.addEventListener("DOMContentLoaded", init);
})();
