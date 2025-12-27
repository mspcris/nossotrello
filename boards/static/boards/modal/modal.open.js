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

    htmx.ajax("GET", `/card/${cardId}/modal/`, {
      target: "#modal-body",
      swap: "innerHTML",
    });
  }

  // Clique no card
  document.body.addEventListener(
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
  document.body.addEventListener("htmx:afterSwap", (e) => {
    if (e.target.id !== "modal-body") return;

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
