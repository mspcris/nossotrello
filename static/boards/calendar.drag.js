//boards/static/boards/calendar.drag.js
// ============================================================
// CM — Calendar Drag & Drop (HTML5 DnD)
// Backend: POST /card/<id>/calendar-date/ (field=due|start|warn, date=YYYY-MM-DD)
// ============================================================
(function () {
  let draggingCard = null;
  let originDay = null;

  function getActiveField() {
    const sel = document.querySelector(".cm-cal-field");
    if (sel && sel.value) return sel.value;
    const el = document.querySelector("[data-cal-field]");
    return (el && el.dataset && el.dataset.calField) ? el.dataset.calField : "due";
  }

  function getCSRF() {
    return (
      document.querySelector("input[name=csrfmiddlewaretoken]")?.value ||
      document.querySelector("meta[name='csrf-token']")?.content ||
      ""
    );
  }

  // IMPORTANTE: seu markup real é .cm-cal-card (não .cm-cal-card)
  function cardSelector() {
    return ".cm-cal-card[data-card-id]";
  }

  function daySelector() {
    return ".cm-cal-day[data-date]";
  }

  function cardsBox(dayEl) {
    return dayEl.querySelector(".cm-cal-cards") || dayEl;
  }

  function enableCardDrag(card) {
    if (card.dataset.cmDrag === "1") return;
    card.dataset.cmDrag = "1";

    card.setAttribute("draggable", "true");
    card.style.cursor = "grab";

    card.addEventListener("dragstart", (e) => {
      draggingCard = card;
      originDay = card.closest(daySelector());
      card.classList.add("is-dragging");

      // Firefox: precisa setData
      try { e.dataTransfer.setData("text/plain", card.dataset.cardId || ""); } catch (_) {}
      e.dataTransfer.effectAllowed = "move";
    });

    card.addEventListener("dragend", () => {
      card.classList.remove("is-dragging");
      draggingCard = null;
      originDay = null;
    });
  }

  function enableDayDrop(day) {
    if (day.dataset.cmDrop === "1") return;
    day.dataset.cmDrop = "1";

    day.addEventListener("dragover", (e) => {
      e.preventDefault();
      day.classList.add("is-drop-target");
    });

    day.addEventListener("dragleave", () => {
      day.classList.remove("is-drop-target");
    });

    day.addEventListener("drop", async (e) => {
      e.preventDefault();
      day.classList.remove("is-drop-target");

      if (!draggingCard || !originDay) return;

      const newDate = day.dataset.date;
      const cardId = draggingCard.dataset.cardId;
      const field = getActiveField();
      if (!newDate || !cardId) return;

      // UI otimista
      cardsBox(day).appendChild(draggingCard);

      try {
        const body = new URLSearchParams({ field, date: newDate });

        const res = await fetch(`/card/${cardId}/calendar-date/`, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-CSRFToken": getCSRF(),
            "X-Requested-With": "XMLHttpRequest",
          },
          body,
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const data = await res.json().catch(() => null);
        if (!data || data.ok !== true) throw new Error("Resposta inválida");
      } catch (_err) {
        // rollback
        cardsBox(originDay).appendChild(draggingCard);
        alert("Erro ao alterar data do card.");
      }
    });
  }

  function initCalendarDrag(scope) {
    const root = scope || document;
    root.querySelectorAll(cardSelector()).forEach(enableCardDrag);
    root.querySelectorAll(daySelector()).forEach(enableDayDrop);
  }

  // ✅ expõe para o calendar.js poder chamar
  window.initCalendarDrag = initCalendarDrag;

  document.addEventListener("DOMContentLoaded", () => initCalendarDrag(document));

  document.body.addEventListener("htmx:afterSwap", (e) => {
    const target = e.detail?.target || e.target || document;
    initCalendarDrag(target);
  });

  // ✅ NOVO
  document.addEventListener("cm:calendarRendered", (e) => {
    const scope = e.detail?.scope || document;
    initCalendarDrag(scope);
  });

})();


//END boards/static/boards/calendar.drag.js