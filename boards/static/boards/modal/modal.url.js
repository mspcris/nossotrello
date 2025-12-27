// modal.url.js — Estado da URL do Modal (?card=ID)
(() => {
  if (!window.Modal) {
    console.error("Modal.core.js precisa ser carregado antes do modal.url.js");
    return;
  }

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

  window.Modal.url = {
    getCardIdFromUrl,
    set(cardId, opts = {}) {
      setUrlCard(cardId, !!opts.replace);
    },
    clear(opts = {}) {
      clearUrlCard(!!opts.replace);
    },
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
