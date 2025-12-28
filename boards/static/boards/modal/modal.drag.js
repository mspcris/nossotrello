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

  // ============================
  // POINTER DOWN
  // ============================
  document.addEventListener(
    "pointerdown",
    function (e) {
      const card = getCard(e.target);
      if (!card) return;

      // ignora botões internos
      if (e.target.closest("button, a, [hx-get], [hx-post]")) return;

      startX = e.clientX;
      startY = e.clientY;
      moved = false;
      activeCard = card;
      window.__isDraggingCard = false;
    },
    true
  );

  // ============================
  // POINTER MOVE
  // ============================
  document.addEventListener(
    "pointermove",
    function (e) {
      if (!activeCard) return;

      const dx = Math.abs(e.clientX - startX);
      const dy = Math.abs(e.clientY - startY);

      if (dx > DRAG_THRESHOLD || dy > DRAG_THRESHOLD) {
        moved = true;
        window.__isDraggingCard = true;
      }
    },
    true
  );

  // ============================
  // POINTER UP
  // ============================
  document.addEventListener(
    "pointerup",
    function () {
      if (!activeCard) return;

      const card = activeCard;
      activeCard = null;

      // CLICK REAL → abre modal (via Facade)
      if (!moved) {
        const cardId = Number(card.dataset.cardId);

        // evita "double fire" (click + pointerup)
        if (cardId) {
          try {
            // delega para o fluxo oficial (modal.open.js)
            if (window.Modal?.openCard) {
              window.Modal.openCard(cardId, false);
            } else if (window.htmx) {
              // fallback mínimo (não ideal, mas seguro)
              window.htmx.ajax("GET", `/card/${cardId}/modal/`, {
                target: "#modal-body",
                swap: "innerHTML",
              });
            }
          } catch (_e) {
          // silencioso: não derruba UX do board
          }
        }
      }


      moved = false;

      setTimeout(() => {
        window.__isDraggingCard = false;
      }, 0);
    },
    true
  );
})();
//END boards/static/boards/modal/modal.drag.js