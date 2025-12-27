// modal.drag.js — mover card
(() => {
  if (!window.Modal) {
    console.error("modal.core.js não carregado");
    return;
  }

  if (window.Modal.moveCard) return;

  function getCsrf() {
    return document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  }

  function moveCardDom(cardId, columnId, position) {
    const card = document.getElementById(`card-${cardId}`);
    if (!card) return false;

    const col =
      document.querySelector(`#cards-col-${columnId}`) ||
      document.querySelector(`[data-column-id="${columnId}"] ul`);

    if (!col) return false;

    const children = Array.from(col.children);
    const ref = children[position] || null;
    col.insertBefore(card, ref);
    return true;
  }

  window.Modal.moveCard = async function (payload) {
    if (!payload?.card_id) return;

    // bloqueia reabertura
    window.Modal.gate.block(4000, "move-card");

    let resp;
    try {
      resp = await fetch("/move-card/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrf(),
        },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
    } catch (_e) {
      window.Modal.close();
      return;
    }

    if (!resp.ok) {
      window.Modal.close();
      return;
    }

    const moved = moveCardDom(
      payload.card_id,
      payload.new_column_id,
      payload.new_position
    );

    window.Modal.url.clear({ replace: true });
    window.Modal.close();

    if (!moved) {
      window.location.reload();
    }
  };
})();
