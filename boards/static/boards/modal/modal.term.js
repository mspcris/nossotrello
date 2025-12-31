// boards/static/boards/modal/modal.term.js
(() => {
  const Modal =
    (window.Modal && typeof window.Modal === "object") ? window.Modal : {};
  window.Modal = Modal;

  Modal.term = Modal.term || {};

  function qs(sel, root = document) { return root.querySelector(sel); }

  function parseYMD(s) {
    if (!s) return null;
    const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return null;
    const y = Number(m[1]), mo = Number(m[2]) - 1, d = Number(m[3]);
    const dt = new Date(Date.UTC(y, mo, d, 0, 0, 0));
    return isNaN(dt.getTime()) ? null : dt;
  }

  function fmtYMD(dt) {
    const y = dt.getUTCFullYear();
    const m = String(dt.getUTCMonth() + 1).padStart(2, "0");
    const d = String(dt.getUTCDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  function addDaysUTC(dt, days) {
    const x = new Date(dt.getTime());
    x.setUTCDate(x.getUTCDate() + days);
    return x;
  }

  function getCSRFToken() {
    return qs('input[name="csrfmiddlewaretoken"]')?.value || "";
  }

  function todayUTC() {
    const now = new Date();
    return new Date(Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate(),
      0, 0, 0
    ));
  }

  function hexToRgbStr(hex) {
    const h = String(hex || "").trim();
    const m = h.match(/^#?([0-9a-fA-F]{6})$/);
    if (!m) return "0,0,0";
    const n = parseInt(m[1], 16);
    const r = (n >> 16) & 255;
    const g = (n >> 8) & 255;
    const b = n & 255;
    return `${r},${g},${b}`;
  }

  Modal.term.init = function initTerm() {
    const root = qs("#cm-root");
    if (!root) return;

    const cardId = root.getAttribute("data-card-id");
    if (!cardId) return;

    const due = qs("#cm-term-due");
    const warn = qs("#cm-term-warn");
    const notify = qs("#cm-term-notify");
    const saveBtn = qs("#cm-term-save");

    // Se você removeu "Salvar term", este módulo pode continuar existindo sem quebrar.
    // Ele só atua quando os elementos existem.
    if (!due || !warn || !notify || !saveBtn) return;

    // Cores do board (de preferência injetadas em window.BOARD_TERM_COLORS pelo template)
    const colors = (window.BOARD_TERM_COLORS && typeof window.BOARD_TERM_COLORS === "object")
      ? window.BOARD_TERM_COLORS
      : {};

    const cOk = colors.ok || "#16a34a";
    const cWarn = colors.warn || "#f59e0b";
    const cOver = colors.overdue || "#dc2626";

    function clearModalTint() {
      root.style.setProperty("--cm-term-opacity", "0");
      root.style.removeProperty("--cm-term-rgb");
    }

    function setModalTint(hexColor) {
      root.style.setProperty("--cm-term-rgb", hexToRgbStr(hexColor));
      root.style.setProperty("--cm-term-opacity", "0.12"); // mesmo "peso" do glass do modal
    }

    function updateModalTint() {
      const dueDt = parseYMD(due.value);

      // sem vencimento ou notify off => sem tint
      if (!dueDt || !notify.checked) {
        clearModalTint();
        return;
      }

      const warnDt = parseYMD(warn.value);
      const t = todayUTC();

      // vencido
      if (dueDt.getTime() < t.getTime()) {
        setModalTint(cOver);
        return;
      }

      // alerta (já entrou no range de aviso)
      if (warnDt && t.getTime() >= warnDt.getTime()) {
        setModalTint(cWarn);
        return;
      }

      // ok
      setModalTint(cOk);
    }

    // default UX:
    // - sem due => warn disabled e vazio
    // - com due e warn vazio => default due-5
    function syncWarnState() {
      const dueDt = parseYMD(due.value);

      if (!dueDt) {
        warn.value = "";
        warn.disabled = true;
        warn.required = false;

        // ✅ garante consistência visual
        updateModalTint();
        return;
      }

      warn.disabled = false;
      warn.required = true;

      if (!warn.value) {
        const def = addDaysUTC(dueDt, -5);
        warn.value = fmtYMD(def);
      }

      // ✅ garante consistência visual
      updateModalTint();
    }

    // autosync
    due.addEventListener("change", syncWarnState);
    due.addEventListener("input", syncWarnState);

    // atualiza tint quando usuário mexe diretamente
    warn.addEventListener("change", updateModalTint);
    warn.addEventListener("input", updateModalTint);
    notify.addEventListener("change", updateModalTint);

    // first sync
    syncWarnState();

    // salvar (HTMX-less, evita mexer no cm-main-form)
    saveBtn.addEventListener("click", async (e) => {
      e.preventDefault();

      const endpoint = `/card/${cardId}/term-due/`;

      const fd = new FormData();
      fd.append("term_due_date", due.value || "");
      fd.append("term_warn_date", warn.value || "");
      fd.append("term_notify", notify.checked ? "1" : "0");
      fd.append("csrfmiddlewaretoken", getCSRFToken());

      const res = await fetch(endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        body: fd,
      });

      if (!res.ok) return;

      // swap modal body (mesma estratégia do resto do projeto)
      const html = await res.text();
      const modalBody = qs("#modal-body");
      if (modalBody) modalBody.innerHTML = html;

      // reinit padrão
      window.Modal?.init?.();
    });
  };
})();
