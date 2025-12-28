// boards/static/boards/modal/modal.core.js
(() => {
  const Modal =
    (window.Modal && typeof window.Modal === "object") ? window.Modal : {};
  window.Modal = Modal;

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

  function getModalEl() {
    return document.getElementById("modal");
  }

  function getRootEl() {
    return document.getElementById("card-modal-root");
  }

  function getBodyEl() {
    return document.getElementById("modal-body");
  }

  function clearCardFromUrl() {
    try {
      const url = new URL(window.location.href);
      url.searchParams.delete("card");
      history.replaceState(history.state || {}, "", url.toString());
    } catch {}
  }

  // ============================================================
  // OPEN — GENIE EFFECT (SAFE)
  // ============================================================
  Modal.open = function () {
    const modal = getModalEl();
    const root = getRootEl();
    if (!modal || !root) {
      warn("open(): modal/root não encontrado");
      return false;
    }

    // garante presença visual sem display:none
    modal.classList.add("modal-open");
    modal.setAttribute("aria-hidden", "false");

    const rect = state.lastCardRect;

    if (rect) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      const scaleX = rect.width / root.offsetWidth;
      const scaleY = rect.height / root.offsetHeight;

      const translateX = rect.left + rect.width / 2 - vw / 2;
      const translateY = rect.top + rect.height / 2 - vh / 2;

      // 1️⃣ estado inicial (sem transição)
      root.style.transition = "none";
      root.style.transformOrigin = "center center";
      root.style.transform =
        `translate(${translateX}px, ${translateY}px) scale(${scaleX}, ${scaleY})`;
      root.style.opacity = "0";

      // 🔑 força layout (IMPRESCINDÍVEL)
      root.getBoundingClientRect();

      // 2️⃣ estado final (com transição)
      requestAnimationFrame(() => {
        root.style.transition =
          "transform 420ms cubic-bezier(0.22, 1, 0.36, 1), opacity 200ms ease";
        root.style.transform = "translate(0,0) scale(1)";
        root.style.opacity = "1";
      });
    }

    state.isOpen = true;
    state.lastOpenedAt = Date.now();
    log("open()");
    return true;
  };

  // ============================================================
  // CLOSE — GENIE EFFECT (SAFE)
  // ============================================================
  Modal.close = function ({ clearBody = true, clearUrl = true } = {}) {
    const modal = getModalEl();
    const root = getRootEl();
    const body = getBodyEl();

    const rect = state.lastCardRect;

    state.isOpen = false;
    state.currentCardId = null;

    if (rect && root) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      const scaleX = rect.width / root.offsetWidth;
      const scaleY = rect.height / root.offsetHeight;

      const translateX = rect.left + rect.width / 2 - vw / 2;
      const translateY = rect.top + rect.height / 2 - vh / 2;

      root.style.transition =
        "transform 220ms ease, opacity 180ms ease";
      root.style.transform =
        `translate(${translateX}px, ${translateY}px) scale(${scaleX}, ${scaleY})`;
      root.style.opacity = "0";

      setTimeout(() => {
        modal.classList.remove("modal-open");
        modal.setAttribute("aria-hidden", "true");

        // limpa resíduos para o próximo open
        root.style.transition = "";
        root.style.transform = "";
        root.style.opacity = "";

        if (clearBody && body) body.innerHTML = "";
        if (clearUrl) clearCardFromUrl();

        document.dispatchEvent(new Event("modal:closed"));
      }, 240);
    } else {
      modal?.classList.remove("modal-open");
      modal?.setAttribute("aria-hidden", "true");

      if (clearBody && body) body.innerHTML = "";
      if (clearUrl) clearCardFromUrl();

      document.dispatchEvent(new Event("modal:closed"));
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
