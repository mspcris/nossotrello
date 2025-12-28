// boards/static/boards/modal/modal.core.js
(() => {
  const Modal =
    (window.Modal && typeof window.Modal === "object") ? window.Modal : {};
  window.Modal = Modal;

  const DEBUG = (() => {
    try {
      if (typeof window.DEBUG !== "undefined") return !!window.DEBUG;
      if (location.hostname === "localhost" || location.hostname === "127.0.0.1") return true;
      return localStorage.getItem("DEBUG") === "1";
    } catch {
      return false;
    }
  })();

  const log = (...args) => { if (DEBUG) console.log("[modal.core]", ...args); };
  const warn = (...args) => { if (DEBUG) console.warn("[modal.core]", ...args); };

  const state =
    (Modal.state && typeof Modal.state === "object") ? Modal.state : {};
  Modal.state = state;

  if (!("isOpen" in state)) state.isOpen = false;
  if (!("currentCardId" in state)) state.currentCardId = null;
  if (!("lastOpenedAt" in state)) state.lastOpenedAt = 0;

  function getModalEl() {
    return document.getElementById("modal");
  }

  function getBodyEl() {
    return document.getElementById("modal-body");
  }

  function clearCardFromUrl() {
    try {
      const url = new URL(window.location.href);

      // remove ?card=...
      url.searchParams.delete("card");

      // mantém o hash se existir
      // não dá reload: apenas “normaliza” a barra
      window.history.replaceState(window.history.state || {}, "", url.toString());
    } catch (e) {
      // silencioso
    }
  }

  Modal.open = function open() {
    const modal = getModalEl();
    if (!modal) {
      warn("open(): #modal não encontrado no DOM");
      return false;
    }

    modal.classList.remove("hidden");
    modal.classList.add("modal-open");
    modal.setAttribute("aria-hidden", "false");

    state.isOpen = true;
    state.lastOpenedAt = Date.now();

    log("open()", { isOpen: state.isOpen, currentCardId: state.currentCardId });
    return true;
  };

  Modal.close = function close(opts = {}) {
    const { clearBody = true, clearUrl = true } = opts;

    // 1) Estado primeiro (para destravar polling imediatamente)
    state.isOpen = false;
    state.currentCardId = null;

    const modal = getModalEl();
    const body = getBodyEl();

    if (modal) {
      modal.classList.remove("modal-open");
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
    } else {
      warn("close(): #modal não encontrado no DOM");
    }

    if (clearBody && body) {
      body.innerHTML = "";
    }

    // 2) URL por último (sem reload)
    if (clearUrl) clearCardFromUrl();
    
    try {
      document.dispatchEvent(new CustomEvent("modal:closed"));
    } catch (_) {}

    log("close()", { isOpen: state.isOpen });
    return true;
  };

  if (!Modal.__coreLoaded) {
    Modal.__coreLoaded = true;

    Modal.getElements = Modal.getElements || function () {
      return { modal: getModalEl(), body: getBodyEl() };
    };

    log("core loaded");
  } else {
    log("core already loaded (methods/state ensured)");
  }
})();
