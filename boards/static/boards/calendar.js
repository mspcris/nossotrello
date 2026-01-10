/* boards/static/boards/calendar.js */

/**
 * Calendar (Board)
 * - Alterna entre Board (colunas) e Calendário
 * - Carrega dados via /calendar/cards/
 * - Renderiza Mês (grid) e Semana (7 colunas full-height)
 * - Mês: card como “pílula” com stripe de cor (sem imagem)
 * - Semana: card como “barra” com cor + thumbnail (quando tiver)
 *
 * Contrato:
 * - window.BOARD_ID deve existir
 * - Deve existir #calendar-root e #columns-wrapper no DOM
 * - Backend deve retornar:
 *   {
 *     mode: "month"|"week",
 *     field: "due"|"start"|"warn",
 *     label: "Janeiro 2026",
 *     grid_start: "YYYY-MM-DD",
 *     focus_year: 2026,
 *     focus_month: 1,
 *     week_start: "YYYY-MM-DD",   // recomendado no modo week (se tiver)
 *     days: { "YYYY-MM-DD": [ {id,title,color,cover_url}, ... ] }
 *   }
 */

(function () {
  /* ============================================================
   * STATE
   * ============================================================ */
  window.CalendarState = window.CalendarState || {
    active: false,
    mode: "month", // month | week
    field: "due",  // due | start | warn
    focus: null    // YYYY-MM-DD
  };

  function ymd(d) {
    return d.toISOString().slice(0, 10);
  }

  function parseYmd(s) {
    // força meia-noite local sem “pulo” de timezone
    return new Date(s + "T00:00:00");
  }

  function safe(fn) {
    try { return fn(); } catch (_e) { return null; }
  }

  /* ============================================================
   * TOGGLE (Board <-> Calendar)
   * ============================================================ */
  if (!window.__cmCalendarToggleInstalled) {
    window.__cmCalendarToggleInstalled = true;

    document.addEventListener("click", (e) => {
      const btn = e.target.closest('[data-action="toggle-calendar"]');
      if (!btn) return;

      const columns = document.getElementById("columns-wrapper");
      const calendarRoot = document.getElementById("calendar-root");
      if (!columns || !calendarRoot) return;

      CalendarState.active = !CalendarState.active;

      if (CalendarState.active) {
        columns.classList.add("hidden");
        calendarRoot.classList.remove("hidden");
        renderCalendar();
      } else {
        calendarRoot.classList.add("hidden");
        columns.classList.remove("hidden");
      }
    });
  }

  /* ============================================================
   * FETCH + RENDER
   * ============================================================ */
  async function renderCalendar() {
    const root = document.getElementById("calendar-root");
    if (!root) return;

    root.classList.add("cm-cal-loading");

    try {
      const focus = CalendarState.focus || ymd(new Date());
      const url =
        `/calendar/cards/?board=${window.BOARD_ID}` +
        `&mode=${CalendarState.mode}` +
        `&field=${CalendarState.field}` +
        `&start=${focus}`;

      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const data = await res.json();

      root.innerHTML = renderCalendarView(data);
      wireCalendarControls(root, data);

      // Rehidrata cores de prazo no HTML recém-injetado
      safe(() => window.applySavedTermColorsToBoard && window.applySavedTermColorsToBoard(root));


    } catch (e) {
      console.error("Erro ao carregar calendário:", e);
      root.innerHTML = `
        <div class="cm-calendar-shell">
          <div class="cm-cal-error">
            Erro ao carregar calendário. Veja o console.
          </div>
        </div>
      `;
    } finally {
      root.classList.remove("cm-cal-loading");
    }
  }

  window.renderCalendar = renderCalendar;

  /* ============================================================
   * VIEW
   * ============================================================ */
  function renderCalendarView(data) {
    return `
      <div class="cm-calendar-shell ${data.mode}">
        ${renderCalendarHeader(data)}
        ${data.mode === "week" ? renderWeekView(data) : renderMonthView(data)}
      </div>
    `;
  }

  function renderCalendarHeader(data) {
    const isMonth = data.mode === "month";
    const field = data.field;

    return `
      <div class="cm-calendar-header">
        <div class="cm-cal-left">
          <button class="cm-cal-nav" data-cal-nav="prev" type="button" aria-label="Anterior">‹</button>
          <div class="cm-cal-title">${data.label || ""}</div>
          <button class="cm-cal-nav" data-cal-nav="next" type="button" aria-label="Próximo">›</button>
        </div>

        <div class="cm-cal-right">
          <div class="cm-cal-modes">
            <button type="button" class="cm-cal-mode ${isMonth ? "is-active" : ""}" data-cal-mode="month">Mês</button>
            <button type="button" class="cm-cal-mode ${!isMonth ? "is-active" : ""}" data-cal-mode="week">Semana</button>
          </div>

          <select class="cm-cal-field" data-cal-field>
            <option value="due" ${field === "due" ? "selected" : ""}>Vencimento</option>
            <option value="start" ${field === "start" ? "selected" : ""}>Data de Início</option>
            <option value="warn" ${field === "warn" ? "selected" : ""}>Avisar em</option>
          </select>
        </div>
      </div>
    `;
  }

  /* ============================================================
   * MONTH (grid 6x7)
   * - Card: “pílula” com stripe colorido (sem imagem)
   * ============================================================ */
  function renderMonthView(data) {
    const days = data.days || {};
    const total = 42;

    const gridStart = parseYmd(data.grid_start);
    const focusYear = data.focus_year;
    const focusMonth = data.focus_month; // 1..12

    let html = `<div class="cm-cal-month">`;

    for (let i = 0; i < total; i++) {
      const d = new Date(gridStart);
      d.setDate(d.getDate() + i);

      const key = ymd(d);

      const inFocusMonth =
        (d.getFullYear() === focusYear) &&
        ((d.getMonth() + 1) === focusMonth);

      html += `
        <div class="cm-cal-day ${inFocusMonth ? "" : "is-outside"}" data-day="${key}">
          <div class="cm-cal-date">${d.getDate()}</div>
          <div class="cm-cal-cards">
            ${(days[key] || []).map((card) => renderCalendarCard(card, "month")).join("")}
          </div>
        </div>
      `;
    }

    html += `</div>`;
    return html;
  }

  /* ============================================================
   * WEEK (7 columns full-height)
   * - Top row: Domingo, Segunda...
   * - Columns: barras estilo board
   * ============================================================ */
  function renderWeekView(data) {
    const days = data.days || {};

    // Preferir week_start se backend mandar; senão usa grid_start
    const startStr = data.week_start || data.grid_start || CalendarState.focus || ymd(new Date());
    const start = parseYmd(startStr);

    const dowNames = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"];

    // header + columns
    let html = `<div class="cm-cal-week">`;

    // Cabeçalho fixo da semana
    html += `<div class="cm-week-head">`;
    for (let i = 0; i < 7; i++) {
      const d = new Date(start);
      d.setDate(d.getDate() + i);
      html += `
        <div class="cm-week-headcell">
          <div class="cm-week-dow">${dowNames[d.getDay()]}</div>
          <div class="cm-week-date">${d.getDate()}/${String(d.getMonth() + 1).padStart(2, "0")}</div>
        </div>
      `;
    }
    html += `</div>`;

    // Colunas (até o fim da página; scroll interno via CSS)
    html += `<div class="cm-week-cols">`;
    for (let i = 0; i < 7; i++) {
      const d = new Date(start);
      d.setDate(d.getDate() + i);
      const key = ymd(d);

      html += `
        <div class="cm-week-col" data-day="${key}">
          <div class="cm-week-cards">
            ${(days[key] || []).map((card) => renderCalendarCard(card, "week")).join("")}
          </div>
        </div>
      `;
    }
    html += `</div>`;

    html += `</div>`;
    return html;
  }

  /* ============================================================
   * TERM STATUS resolver (ok|warn|overdue)
   * ============================================================ */
  function resolveTermStatus(card) {
    const raw =
      card?.term_status ??
      card?.termStatus ??
      card?.term?.status ??
      card?.due_status ??
      card?.dueStatus ??
      card?.term ??
      "";

    const s = String(raw || "").trim().toLowerCase();

    if (["ok", "emdia", "em_dia", "em dia", "green"].includes(s)) return "ok";
    if (["warn", "avencer", "a_vencer", "a vencer", "yellow"].includes(s)) return "warn";
    if (["overdue", "vencido", "red"].includes(s)) return "overdue";

    return "";
  }

  /* ============================================================
   * CARD RENDER
   * - month: pílula (sem imagem) + bolinha com data-term-status
   * - week: barra (com thumb quando tiver) + data-term-status
   * ============================================================ */
  function renderCalendarCard(card, viewMode) {
    const id = card?.id ?? "";
    const title = (card && card.title) ? String(card.title) : "";
    const cover = (card && card.cover_url) ? String(card.cover_url) : "";

    const termStatus = resolveTermStatus(card); // ok|warn|overdue|""

    if (viewMode === "week") {
      return `
        <button
          type="button"
          class="cm-cal-card cm-cal-card-week"
          data-card-id="${escapeAttr(String(id))}"
          title="${escapeHtml(title)}"
        >
          <span class="cm-cal-bar" ${termStatus ? `data-term-status="${escapeAttr(termStatus)}"` : ""}></span>

          ${cover
            ? `<span class="cm-cal-thumb" style="background-image:url('${escapeAttr(cover)}')"></span>`
            : `<span class="cm-cal-thumb is-empty"></span>`
          }

          <span class="cm-cal-card-title">${escapeHtml(title)}</span>
        </button>
      `;
    }

    // month
    return `
      <button
        type="button"
        class="cm-cal-card cm-cal-card-month"
        data-card-id="${escapeAttr(String(id))}"
        title="${escapeHtml(title)}"
      >
        <span class="cm-cal-dot" ${termStatus ? `data-term-status="${escapeAttr(termStatus)}"` : ""}></span>
        <span class="cm-cal-card-title">${escapeHtml(title)}</span>
      </button>
    `;
  }








  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function escapeAttr(s) {
    // suficiente pra url dentro de aspas simples
    return String(s).replaceAll("'", "%27");
  }

  /* ============================================================
   * WIRING
   * ============================================================ */
  function wireCalendarControls(root, data) {
    // navegação prev/next
    root.querySelectorAll("[data-cal-nav]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const dir = btn.getAttribute("data-cal-nav"); // prev|next
        shiftCalendarFocus(dir);
      });
    });

    // modo mês/semana
    root.querySelectorAll("[data-cal-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        CalendarState.mode = btn.getAttribute("data-cal-mode");
        renderCalendar();
      });
    });

    // campo due/start/warn
    const fieldSelect = root.querySelector("[data-cal-field]");
    if (fieldSelect) {
      fieldSelect.addEventListener("change", () => {
        CalendarState.field = fieldSelect.value;
        renderCalendar();
      });
    }

    // abrir card ao clicar
    root.querySelectorAll(".cm-cal-card[data-card-id]").forEach((el) => {
      el.addEventListener("click", () => {
        const cardId = Number(el.getAttribute("data-card-id") || 0);
        if (!cardId) return;

        // Integra com seu modal, se existir
        const opened = safe(() => window.Modal && typeof window.Modal.openCard === "function" && window.Modal.openCard(cardId, true, null));
        if (!opened) {
          // fallback: navega para board com ?card=
          safe(() => { window.location.search = `?card=${cardId}`; });
        }
      });
    });
  }

  function shiftCalendarFocus(dir) {
    const focusStr = CalendarState.focus || ymd(new Date());
    const focus = parseYmd(focusStr);

    if (CalendarState.mode === "week") {
      focus.setDate(focus.getDate() + (dir === "next" ? 7 : -7));
    } else {
      // month: trava dia 1 para não “pular mês”
      const m = focus.getMonth();
      focus.setDate(1);
      focus.setMonth(dir === "next" ? m + 1 : m - 1);
    }

    CalendarState.focus = ymd(focus);
    renderCalendar();
  }
})();



