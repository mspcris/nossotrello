// boards/static/boards/modal/modal.open.js
(() => {
  console.log("[modal.open] loaded");

  if (!window.Modal) {
    console.error("[modal.open] modal.core.js não carregado (window.Modal ausente)");
    return;
  }

  if (typeof window.Modal.openCard === "function") return;

  function getModalBody() {
    return document.getElementById("modal-body");
  }

  function safeOpenModal() {
    if (typeof window.Modal.open === "function") {
      window.Modal.open();
      const modal = document.getElementById("modal");
      if (modal) modal.setAttribute("aria-hidden", "false");
    }
  }

  function buildCardModalUrl(cardId) {
    // padrão do seu server log: GET /card/135/modal/
    return `/card/${cardId}/modal/`;
  }

  function loadCard(cardId, replaceUrl = false) {
    const id = Number(cardId);
    if (!id) return;

    if (typeof window.Modal.canOpen === "function" && !window.Modal.canOpen()) return;

    const target = getModalBody();
    if (!target) {
      console.error("[modal.open] #modal-body não existe no DOM");
      return;
    }

    const now = Date.now();
    if (window.Modal?.state?.lastOpenedAt && now - window.Modal.state.lastOpenedAt < 250) {
      // evita dupla chamada na mesma interação
      return;
    }

    // marca estado antes do request
    window.Modal.state.currentCardId = id;

    // URL helper (se existir)
    if (window.Modal.url && typeof window.Modal.url.set === "function") {
      window.Modal.url.set(id, { replace: !!replaceUrl });
    }

    // abre visual imediatamente
    safeOpenModal();

    const hx = window.htmx;
    if (!hx || typeof hx.ajax !== "function") {
      console.error("[modal.open] HTMX não carregado (window.htmx ausente).");
      return;
    }

    const url = buildCardModalUrl(id);

    hx.ajax("GET", url, {
      target: target,
      swap: "innerHTML",
    });
  }

  document.addEventListener(
    "click",
    (ev) => {
      const card = ev.target.closest("li[data-card-id], .card-item[data-card-id]");
      if (!card) return;

      if (ev.target.closest("button, a, input, textarea, select, [contenteditable='true'], [hx-get], [hx-post]")) {
        return;
      }

      if (window.__isDraggingCard) return;

      if (typeof window.Modal.canOpen === "function" && !window.Modal.canOpen()) return;

      if (ev.defaultPrevented || ev.__modalHandled) return;

      ev.preventDefault();
      ev.stopPropagation();
      ev.__modalHandled = true;

      const cardId = Number(card.dataset.cardId);
      loadCard(cardId, false);
    },
    true
  );

  document.addEventListener("htmx:afterSwap", (e) => {
    const target = e.detail?.target || e.target;
    if (!target || target.id !== "modal-body") return;
    safeOpenModal();
  });

  document.addEventListener("DOMContentLoaded", () => {
    if (window.Modal.url && typeof window.Modal.url.getCardIdFromUrl === "function") {
      const cardId = window.Modal.url.getCardIdFromUrl();
      if (cardId) loadCard(cardId, true);
    }
  });

  window.Modal.openCard = loadCard;
})();
