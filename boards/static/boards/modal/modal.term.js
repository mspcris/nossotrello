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

    function pickInput(root, name) {
    return qs(`input[name="${name}"]`, root);
  }

  function pickCheckbox(root, name) {
    return qs(`input[name="${name}"][type="checkbox"]`, root);
  }


  Modal.term.init = function initTerm() {
    const root = qs("#cm-root");
    if (!root) return;

    // HTML novo (sem IDs antigos)
    const due = pickInput(root, "due_date");
    const warn = pickInput(root, "due_warn_date");
    const notify = pickCheckbox(root, "due_notify"); // checkbox
    const cOk = pickInput(root, "due_color_ok");
    const cWarn = pickInput(root, "due_color_warn");
    const cOver = pickInput(root, "due_color_overdue");

    if (!due || !warn || !notify) return;

    function clearModalTint() {
      root.style.setProperty("--cm-term-opacity", "0");
      root.style.removeProperty("--cm-term-rgb");
    }

    function setModalTint(hexColor) {
      root.style.setProperty("--cm-term-rgb", hexToRgbStr(hexColor));
      root.style.setProperty("--cm-term-opacity", "0.12"); // mesmo tom “glass”
    }

    function getColors() {
      return {
        ok: (cOk && cOk.value) ? cOk.value : "#16a34a",
        warn: (cWarn && cWarn.value) ? cWarn.value : "#f59e0b",
        overdue: (cOver && cOver.value) ? cOver.value : "#dc2626",
      };
    }

    // UX:
    // - sem due => warn disabled e vazio
    // - com due e warn vazio => default due-5
    function syncWarnState() {
      const dueDt = parseYMD(due.value);
      if (!dueDt) {
        warn.value = "";
        warn.disabled = true;
        warn.required = false;
        return;
      }

      warn.disabled = false;
      warn.required = true;

      if (!warn.value) {
        const def = addDaysUTC(dueDt, -5);
        warn.value = fmtYMD(def);
      }
    }

    function updateModalTint() {
      const dueDt = parseYMD(due.value);

      // regra: sem vencimento ou notify off => sem tint
      if (!dueDt || !notify.checked) {
        clearModalTint();
        return;
      }

      const warnDt = parseYMD(warn.value);
      const t = todayUTC();
      const colors = getColors();

      if (dueDt.getTime() < t.getTime()) {
        setModalTint(colors.overdue);
        return;
      }

      if (warnDt && t.getTime() >= warnDt.getTime()) {
        setModalTint(colors.warn);
        return;
      }

      setModalTint(colors.ok);
    }

    function refreshAll() {
      syncWarnState();
      updateModalTint();
    }

    // listeners
    due.addEventListener("change", refreshAll);
    due.addEventListener("input", refreshAll);

    warn.addEventListener("change", updateModalTint);
    warn.addEventListener("input", updateModalTint);

    notify.addEventListener("change", updateModalTint);

    // preview ao trocar cores (sem precisar salvar)
    if (cOk) cOk.addEventListener("input", updateModalTint);
    if (cWarn) cWarn.addEventListener("input", updateModalTint);
    if (cOver) cOver.addEventListener("input", updateModalTint);

    // init
    refreshAll();
  };
})();
