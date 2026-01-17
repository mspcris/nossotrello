// boards/static/boards/modal/modal.core.js
(() => {
  const Modal =
    (window.Modal && typeof window.Modal === "object") ? window.Modal : {};
  window.Modal = Modal;

  // evita duplicidade
  if (Modal.__coreLoaded) return;
  Modal.__coreLoaded = true;

  const DEBUG =
    location.hostname === "localhost" ||
    localStorage.getItem("DEBUG") === "1";

  const log = (...a) => DEBUG && console.log("[modal.core]", ...a);
  const warn = (...a) => DEBUG && console.warn("[modal.core]", ...a);

  const state =
    (Modal.state && typeof Modal.state === "object") ? Modal.state : {};
  Modal.state = state;

  state.isOpen ??= false;
  state.currentCardId ??= null;
  state.lastOpenedAt ??= 0;
  state.lastCardRect ??= null;

  // foco
  state.lastFocusedEl ??= null;

  // ============================================================
  // Helpers DOM
  // ============================================================
  function getModalEl() {
    return document.getElementById("modal");
  }

  function getRootEl() {
    return document.getElementById("card-modal-root");
  }

  function getBodyEl() {
    return document.getElementById("modal-body");
  }

  function isInsideModal(el) {
    const modal = getModalEl();
    return !!(modal && el && modal.contains(el));
  }

  function tryFocus(el) {
    try {
      if (el && typeof el.focus === "function") {
        el.focus({ preventScroll: true });
        return true;
      }
    } catch {}
    return false;
  }

  function restoreFocusBeforeHide() {
    const active = document.activeElement;
    if (!isInsideModal(active)) return;

    const last = state.lastFocusedEl;
    if (last && document.contains(last) && !isInsideModal(last)) {
      if (tryFocus(last)) return;
    }

    // fallback seguro
    try {
      document.body.tabIndex = document.body.tabIndex || -1;
      tryFocus(document.body);
    } catch {}
  }

  // ============================================================
  // Inert (trava fundo sem travar modal)
  // Regra: nunca aplicar inert em um ancestral do modal.
  // ============================================================
  function getModalTopContainer() {
    const modal = getModalEl();
    if (!modal) return null;

    // sobe até o filho direto do <body> que contém o modal
    let node = modal;
    while (node && node.parentElement && node.parentElement !== document.body) {
      node = node.parentElement;
    }

    return node && node.parentElement === document.body ? node : null;
  }

  function applyInert(isOpen) {
    const modal = getModalEl();
    if (!modal) return;

    // 1) se existir #board-root E ele não contém o modal, aplique inert nele
    const boardRoot = document.getElementById("board-root");
    if (boardRoot && !boardRoot.contains(modal)) {
      if (isOpen) boardRoot.setAttribute("inert", "");
      else boardRoot.removeAttribute("inert");
      return;
    }

    // 2) fallback: aplica inert nos irmãos do "top container" do modal
    const top = getModalTopContainer();
    if (!top) return;

    const kids = Array.from(document.body.children || []);
    for (const k of kids) {
      if (k === top) continue; // poupa o container que contém o modal
      if (isOpen) k.setAttribute("inert", "");
      else k.removeAttribute("inert");
    }
  }

  // ============================================================
  // URL (?card=)
  // ============================================================
  function clearCardFromUrl() {
    try {
      const url = new URL(window.location.href);
      url.searchParams.delete("card");
      history.replaceState(history.state || {}, "", url.toString());
    } catch {}
  }

  // ============================================================
  // OPEN
  // ============================================================
  Modal.open = function () {
    const modal = getModalEl();
    const root = getRootEl();

    if (!modal || !root) {
      warn("open(): modal/root não encontrado");
      return false;
    }

    // salva foco anterior
    state.lastFocusedEl = document.activeElement;

    modal.classList.add("modal-open");
    modal.setAttribute("aria-hidden", "false");

    // trava o fundo (sem travar o modal)
    applyInert(true);

    const rect = state.lastCardRect;

    // Genie (se tiver geometria do card)
    if (rect) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      const rw = root.offsetWidth || 1;
      const rh = root.offsetHeight || 1;

      const scaleX = rect.width / rw;
      const scaleY = rect.height / rh;

      const translateX = rect.left + rect.width / 2 - vw / 2;
      const translateY = rect.top + rect.height / 2 - vh / 2;

      root.style.transition = "none";
      root.style.transformOrigin = "center center";
      root.style.transform =
        `translate(${translateX}px, ${translateY}px) scale(${scaleX}, ${scaleY})`;
      root.style.opacity = "0";

      // força layout
      root.getBoundingClientRect();

      requestAnimationFrame(() => {
        root.style.transition =
          "transform 420ms cubic-bezier(0.22, 1, 0.36, 1), opacity 200ms ease";
        root.style.transform = "translate(0,0) scale(1)";
        root.style.opacity = "1";
      });
    }

    // foco dentro do modal
    requestAnimationFrame(() => {
      const closeBtn =
        modal.querySelector("button.modal-top-x, [data-modal-close], #modal-top-x") ||
        modal.querySelector("button, [tabindex]:not([tabindex='-1'])");
      if (closeBtn) tryFocus(closeBtn);
    });

    state.isOpen = true;
    state.lastOpenedAt = Date.now();
    log("open()");
    return true;
  };

  // ============================================================
  // CLOSE
  // ============================================================
  Modal.close = function ({ clearBody = true, clearUrl = true } = {}) {
    const modal = getModalEl();
    const root = getRootEl();
    const body = getBodyEl();

    const rect = state.lastCardRect;

    state.isOpen = false;
    state.currentCardId = null;

    // devolve foco antes de esconder
    restoreFocusBeforeHide();

    const finalize = () => {
      modal?.classList.remove("modal-open");
      modal?.setAttribute("aria-hidden", "true");

      // libera o fundo
      applyInert(false);

      // limpa resíduos
      if (root) {
        root.style.transition = "";
        root.style.transform = "";
        root.style.opacity = "";
      }

      if (clearBody && body) body.innerHTML = "";
      if (clearUrl) clearCardFromUrl();

      document.dispatchEvent(new Event("modal:closed"));
    };

    // Genie close (se tiver geometria)
    if (rect && root && modal) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      const rw = root.offsetWidth || 1;
      const rh = root.offsetHeight || 1;

      const scaleX = rect.width / rw;
      const scaleY = rect.height / rh;

      const translateX = rect.left + rect.width / 2 - vw / 2;
      const translateY = rect.top + rect.height / 2 - vh / 2;

      root.style.transition = "transform 220ms ease, opacity 180ms ease";
      root.style.transform =
        `translate(${translateX}px, ${translateY}px) scale(${scaleX}, ${scaleY})`;
      root.style.opacity = "0";

      setTimeout(finalize, 240);
    } else {
      finalize();
    }

    log("close()");
    return true;
  };

  Modal.getElements = () => ({
    modal: getModalEl(),
    body: getBodyEl(),
    root: getRootEl(),
  });
})();
// end boards/static/boards/modal/modal.core.js