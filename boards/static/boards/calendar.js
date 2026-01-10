/* ======================================================================
   boards/static/boards/calendar.js

   Calendar UI (Mês / Semana) para Board Detail
   - Renderiza calendário via endpoint /calendar/cards/
   - Controla navegação (prev/next), modo (mês/semana) e campo (due/start/warn)
   - Alterna visibilidade entre colunas e calendário via menu (drawer)

   Contrato do backend (JSON):
     {
       mode: "month"|"week",
       field: "due"|"start"|"warn",
       days: { "YYYY-MM-DD": [{id,title,...}] },
       grid_start: "YYYY-MM-DD",
       grid_end: "YYYY-MM-DD",
       focus_year: 2026,
       focus_month: 1,
       label: "janeiro 2026" | "Semana de 10/01/2026",
       ...
     }

   Contrato do DOM:
     - #calendar-root
     - #columns-wrapper
     - botão com [data-action="toggle-calendar"]
     - window.BOARD_ID setado no template
====================================================================== */

(function () {
  "use strict";

  /* =======================
     1) STATE (Single Source of Truth)
  ======================= */
  window.CalendarState = window.CalendarState || {
    active: false,
    mode: "month",  // "month" | "week"
    field: "due",   // "due" | "start" | "warn"
    focus: null     // "YYYY-MM-DD" (data foco)
  };

  /* =======================
     2) HELPERS
  ======================= */
  function isoToday() {
    return new Date().toISOString().slice(0, 10);
  }

  function toDateUTC(isoDateStr) {
    // Evita variação por timezone ao criar Date a partir de "YYYY-MM-DD"
    return new Date(isoDateStr + "T00:00:00");
  }

  function fmtISO(d) {
    return d.toISOString().slice(0, 10);
  }

  function getEl(id) {
    return document.getElementById(id);
  }

  function assertBoardId() {
    const id = Number(window.BOARD_ID || 0);
    if (!id) {
      console.error("[calendar] window.BOARD_ID não definido. Verifique o BOOT GLOBAL no template.");
      return 0;
    }
    return id;
  }

  /* =======================
     3) PUBLIC API (opcional)
     - Se no futuro quiser chamar calendar via console/integrações
  ======================= */
  window.CalendarUI = window.CalendarUI || {};
  window.CalendarUI.render = renderCalendar;
  window.CalendarUI.toggle = toggleCalendar;
  window.CalendarUI.setMode = function (mode) {
    window.CalendarState.mode = (mode === "week") ? "week" : "month";
    renderCalendar();
  };
  window.CalendarUI.setField = function (field) {
    window.CalendarState.field = field;
    renderCalendar();
  };

  /* =======================
     4) TOGGLE (Menu Drawer)
     - Delegação global: funciona mesmo se o drawer for re-renderizado
  ======================= */
  document.addEventListener("click", function (e) {
    const btn = e.target.closest('[data-action="toggle-calendar"]');
    if (!btn) return;
    toggleCalendar();
  });

  function toggleCalendar() {
    const columns = getEl("columns-wrapper");
    const calendarRoot = getEl("calendar-root");
    if (!columns || !calendarRoot) {
      console.error("[calendar] #columns-wrapper ou #calendar-root não encontrado no DOM.");
      return;
    }

    window.CalendarState.active = !window.CalendarState.active;

    if (window.CalendarState.active) {
      columns.classList.add("hidden");
      calendarRoot.classList.remove("hidden");
      renderCalendar();
    } else {
      calendarRoot.classList.add("hidden");
      columns.classList.remove("hidden");
    }
  }

  /* =======================
     5) FETCH + RENDER (core)
  ======================= */
  async function renderCalendar() {
    const boardId = assertBoardId();
    if (!boardId) return;

    const focus = window.CalendarState.focus || isoToday();

    const url =
      `/calendar/cards/?board=${boardId}` +
      `&mode=${encodeURIComponent(window.CalendarState.mode)}` +
      `&field=${encodeURIComponent(window.CalendarState.field)}` +
      `&start=${encodeURIComponent(focus)}`;

    try {
      const res = await fetch(url, {
        method: "GET",
        credentials: "same-origin",
        headers: { "Accept": "application/json" }
      });

      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        console.error("[calendar] Erro HTTP:", res.status, txt);
        return;
      }

      const data = await res.json();

      const root = getEl("calendar-root");
      if (!root) {
        console.error("[calendar] #calendar-root não encontrado no DOM.");
        return;
      }

      root.innerHTML = renderCalendarView(data);

      // Wiring precisa ocorrer após inserir HTML
      wireCalendarControls(root);

    } catch (err) {
      console.error("[calendar] Falha ao buscar calendário:", err);
    }
  }

  /* =======================
     6) VIEW (HTML render)
  ======================= */
  function renderCalendarView(data) {
    return `
      <div class="cm-calendar-shell">
        ${renderCalendarHeader(data)}
        ${renderCalendarGrid(data)}
      </div>
    `;
  }

  function renderCalendarHeader(data) {
    const isMonth = data.mode === "month";
    const field = data.field || window.CalendarState.field;

    return `
      <div class="cm-calendar-header">
        <div class="cm-cal-left">
          <button class="cm-cal-nav" data-cal-nav="prev" type="button" aria-label="Anterior">‹</button>
          <div class="cm-cal-title">${escapeHtml(data.label || "")}</div>
          <button class="cm-cal-nav" data-cal-nav="next" type="button" aria-label="Próximo">›</button>
        </div>

        <div class="cm-cal-right">
          <div class="cm-cal-modes" role="group" aria-label="Modo do calendário">
            <button type="button"
                    class="cm-cal-mode ${isMonth ? "is-active" : ""}"
                    data-cal-mode="month">Mês</button>
            <button type="button"
                    class="cm-cal-mode ${!isMonth ? "is-active" : ""}"
                    data-cal-mode="week">Semana</button>
          </div>

          <select class="cm-cal-field" data-cal-field aria-label="Campo de data">
            <option value="due" ${field === "due" ? "selected" : ""}>Vencimento</option>
            <option value="start" ${field === "start" ? "selected" : ""}>Data de Início</option>
            <option value="warn" ${field === "warn" ? "selected" : ""}>Avisar em</option>
          </select>
        </div>
      </div>
    `;
  }

  function renderCalendarGrid(data) {
    const days = data.days || {};
    const total = (data.mode === "week") ? 7 : 42;

    // backend agora manda grid_start (ISO)
    const gridStartIso = data.grid_start;
    if (!gridStartIso) {
      console.error("[calendar] Backend não retornou grid_start. Verifique views/calendar.py.");
      return `<div class="cm-calendar ${data.mode}"></div>`;
    }

    const gridStart = toDateUTC(gridStartIso);

    // Para style "fora do mês" no modo mês
    const focusYear = Number(data.focus_year || 0);
    const focusMonth = Number(data.focus_month || 0); // 1..12

    let html = `<div class="cm-calendar ${data.mode}">`;

    for (let i = 0; i < total; i++) {
      const d = new Date(gridStart);
      d.setDate(d.getDate() + i);

      const key = fmtISO(d);

      const inFocusMonth =
        (data.mode === "week") ? true :
        (d.getFullYear() === focusYear) && ((d.getMonth() + 1) === focusMonth);

      html += `
        <div class="cm-calendar-day ${inFocusMonth ? "" : "is-outside"}" data-day="${key}">
          <div class="cm-calendar-date">${d.getDate()}</div>
          ${(days[key] || []).map(renderCalendarCard).join("")}
        </div>
      `;
    }

    html += `</div>`;
    return html;
  }

  function renderCalendarCard(card) {
    // Card mínimo por enquanto. Depois dá para enriquecer (status de prazo, cor, tags, clique abre modal etc.)
    return `
      <div class="cm-calendar-card" data-card-id="${Number(card.id || 0)}">
        ${escapeHtml(card.title || "")}
      </div>
    `;
  }

  /* =======================
     7) CONTROLS (navegação, modo, field)
     - Usa delegação por container do calendário para não duplicar handlers
  ======================= */
  function wireCalendarControls(root) {
    // Evita duplicar listeners a cada render
    if (root.dataset.cmCalendarWired === "1") return;
    root.dataset.cmCalendarWired = "1";

    root.addEventListener("click", function (e) {
      const navBtn = e.target.closest("[data-cal-nav]");
      if (navBtn) {
        const dir = navBtn.getAttribute("data-cal-nav"); // prev|next
        shiftCalendarFocus(dir);
        return;
      }

      const modeBtn = e.target.closest("[data-cal-mode]");
      if (modeBtn) {
        window.CalendarState.mode = modeBtn.getAttribute("data-cal-mode");
        renderCalendar();
        return;
      }
    });

    root.addEventListener("change", function (e) {
      const fieldSelect = e.target.closest("[data-cal-field]");
      if (!fieldSelect) return;
      window.CalendarState.field = fieldSelect.value;
      renderCalendar();
    });
  }

  function shiftCalendarFocus(dir) {
    const current = window.CalendarState.focus || isoToday();
    const focus = toDateUTC(current);

    if (window.CalendarState.mode === "week") {
      focus.setDate(focus.getDate() + (dir === "next" ? 7 : -7));
    } else {
      // month: mover mês e ancorar no dia 1 para não "pular"
      focus.setDate(1);
      focus.setMonth(focus.getMonth() + (dir === "next" ? 1 : -1));
    }

    window.CalendarState.focus = fmtISO(focus);
    renderCalendar();
  }

  /* =======================
     8) SAFE HTML
  ======================= */
  function escapeHtml(str) {
    return String(str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
})();