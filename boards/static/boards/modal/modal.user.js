// boards/static/boards/modal/modal.user.js
(() => {
  if (!window.Modal || window.Modal.user) return;

  function umOpenTab(tab) {
    const panels = {
      profile: document.getElementById("um-panel-profile"),
      password: document.getElementById("um-panel-password"),
      avatar: document.getElementById("um-panel-avatar"),
    };

    Object.keys(panels).forEach((k) => {
      if (panels[k]) panels[k].style.display = (k === tab) ? "block" : "none";
    });

    // marca botão ativo (opcional, mas ajuda a não confundir)
    document.querySelectorAll("[data-um-tab]").forEach((btn) => {
      const isActive = btn.getAttribute("data-um-tab") === tab;
      btn.classList.toggle("font-semibold", isActive);
    });
  }

  function umInitFromDom() {
    const root = document.getElementById("um-root");
    if (!root) return;

    const tab = root.getAttribute("data-active-tab") || "profile";
    umOpenTab(tab);
  }

  function wireTabClicks() {
    // Delegação: funciona mesmo com conteúdo trocado
    document.getElementById("modal-body")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-um-tab]");
      if (!btn) return;

      e.preventDefault();
      const tab = btn.getAttribute("data-um-tab");
      if (tab) umOpenTab(tab);
    });
  }

  window.Modal.user = {
    _wired: false,

    open() {
      fetch("/account/modal/")
        .then((r) => r.text())
        .then((html) => {
          const body = document.getElementById("modal-body");
          if (!body) return;

          body.innerHTML = html;
          window.Modal.open();

          // garante que a aba certa aparece ao abrir
          umInitFromDom();

          // garante que clique nas tabs sempre funcione
          if (!window.Modal.user._wired) {
            wireTabClicks();
            window.Modal.user._wired = true;
          }
        });
    },
  };

  // API global caso você ainda tenha onclick="window.umOpenTab('...')" no template
  window.umOpenTab = umOpenTab;

  document.body.addEventListener("click", (e) => {
    if (e.target.closest("#open-user-settings")) {
      e.preventDefault();
      window.Modal.user.open();
    }
  });

  // Se o seu modal do usuário usa HTMX dentro (hx-post nos forms),
  // o swap do #modal-body acontece e precisamos re-inicializar a aba ativa.
  document.body.addEventListener("htmx:afterSwap", (evt) => {
    const target = evt.detail && evt.detail.target;
    if (!target || target.id !== "modal-body") return;

    // só reinicializa se o conteúdo do user modal estiver presente
    if (document.getElementById("um-root")) {
      umInitFromDom();
    }
  });
})();
