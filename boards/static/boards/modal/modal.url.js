// modal.url.js — Estado da URL do Modal (?card=ID)
(() => {
  if (!window.Modal) {
    console.error("Modal.core.js precisa ser carregado antes do modal.url.js");
    return;
  }

  // evita redefinir em swaps/duplicidade
  if (window.Modal.url) return;

  function getCardIdFromUrl() {
    const u = new URL(window.location.href);
    const v = u.searchParams.get("card");
    const id = v ? parseInt(v, 10) : null;
    return Number.isFinite(id) ? id : null;
  }

  function setUrlCard(cardId, replace = false) {
    const u = new URL(window.location.href);
    u.searchParams.set("card", String(cardId));
    if (replace) history.replaceState({}, "", u);
    else history.pushState({}, "", u);
  }

  function clearUrlCard(replace = false) {
    const u = new URL(window.location.href);
    u.searchParams.delete("card");
    if (replace) history.replaceState({}, "", u);
    else history.pushState({}, "", u);
  }

  // ✅ helper: “voltar para o board limpo”
  // - remove ?card=... sem poluir histórico (replace)
  // - zera estado do modal
  // - navega para pathname (sem query) evitando reabrir ao reload
  function goToBoard(opts = {}) {
    const replace = ("replace" in opts) ? !!opts.replace : true;

    // 1) limpa a URL
    clearUrlCard(replace);

    // 2) zera estado do modal (hardening)
    try {
      if (window.Modal?.state) window.Modal.state.currentCardId = null;
    } catch (_e) {}

    // 3) navega para o board sem querystring
    // usa href para garantir request limpo (e evitar reabrir via boot)
    try {
      window.location.href = window.location.pathname;
    } catch (_e) {
      // fallback
      window.location.replace(window.location.pathname);
    }
  }

  window.Modal.url = {
    getCardIdFromUrl,
    set(cardId, opts = {}) {
      setUrlCard(cardId, !!opts.replace);
    },
    clear(opts = {}) {
      clearUrlCard(!!opts.replace);
    },

    // ✅ expõe para outros módulos (ex.: mover card, fechar modal, etc.)
    goToBoard,
  };

  // Boot por URL (refresh / deep link)
  document.addEventListener("DOMContentLoaded", () => {
    const cardId = getCardIdFromUrl();
    if (!cardId) return;

    if (!window.Modal.canOpen()) {
      clearUrlCard(true);
      return;
    }

    // NÃO abre aqui — apenas sinaliza
    window.Modal.state.currentCardId = cardId;
  });

  // Back / forward
  window.addEventListener("popstate", () => {
    const cardId = getCardIdFromUrl();

    if (cardId) {
      if (!window.Modal.canOpen()) {
        clearUrlCard(true);
        return;
      }
      window.Modal.state.currentCardId = cardId;
    } else {
      if (window.Modal.state.isOpen) {
        window.Modal.close();
      }
    }
  });
})();
