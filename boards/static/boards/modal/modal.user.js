// boards/static/boards/modal/modal.user.js
(() => {
  if (!window.Modal || window.Modal.user) return;

  function htmxProcess(scopeEl) {
    try {
      if (window.htmx && typeof window.htmx.process === "function" && scopeEl) {
        window.htmx.process(scopeEl);
      }
    } catch (_e) {}
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

    document.querySelectorAll("[data-um-tab]").forEach((btn) => {
      const isActive = btn.getAttribute("data-um-tab") === tab;
      btn.classList.toggle("font-semibold", isActive);
    });

    // mantém o estado (pra quando der swap)
    const root = document.getElementById("um-root");
    if (root) root.setAttribute("data-active-tab", tab);
  }

  function umInitFromDom() {
    const root = document.getElementById("um-root");
    if (!root) return;

    const tab = root.getAttribute("data-active-tab") || "profile";
    umOpenTab(tab);
  }

  // ============================================================
  // Avatar presets (seleção visual)
  // ============================================================
  function umRefreshAvatarSelection(scope) {
    const root = scope || document;
    const grid = root.querySelector?.("#um-avatar-grid");
    if (!grid) return;

    const checked = grid.querySelector("input[name='avatar_choice']:checked");
    const chosen = checked ? checked.value : "";

    grid.querySelectorAll(".um-avatar-item").forEach((img) => {
      const isOn = chosen && img.getAttribute("data-avatar") === chosen;
      img.classList.toggle("ring-2", !!isOn);
      img.classList.toggle("ring-blue-600", !!isOn);
      img.classList.toggle("border-blue-600", !!isOn);
    });
  }

  function wireAvatarPresetClicks() {
    const modalBody = document.getElementById("modal-body");
    if (!modalBody) return;

    modalBody.addEventListener("click", (e) => {
      const img = e.target.closest(".um-avatar-item");
      if (!img) return;

      const label = img.closest("label");
      const radio = label ? label.querySelector("input[name='avatar_choice']") : null;
      if (radio) {
        radio.checked = true;
        umRefreshAvatarSelection(document);
      }
    });
  }

  function wireTabClicks() {
    const modalBody = document.getElementById("modal-body");
    if (!modalBody) return;

    modalBody.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-um-tab]");
      if (!btn) return;

      e.preventDefault();
      const tab = btn.getAttribute("data-um-tab");
      if (tab) umOpenTab(tab);
    });
  }

  function afterModalHtmlInjected() {
    const body = document.getElementById("modal-body");
    if (!body) return;

    // 🔑 ativa hx-* dentro do HTML injetado (evita navegar para /account/avatar/choose/)
    htmxProcess(body);

    // garante abas e seleção sempre ok
    umInitFromDom();
    umRefreshAvatarSelection(document);
  }

  window.Modal.user = {
    _wired: false,

    open() {
      fetch("/account/modal/", { credentials: "same-origin" })
        .then((r) => r.text())
        .then((html) => {
          const body = document.getElementById("modal-body");
          if (!body) return;

          body.innerHTML = html;
          window.Modal.open();

          afterModalHtmlInjected();

          if (!window.Modal.user._wired) {
            wireTabClicks();
            wireAvatarPresetClicks();
            window.Modal.user._wired = true;
          }
        });
    },
  };

  // compat com onclick="window.umOpenTab('...')" do template
  window.umOpenTab = umOpenTab;

  document.body.addEventListener("click", (e) => {
    if (e.target.closest("#open-user-settings")) {
      e.preventDefault();
      window.Modal.user.open();
    }
  });

  // quando o #modal-body é trocado por HTMX (hx-post dos forms), reprocessa e reinit
  document.body.addEventListener("htmx:afterSwap", (evt) => {
    const target = evt.detail && evt.detail.target;
    if (!target || target.id !== "modal-body") return;

    if (document.getElementById("um-root")) {
      afterModalHtmlInjected();
    }
  });

    // ============================================================
  // Avatar runtime update (header + modal + board) via HX-Trigger
  // ============================================================
  function applyAvatarEverywhere(url) {
    if (!url) return;

    // 1) Header (base.html) — botão do usuário no topo
    const headerImg = document.querySelector("#open-user-settings img");
    if (headerImg) {
      headerImg.src = url;
    }

    // 2) Modal — avatar grande no topo do modal
    const modalTopImg = document.querySelector("#um-root #um-avatar-img");
    if (modalTopImg) {
      modalTopImg.src = url;
    }

    // 3) Board — bolinha do próprio usuário na barra de membros
    try {
      const me = Number(window.CURRENT_USER_ID || 0);
      if (me) {
        const btn = document.querySelector(`.board-member-avatar[data-user-id="${me}"]`);
        if (btn) {
          let img = btn.querySelector("img");
          if (!img) {
            // se estava fallback (letra), troca por img
            btn.innerHTML = "";
            img = document.createElement("img");
            img.loading = "lazy";
            btn.appendChild(img);
          }
          img.src = url;
        }
      }
    } catch (_e) {}
  }

  document.body.addEventListener("userAvatarUpdated", (e) => {
    const url = e && e.detail && e.detail.url;
    applyAvatarEverywhere(url);
  });



})();
