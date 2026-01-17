// ============================================================
// CM — Calendar Drag & Drop (update date by active field)
// ============================================================
(function () {
  let draggingCard = null;
  let originCell = null;

  function getActiveField() {
    const sel = document.querySelector('.cm-cal-field');
    return sel ? sel.value : 'due'; // fallback seguro
  }

  function getCSRF() {
    return document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || '';
  }

  function enableCardDrag(card) {
    card.setAttribute('draggable', 'true');

    card.addEventListener('dragstart', (e) => {
      draggingCard = card;
      originCell = card.closest('.cm-cal-day');
      card.classList.add('is-dragging');
      e.dataTransfer.effectAllowed = 'move';
    });

    card.addEventListener('dragend', () => {
      card.classList.remove('is-dragging');
      draggingCard = null;
      originCell = null;
    });
  }

  function enableDayDrop(day) {
    day.addEventListener('dragover', (e) => {
      e.preventDefault();
      day.classList.add('is-drop-target');
    });

    day.addEventListener('dragleave', () => {
      day.classList.remove('is-drop-target');
    });

    day.addEventListener('drop', async (e) => {
      e.preventDefault();
      day.classList.remove('is-drop-target');

      if (!draggingCard || !originCell) return;

      const newDate = day.dataset.date;
      const cardId = draggingCard.dataset.cardId;
      const field = getActiveField();

      if (!newDate || !cardId) return;

      // move visual imediato (optimistic UI)
      day.querySelector('.cm-cal-cards')?.appendChild(draggingCard);

      try {
        const res = await fetch(`/card/${cardId}/calendar/update/`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRF(),
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify({
            field: field,
            date: newDate,
          }),
          credentials: 'same-origin',
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json();
        if (!data || data.ok !== true) throw new Error('Resposta inválida');

      } catch (err) {
        // rollback visual
        originCell.querySelector('.cm-cal-cards')?.appendChild(draggingCard);
        alert('Erro ao alterar data do card.');
      }
    });
  }

  function initCalendarDrag() {
    document.querySelectorAll('.cm-cal-card[data-card-id]').forEach(enableCardDrag);
    document.querySelectorAll('.cm-cal-day[data-date]').forEach(enableDayDrop);
  }

  document.addEventListener('DOMContentLoaded', initCalendarDrag);
  document.body.addEventListener('htmx:afterSwap', initCalendarDrag);
})();
