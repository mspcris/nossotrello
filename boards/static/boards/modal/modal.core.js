// boards/static/boards/modal/modal.core.js
(() => {
  // ============================================================
  // Modal Core — estado + open/close + foco + inert
  // - Corrige "modal abre mas não clica" (pointer-events/invisible)
  // - Mantém Genie effect quando existir lastCardRect
  // - Hardening: não duplica init em HTMX swaps
  // ============================================================

  const Modal =
    (window.Modal && typeof window.Modal === "object") ? window.Modal : {};
  window.Modal = Modal;

  // evita redefinir se esse arquivo for carregado duas vezes
  if (Modal.__core_inited) return;
  Modal.__core_inited = true;

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

  // foco / a11y
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
    // se tiver um root específico no board, use. senão, fallback para body.
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
    const active = document.activeElement;

    if (isInsideModal(active)) {
      const last = state.lastFocusedEl;
      if (last && document.contains(last) && !isInsideModal(last)) {
        if (tryFocus(last)) return;
      }

      // fallback seguro fora do modal
      try {
        document.body.tabIndex = document.body.tabIndex || -1;
        tryFocus(document.body);
      } catch {}
    }
  }

  function applyInert(isOpen) {
    // bloqueia o "fundo" enquanto o modal está aberto
    const modal = getModalEl();
    const board = getBoardRootEl();
    if (!modal || !board) return;

    // se board == body, não aplique inert no body inteiro (mata o modal)
    if (board === document.body) {
      const kids = Array.from(document.body.children || []);
      for (const k of kids) {
        if (k === modal) continue;
        if (isOpen) k.setAttribute("inert", "");
        else k.removeAttribute("inert");
      }
      return;
    }

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
  // VISIBILITY HELPERS (CRÍTICO)
  // - Seu #modal nasce com: opacity-0 pointer-events-none invisible
  // - Se open() não remover isso => modal abre mas não clica
  // ============================================================
  function makeModalInteractive(modal) {
    if (!modal) return;

    // remove travas
    modal.classList.remove("opacity-0", "pointer-events-none", "invisible");
    // reforça visível
    modal.classList.add("opacity-100");
    // garante que não tem hidden (caso alguém use)
    modal.classList.remove("hidden");

    // hardening inline (caso CSS esteja ganhando)
    modal.style.pointerEvents = "auto";
  }

  function makeModalNonInteractive(modal) {
    if (!modal) return;

    modal.classList.remove("opacity-100");
    modal.classList.add("opacity-0", "pointer-events-none", "invisible");

    // limpa inline
    try {
      modal.style.pointerEvents = "";
    } catch {}
  }

  // ============================================================
  // HARDENING — se algo deixar foco preso dentro do modal
  // (não execute fora de close/open; fica aqui como util)
  // ============================================================
  function forceBlurIfFocusedInsideModal() {
    try {
      const modalEl = getModalEl();
      const active = document.activeElement;
      if (modalEl && active && modalEl.contains(active)) {
        if (typeof active.blur === "function") active.blur();

        const last = state.lastFocusedEl;
        if (last && document.contains(last) && !modalEl.contains(last) && typeof last.focus === "function") {
          last.focus({ preventScroll: true });
        } else {
          document.body.tabIndex = document.body.tabIndex || -1;
          document.body.focus({ preventScroll: true });
        }
      }
    } catch {}
  }

  // ============================================================
  // OPEN — GENIE EFFECT (SAFE) + FIX INTERAÇÃO
  // ============================================================
  Modal.open = function () {
    const modal = getModalEl();
    const root = getRootEl();
    if (!modal || !root) {
      warn("open(): modal/root não encontrado");
      return false;
    }

    // anti double-open spam
    const now = Date.now();
    if (state.lastOpenedAt && now - state.lastOpenedAt < 150) {
      return true;
    }

    // salva quem tinha foco antes de abrir
    state.lastFocusedEl = document.activeElement;

    // liga estado + acessibilidade
    state.isOpen = true;
    state.lastOpenedAt = now;
    modal.setAttribute("aria-hidden", "false");

    // ✅ torna clicável/visível (CRÍTICO)
    makeModalInteractive(modal);

    // marca open (se você usa isso em CSS)
    modal.classList.add("modal-open");

    // bloqueia fundo
    applyInert(true);

    const rect = state.lastCardRect;

    // Genie (se tiver geometria)
    if (rect) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      const scaleX = rect.width / Math.max(root.offsetWidth, 1);
      const scaleY = rect.height / Math.max(root.offsetHeight, 1);

      const translateX = rect.left + rect.width / 2 - vw / 2;
      const translateY = rect.top + rect.height / 2 - vh / 2;

      // estado inicial
      root.style.transition = "none";
      root.style.transformOrigin = "center center";
      root.style.transform =
        `translate(${translateX}px, ${translateY}px) scale(${scaleX}, ${scaleY})`;
      root.style.opacity = "0";

      // força layout
      root.getBoundingClientRect();

      // estado final
      requestAnimationFrame(() => {
        root.style.transition =
          "transform 420ms cubic-bezier(0.22, 1, 0.36, 1), opacity 200ms ease";
        root.style.transform = "translate(0,0) scale(1)";
        root.style.opacity = "1";
      });
    } else {
      // sem genie: garante root visível
      root.style.opacity = "1";
    }

    // foco dentro do modal (não depende do conteúdo ter carregado)
    requestAnimationFrame(() => {
      const closeBtn =
        modal.querySelector("button.modal-top-x, [data-modal-close], #modal-close, #modal-top-x") ||
        modal.querySelector("button, [tabindex]:not([tabindex='-1'])");
      if (closeBtn) tryFocus(closeBtn);
    });

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

    // estado
    state.isOpen = false;
    state.currentCardId = null;

    // antes de esconder, tira foco de dentro do modal
    restoreFocusBeforeHide();
    forceBlurIfFocusedInsideModal();

    const rect = state.lastCardRect;

    const finalize = () => {
      // remove marca open
      modal?.classList.remove("modal-open");
      modal?.setAttribute("aria-hidden", "true");

      // ✅ desliga interação
      makeModalNonInteractive(modal);

      // libera fundo
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

    if (rect && root && modal) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      const scaleX = rect.width / Math.max(root.offsetWidth, 1);
      const scaleY = rect.height / Math.max(root.offsetHeight, 1);

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

  // hardening: se recarregar e estiver "aberto" no state, garante coerência visual
  document.addEventListener("DOMContentLoaded", () => {
    const modal = getModalEl();
    if (!modal) return;

    if (state.isOpen) {
      modal.setAttribute("aria-hidden", "false");
      makeModalInteractive(modal);
      modal.classList.add("modal-open");
      applyInert(true);
    } else {
      modal.setAttribute("aria-hidden", "true");
      // não força nada aqui, só deixa como veio do HTML
    }
  });
})();
