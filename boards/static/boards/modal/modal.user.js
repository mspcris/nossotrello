// boards/static/boards/modal/modal.user.js
(() => {
  if (!window.Modal || window.Modal.user) return;

  function processHtmx(el) {
    try {
      if (window.htmx && typeof window.htmx.process === "function") {
        window.htmx.process(el);
      }
    } catch (_e) {}
  }

  function refreshAvatarSelection(modalBody) {
    if (!modalBody) return;

    const checked = modalBody.querySelector(
      "#um-avatar-grid input[name='avatar_choice']:checked"
    );
    const chosen = checked ? checked.value : null;

    modalBody.querySelectorAll("#um-avatar-grid .um-avatar-item").forEach((img) => {
      const isOn = !!(chosen && img.getAttribute("data-avatar") === chosen);

      // Não depende de Tailwind (garante feedback visual mesmo sem utilitários)
      if (isOn) {
        img.style.outline = "3px solid #2563eb";
        img.style.outlineOffset = "2px";
        img.style.borderColor = "#2563eb";
      } else {
        img.style.outline = "";
        img.style.outlineOffset = "";
        img.style.borderColor = "";
      }
    });
  }

  function wireAvatarPresetClicks() {
    const modalBody = document.getElementById("modal-body");
    if (!modalBody) return;

    // Delegação: funciona mesmo após HTMX swap do modal
    modalBody.addEventListener("click", (e) => {
      const img = e.target.closest("#um-avatar-grid .um-avatar-item");
      if (!img) return;

      const label = img.closest("label");
      const inputId = label ? label.getAttribute("for") : null;
      const radio = inputId ? document.getElementById(inputId) : null;

      if (radio && radio.type === "radio") {
        radio.checked = true;
        refreshAvatarSelection(modalBody);
      }
    });
  }

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
    _wiredAvatar: false,

    open() {
      fetch("/account/modal/")
        .then((r) => r.text())
        .then((html) => {
          const body = document.getElementById("modal-body");
          if (!body) return;

          body.innerHTML = html;

          // IMPORTANTe: como carregamos via fetch + innerHTML, precisamos reprocessar HTMX
          // para ativar hx-post/hx-target/hx-swap dentro do modal.
          processHtmx(body);

          window.Modal.open();

          // garante que a aba certa aparece ao abrir
          umInitFromDom();

          // garante que clique nas tabs sempre funcione
          if (!window.Modal.user._wired) {
            wireTabClicks();
            window.Modal.user._wired = true;
          }

          // habilita seleção visual dos avatares (preset)
          if (!window.Modal.user._wiredAvatar) {
            wireAvatarPresetClicks();
            window.Modal.user._wiredAvatar = true;
          }

          refreshAvatarSelection(body);
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
      refreshAvatarSelection(target);
    }
  });
})();
