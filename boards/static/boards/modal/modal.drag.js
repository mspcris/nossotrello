// boards/static/boards/modal/modal.drag.js
// RESPONSABILIDADE ÚNICA:
// - Diferenciar CLICK de DRAG
// - Abrir modal SOMENTE se for click
// - NUNCA interferir no SortableJS

(function () {
  console.log("[modal.drag] loaded");

  const DRAG_THRESHOLD = 6;

  let startX = 0;
  let startY = 0;
  let moved = false;
  let activeCard = null;

  window.__isDraggingCard = false;

  function getCard(el) {
    return el && el.closest && el.closest(".card-item, li[data-card-id]");
  }

  document.addEventListener(
    "pointerdown",
    function (ev) {
      const card = getCard(ev.target);
      if (!card) return;

      if (ev.target.closest("button, a, input, textarea, select, [contenteditable='true'], [hx-get], [hx-post]")) {
        return;
      }

      startX = ev.clientX;
      startY = ev.clientY;
      moved = false;
      activeCard = card;
      window.__isDraggingCard = false;
    },
    true
  );

  document.addEventListener(
    "pointermove",
    function (ev) {
      if (!activeCard) return;

      const dx = Math.abs(ev.clientX - startX);
      const dy = Math.abs(ev.clientY - startY);

      if (dx > DRAG_THRESHOLD || dy > DRAG_THRESHOLD) {
        moved = true;
        window.__isDraggingCard = true;
      }
    },
    true
  );

  document.addEventListener(
    "pointerup",
    function (ev) {
      if (!activeCard) return;

      if (ev.defaultPrevented || ev.__modalHandled) {
        activeCard = null;
        moved = false;
        window.__isDraggingCard = false;
        return;
      }

      const card = activeCard;
      activeCard = null;

      if (!moved) {
        const cardId = Number(card.dataset.cardId);
        if (cardId) {
          try {
            if (window.Modal && typeof window.Modal.openCard === "function") {
              window.Modal.openCard(cardId, false);
              ev.__modalHandled = true;
            }
          } catch (_e) {
            // silencioso
          }
        }
      }

      moved = false;
      setTimeout(() => { window.__isDraggingCard = false; }, 0);
    },
    true
  );
})();
