// modal.nav.js — pós-ação: voltar para o board sem ?card=
(() => {
  if (!window.Modal) return;

  window.Modal.nav = window.Modal.nav || {};

  window.Modal.nav.goToBoard = function () {
    if (window.Modal?.url?.clear) window.Modal.url.clear({ replace: true });
    else history.replaceState({}, "", window.location.pathname);

    if (window.Modal?.state) window.Modal.state.currentCardId = null;

    window.location.href = window.location.pathname;
  };
})();
