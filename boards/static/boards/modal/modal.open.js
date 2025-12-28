// boards/static/boards/modal/modal.open.js
(() => {
  if (!window.Modal) {
    console.error("[modal.open] modal.core.js não carregado");
    return;
  }

  if (typeof window.Modal.openCard === "function") return;

  function getModalBody() {
    return document.getElementById("modal-body");
  }

  function buildCardModalUrl(cardId) {
    return `/card/${cardId}/modal/`;
  }

  function loadCard(cardId, replaceUrl = false, cardEl = null) {
    const id = Number(cardId);
    if (!id) return;

    if (typeof window.Modal.canOpen === "function" &&
        !window.Modal.canOpen()) return;

    const target = getModalBody();
    if (!target) {
      console.error("[modal.open] #modal-body não encontrado");
      return;
    }

    const now = Date.now();
    if (window.Modal.state.lastOpenedAt &&
        now - window.Modal.state.lastOpenedAt < 250) {
      return;
    }

    // 🔑 captura geometria do card (base do Genie)
    if (cardEl?.getBoundingClientRect) {
      window.Modal.state.lastCardRect = cardEl.getBoundingClientRect();
    } else {
      window.Modal.state.lastCardRect = null;
    }

    window.Modal.state.currentCardId = id;

    if (window.Modal.url?.set) {
      window.Modal.url.set(id, { replace: !!replaceUrl });
    }

    // abre imediatamente (animação no core)
    window.Modal.open();

    if (!window.htmx?.ajax) {
      console.error("[modal.open] HTMX não disponível");
      return;
    }

    window.htmx.ajax("GET", buildCardModalUrl(id), {
      target,
      swap: "innerHTML",
    });
  }

  // ============================================================
  // CLICK GLOBAL NOS CARDS
  // ============================================================
  document.addEventListener(
    "click",
    (ev) => {
      const card = ev.target.closest(
        "li[data-card-id], .card-item[data-card-id]"
      );
      if (!card) return;

      if (ev.target.closest(
        "button, a, input, textarea, select, [contenteditable], [hx-get], [hx-post]"
      )) return;

      if (window.__isDraggingCard) return;
      if (typeof window.Modal.canOpen === "function" &&
          !window.Modal.canOpen()) return;
      if (ev.defaultPrevented || ev.__modalHandled) return;

      ev.preventDefault();
      ev.stopPropagation();
      ev.__modalHandled = true;

      loadCard(card.dataset.cardId, false, card);
    },
    true
  );

  // ============================================================
  // URL DIRECT LOAD
  // ============================================================
  document.addEventListener("DOMContentLoaded", () => {
    if (window.Modal.url?.getCardIdFromUrl) {
      const cardId = window.Modal.url.getCardIdFromUrl();
      if (cardId) loadCard(cardId, true, null);
    }
  });

  window.Modal.openCard = loadCard;
})();
