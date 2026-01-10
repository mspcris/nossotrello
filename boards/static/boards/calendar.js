/* boards/static/boards/calendar.js */

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

  function escapeHtml(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function escapeAttr(s) {
    // robusto pra atributos HTML entre aspas
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll('"', "&quot;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll("'", "&#039;");
  }

  /* ============================================================
   * URL SYNC (view=calendar)
   * ============================================================ */
  function syncCalendarUrl() {
    const url = new URL(window.location.href);

    if (window.CalendarState && window.CalendarState.active) {
      url.searchParams.set("view", "calendar");
      url.searchParams.set("mode", CalendarState.mode || "month");
      url.searchParams.set("field", CalendarState.field || "due");
      url.searchParams.set("start", CalendarState.focus || ymd(new Date()));
    } else {
      url.searchParams.delete("view");
      url.searchParams.delete("mode");
      url.searchParams.delete("field");
      url.searchParams.delete("start");
    }

    history.replaceState({}, "", url.toString());
  }

  function hydrateCalendarStateFromUrl() {
    const url = new URL(window.location.href);
    const view = url.searchParams.get("view");

    if (view !== "calendar") return false;

    CalendarState.active = true;

    const mode = url.searchParams.get("mode");
    const field = url.searchParams.get("field");
    const start = url.searchParams.get("start");

    CalendarState.mode = (mode === "week" || mode === "month") ? mode : "month";
    CalendarState.field = (field === "due" || field === "start" || field === "warn") ? field : "due";
    CalendarState.focus = start || ymd(new Date());

    return true;
  }

  function showCalendarUI() {
    const columns = document.getElementById("columns-wrapper");
    const calendarRoot = document.getElementById("calendar-root");
    if (!columns || !calendarRoot) return;

    columns.classList.add("hidden");
    calendarRoot.classList.remove("hidden");
  }

  function showBoardUI() {
    const columns = document.getElementById("columns-wrapper");
    const calendarRoot = document.getElementById("calendar-root");
    if (!columns || !calendarRoot) return;

    calendarRoot.classList.add("hidden");
    columns.classList.remove("hidden");
  }

  /* ============================================================
   * TOGGLE (Board <-> Calendar)
   * ============================================================ */
  if (!window.__cmCalendarToggleInstalled) {
    window.__cmCalendarToggleInstalled = true;

    document.addEventListener("click", (e) => {
      const btn = e.target.closest('[data-action="toggle-calendar"]');
      if (!btn) return;

      CalendarState.active = !CalendarState.active;

      if (CalendarState.active) {
        showCalendarUI();
        syncCalendarUrl();
        renderCalendar();
      } else {
        showBoardUI();
        syncCalendarUrl();
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
   * WEEK (7 columns)
   * ============================================================ */
  function renderWeekView(data) {
    const days = data.days || {};

    // preferir week_start vindo do backend
    const startStr = data.week_start || data.grid_start || CalendarState.focus || ymd(new Date());
    const start = parseYmd(startStr);

    const dowNames = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"];

    let html = `<div class="cm-cal-week">`;

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
   * CARD RENDER
   * ============================================================ */
  function renderCalendarCard(card, viewMode) {
    const id = card?.id ?? "";
    const title = (card && card.title) ? String(card.title) : "";
    const cover = (card && card.cover_url) ? String(card.cover_url) : "";

    // estes 3 precisam ir pro DOM (pra pintar prazo no client)
    const due = card?.due_date || "";
    const warn = card?.warn_date || "";
    const notify = (card?.due_notify === false || card?.due_notify === 0) ? "0" : "1";

    if (viewMode === "week") {
      return `
        <button
          type="button"
          class="cm-cal-card cm-cal-card-week"
          data-card-id="${escapeAttr(String(id))}"
          data-term-due="${escapeAttr(due)}"
          data-term-warn="${escapeAttr(warn)}"
          data-term-notify="${escapeAttr(notify)}"
          title="${escapeHtml(title)}"
        >
          <span class="cm-cal-bar"></span>

          ${
            cover
              ? `<span class="cm-cal-thumb">
                   <img src="${escapeAttr(cover)}" alt="" loading="lazy" />
                 </span>`
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
        data-term-due="${escapeAttr(due)}"
        data-term-warn="${escapeAttr(warn)}"
        data-term-notify="${escapeAttr(notify)}"
        title="${escapeHtml(title)}"
      >
        <span class="cm-cal-dot"></span>
        <span class="cm-cal-card-title">${escapeHtml(title)}</span>
      </button>
    `;
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
        syncCalendarUrl();
        renderCalendar();
      });
    });

    // campo due/start/warn
    const fieldSelect = root.querySelector("[data-cal-field]");
    if (fieldSelect) {
      fieldSelect.addEventListener("change", () => {
        CalendarState.field = fieldSelect.value;
        syncCalendarUrl();
        renderCalendar();
      });
    }

    // abrir card ao clicar
    root.querySelectorAll(".cm-cal-card[data-card-id]").forEach((el) => {
      el.addEventListener("click", () => {
        const cardId = Number(el.getAttribute("data-card-id") || 0);
        if (!cardId) return;

        // Integra com seu modal, se existir
let opened = false;

try {
  if (window.Modal && typeof window.Modal.openCard === "function") {
    window.Modal.openCard(cardId, true, null);
    opened = true; // ✅ considera sucesso mesmo se openCard retornar undefined
  }
} catch (e) {
  opened = false;
}

if (!opened) {
  // fallback: navega para board com ?card=
  try { window.location.search = `?card=${cardId}`; } catch (e) {}
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
      const m = focus.getMonth();
      focus.setDate(1);
      focus.setMonth(dir === "next" ? m + 1 : m - 1);
    }

    CalendarState.focus = ymd(focus);
    syncCalendarUrl();
    renderCalendar();
  }

  /* ============================================================
   * BOOT: abre calendário via URL
   * ============================================================ */
  document.addEventListener("DOMContentLoaded", () => {
    const shouldOpen = hydrateCalendarStateFromUrl();
    if (!shouldOpen) return;

    showCalendarUI();
    syncCalendarUrl();
    renderCalendar();
  });

  // Back/forward do browser (opcional, mas dá previsibilidade)
  window.addEventListener("popstate", () => {
    const opened = hydrateCalendarStateFromUrl();
    if (opened) {
      showCalendarUI();
      renderCalendar();
    } else {
      CalendarState.active = false;
      showBoardUI();
    }
  });

})();
