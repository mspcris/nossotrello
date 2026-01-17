// boards/static/boards/modal/modal.core.js
(() => {
  const Modal =
    (window.Modal && typeof window.Modal === "object") ? window.Modal : {};
  window.Modal = Modal;

  if (Modal.__coreLoaded) return;
  Modal.__coreLoaded = true;

  const DEBUG =
    location.hostname === "localhost" ||
    localStorage.getItem("DEBUG") === "1";

  const log = (...a) => DEBUG && console.log("[modal.core]", ...a);
  const warn = (...a) => DEBUG && console.warn("[modal.core]", ...a);

  const state = Modal.state ||= {};
  state.isOpen ??= false;
  state.lastFocusedEl ??= null;

  /* ============================================================
   * Helpers DOM
   * ============================================================ */
  const getModalEl = () => document.getElementById("modal");
  const getRootEl  = () => document.getElementById("card-modal-root");
  const getBodyEl  = () => document.getElementById("modal-body");

  const isInsideModal = (el) => {
    const modal = getModalEl();
    return !!(modal && el && modal.contains(el));
  };

  const tryFocus = (el) => {
    try {
      el?.focus?.({ preventScroll: true });
      return true;
    } catch {
      return false;
    }
  };

  /* ============================================================
   * Nova Atividade — TOGGLE (FONTE ÚNICA DE VERDADE)
   * ============================================================ */
  function initActivityToggle() {
    const root = document.getElementById("cm-root");
    if (!root) return;

    const btn = root.querySelector("#cm-activity-toggle");
    const composer = root.querySelector("#cm-activity-composer");
    const gap = root.querySelector("#cm-activity-gap");

    if (!btn || !composer) return;

    // evita múltiplos binds
    if (btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";

    // estado inicial: FECHADO
    composer.classList.add("is-hidden");
    gap?.classList.add("is-hidden");
    btn.setAttribute("aria-expanded", "false");

    btn.addEventListener("click", () => {
      const closed = composer.classList.toggle("is-hidden");
      gap?.classList.toggle("is-hidden", closed);
      btn.setAttribute("aria-expanded", closed ? "false" : "true");
    });
  }

  /* ============================================================
   * OPEN
   * ============================================================ */
  Modal.open = function () {
    const modal = getModalEl();
    const root = getRootEl();

    if (!modal || !root) {
      warn("open(): modal/root não encontrado");
      return false;
    }

    state.lastFocusedEl = document.activeElement;

    modal.classList.add("modal-open");
    modal.setAttribute("aria-hidden", "false");

    requestAnimationFrame(() => {
      tryFocus(
        modal.querySelector(
          "button.modal-top-x, [data-modal-close], button"
        )
      );
    });

    state.isOpen = true;

    // AA
    try { Modal.fontSize?.init?.(); } catch {}

    // NOVA ATIVIDADE (AQUI É O LUGAR CERTO)
    initActivityToggle();

    log("open()");
    return true;
  };

  /* ============================================================
   * CLOSE
   * ============================================================ */
  Modal.close = function () {
    const modal = getModalEl();
    const body = getBodyEl();

    modal?.classList.remove("modal-open");
    modal?.setAttribute("aria-hidden", "true");

    body && (body.innerHTML = "");

    try { Modal.fontSize?.destroy?.(); } catch {}

    state.isOpen = false;
    log("close()");
  };

  /* ============================================================
   * Font size (AA)
   * ============================================================ */
  (() => {
    const KEY = "cm_modal_font_size";
    const DEFAULT = "sm";

    const applyFont = (size) => {
      getRootEl()?.setAttribute("data-font", size);
      getModalEl()?.setAttribute("data-font", size);
      document.getElementById("cm-root")?.setAttribute("data-font", size);
      localStorage.setItem(KEY, size);
    };

    const current = () => localStorage.getItem(KEY) || DEFAULT;

    Modal.fontSize = {
      init() {
        applyFont(current());
      },
      destroy() {},
    };

    // HTMX — reaplica AA + toggle
    if (!window.__cmAfterSwapBound) {
      window.__cmAfterSwapBound = true;

      document.body.addEventListener("htmx:afterSwap", (e) => {
        if (e.target?.id === "modal-body") {
          Modal.fontSize.init();
          initActivityToggle();
        }
      });
    }
  })();

})();
