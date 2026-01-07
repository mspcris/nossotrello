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

  // NOVO: controle de foco + inert
  state.lastFocusedEl ??= null;

  function getModalEl() {
    return document.getElementById("modal");
  }

  function getRootEl() {
    return document.getElementById("card-modal-root");
  }

  function getBodyEl() {
    return document.getElementById("modal-body");
  }

  function getBoardRootEl() {
    // ajuste se seu board tiver um root específico
    // fallback: corpo todo, exceto modal
    return document.getElementById("board-root") || document.body;
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
    // 1) se o foco atual está dentro do modal, devolve para quem abriu
    const active = document.activeElement;

    if (isInsideModal(active)) {
      const last = state.lastFocusedEl;
      if (last && document.contains(last) && !isInsideModal(last)) {
        if (tryFocus(last)) return;
      }

      // fallback seguro: foca no body para não ficar dentro do modal
      try {
        document.body.tabIndex = document.body.tabIndex || -1;
        tryFocus(document.body);
      } catch {}
    }
  }

  function applyInert(isOpen) {
    // Aplica inert no "fundo" enquanto o modal está aberto
    // Isso evita foco e clique fora (e melhora A11y).
    const modal = getModalEl();
    const board = getBoardRootEl();
    if (!modal || !board) return;

    // se board == body, não aplique inert no body inteiro (senão mata o modal)
    if (board === document.body) {
      // aplica inert em todos os filhos do body exceto o modal
      const kids = Array.from(document.body.children || []);
      for (const k of kids) {
        if (k === modal) continue;
        if (isOpen) k.setAttribute("inert", "");
        else k.removeAttribute("inert");
      }
      return;
    }

    // caso exista um #board-root: inert nele
    if (isOpen) board.setAttribute("inert", "");
    else board.removeAttribute("inert");
  }

  function clearCardFromUrl() {
    try {
      const url = new URL(window.location.href);
      url.searchParams.delete("card");
      history.replaceState(history.state || {}, "", url.toString());
    } catch {}
  }



  // ============================================================
  // PATCH — GENIE EFFECT (SAFE)
  // ============================================================  
  // tira foco de dentro do modal IMEDIATAMENTE (antes do timeout)
  
try {
  const modalEl = getModalEl();
  const active = document.activeElement;
  if (modalEl && active && modalEl.contains(active)) {
    // 1) blur no elemento focado (garante que ele não “segure” foco)
    if (typeof active.blur === "function") active.blur();

    // 2) devolve foco para quem abriu (se existir)
    const last = state.lastFocusedEl;
    if (last && document.contains(last) && !modalEl.contains(last) && typeof last.focus === "function") {
      last.focus({ preventScroll: true });
    } else {
      // fallback seguro fora do modal
      document.body.tabIndex = document.body.tabIndex || -1;
      document.body.focus({ preventScroll: true });
    }
  }
} catch {}


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

    // NOVO: salva quem tinha foco antes de abrir
    state.lastFocusedEl = document.activeElement;

    // garante presença visual sem display:none
    modal.classList.add("modal-open");
    modal.setAttribute("aria-hidden", "false");

    // NOVO: bloqueia interação/foco no fundo
    applyInert(true);

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

    // NOVO: manda o foco para dentro do modal (depois do open)
    // (não depende do conteúdo já ter carregado)
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
  // CLOSE — GENIE EFFECT (SAFE)
  // ============================================================
  Modal.close = function ({ clearBody = true, clearUrl = true } = {}) {
    const modal = getModalEl();
    const root = getRootEl();
    const body = getBodyEl();

    const rect = state.lastCardRect;

    state.isOpen = false;
    state.currentCardId = null;

    // NOVO: antes de esconder, tira o foco de dentro do modal
    restoreFocusBeforeHide();

    const finalize = () => {
      modal?.classList.remove("modal-open");
      modal?.setAttribute("aria-hidden", "true");

      // NOVO: libera o fundo
      applyInert(false);

      // limpa resíduos para o próximo open
      if (root) {
        root.style.transition = "";
        root.style.transform = "";
        root.style.opacity = "";
      }

      if (clearBody && body) body.innerHTML = "";
      if (clearUrl) clearCardFromUrl();

      document.dispatchEvent(new Event("modal:closed"));
    };

    if (rect && root && modal) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      const scaleX = rect.width / root.offsetWidth;
      const scaleY = rect.height / root.offsetHeight;

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
