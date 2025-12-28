// modal.open.js — abertura do modal + HTMX
(() => {
  if (!window.Modal) {
    console.error("modal.core.js não carregado");
    return;
  }

  if (window.Modal.openCard) return;

  function loadCard(cardId, replaceUrl = false) {
    if (!cardId) return;
    if (!window.Modal.canOpen()) return;

    window.Modal.state.currentCardId = cardId;
    window.Modal.url.set(cardId, { replace: replaceUrl });

    const hx = window.htmx;
    if (!hx || typeof hx.ajax !== "function") {
      console.error("HTMX não carregado (window.htmx ausente).");
      return;
    }

    hx.ajax("GET", `/card/${cardId}/modal/`, {
      target: "#modal-body",
      swap: "innerHTML",
    });
  }

  // Clique no card
  document.addEventListener(
  "click",
  (ev) => {
    const card = ev.target.closest("li[data-card-id]");
    if (!card) return;
    if (!window.Modal.canOpen()) return;

    ev.preventDefault();
    ev.stopPropagation();

    const cardId = Number(card.dataset.cardId);
    loadCard(cardId, false);
  },
  true
);

    // HTMX: modal carregou conteúdo
  document.addEventListener("htmx:afterSwap", (e) => {
    const target = e.detail?.target || e.target;
    if (!target || target.id !== "modal-body") return;
    if (!window.Modal.canOpen()) return;

    window.Modal.open();
});
  // Boot por URL (?card=)
  document.addEventListener("DOMContentLoaded", () => {
    const cardId = window.Modal.url.getCardIdFromUrl();
    if (cardId) loadCard(cardId, true);
  });

  window.Modal.openCard = loadCard;
})();
//END modal.open.js — abertura do modal + HTMX