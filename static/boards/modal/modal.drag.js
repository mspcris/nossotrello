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

      // --------------------------------------------------
      // DETECTAR DROP DE CARD E SINCRONIZAR COM BACKEND
      // --------------------------------------------------
      if (moved) {

        const card = ev.target.closest(".card-item, li[data-card-id]");
        if (!card) return;

        const cardId = Number(card.dataset.cardId);
        if (!cardId) return;

        const column = card.closest("[data-column-id]");
        if (!column) return;

        const columnId = Number(column.dataset.columnId);

        const siblings = Array.from(
          column.querySelectorAll("li[data-card-id]")
        );

        const newPosition = siblings.indexOf(card);

        try {

          fetch("/move_card/", {
            method: "POST",
            credentials: "same-origin",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": document.querySelector("meta[name='csrf-token']")?.content
            },
            body: JSON.stringify({
              card_id: cardId,
              new_column_id: columnId,
              new_position: newPosition
            })
          })
          .then(r => r.json())
          .then(data => {

            if (!data || data.status !== "ok") {
              location.reload();
              return;
            }

            const el = document.querySelector(`li[data-card-id="${data.card_id}"]`);
            if (el && data.snippet) {
              el.outerHTML = data.snippet;
            }

          })
          .catch(() => location.reload());

        } catch (_e) {
          location.reload();
        }

      }

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
