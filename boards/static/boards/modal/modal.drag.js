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

      /* Aqui existia uma SEGUNDA sincronização de mover card, que contrariava o
         "NUNCA interferir no SortableJS" do topo deste arquivo. Ela postava em
         "/move_card/" — underscore — mas a rota é "/move-card/" com hífen, então
         sempre deu 404 desde que foi escrita. O 404 devolve HTML, o r.json()
         estourava e o .catch caía num location.reload().

         No mouse isso nunca aparecia: clicar no ⋮ não move o ponteiro, moved
         ficava false e o bloco nem rodava. No dedo o ⋮ é pequeno, o toque
         costuma cair no card em vez do botão, e qualquer tremida acima de 6px
         marcava moved=true — daí tocar nos três pontinhos recarregava a página
         no celular (chamado PPY-EJ6-BRTZ).

         Quem move card de verdade é o Sortable, via postMove() em
         board_detail.html, que usa a URL certa. Este arquivo volta a fazer só o
         que o cabeçalho promete: separar clique de arrasto. */

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

  /* Rede de segurança pro __isDraggingCard. O bloco removido acima tinha
     early-returns que puravam antes da limpeza e deixavam o flag preso em true
     — e com ele preso, o pan do quadro e o puxar-pra-atualizar ficam bloqueados
     pra sempre, sem jeito a não ser sair e voltar. O flag descreve um arrasto em
     curso: acabou o ponteiro, acabou o arrasto. O Sortable já zera no onEnd; o
     setTimeout deixa esse caminho normal acontecer primeiro. */
  ["pointerup", "pointercancel"].forEach(function (evt) {
    document.addEventListener(
      evt,
      function () { setTimeout(function () { window.__isDraggingCard = false; }, 0); },
      true
    );
  });
})();
