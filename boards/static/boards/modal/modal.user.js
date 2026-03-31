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

  // ── Carrega painel social via fetch ────────────────────────
  function loadSocialPanel(container) {
    if (!container) return;
    var uid = Number(window.CURRENT_USER_ID || 0);
    if (!uid) return;
    // Evita recarregar se já carregou
    if (container.querySelector("#social-panel")) return;
    container.innerHTML = '<div class="sp-loading">Carregando...</div>';
    fetch("/users/" + uid + "/social/", { credentials: "same-origin" })
      .then(function(r) { return r.text(); })
      .then(function(html) {
        container.innerHTML = html;
        htmxProcess(container);
        // Executa scripts inline do social_panel.html
        container.querySelectorAll("script").forEach(function(old) {
          var ns = document.createElement("script");
          ns.textContent = old.textContent;
          old.parentNode.replaceChild(ns, old);
        });
      })
      .catch(function() {
        container.innerHTML = '<div class="sp-loading">Erro ao carregar painel social.</div>';
      });
  }

  function umOpenTab(tab) {
    const panels = {
      profile: document.getElementById("um-panel-profile"),
      password: document.getElementById("um-panel-password"),
      avatar: document.getElementById("um-panel-avatar"),
      social: document.getElementById("um-panel-social"),
    };

    Object.keys(panels).forEach((k) => {
      if (panels[k]) panels[k].style.display = (k === tab) ? "block" : "none";
    });

    document.querySelectorAll("[data-um-tab]").forEach((btn) => {
      const isActive = btn.getAttribute("data-um-tab") === tab;
      btn.classList.toggle("font-semibold", isActive);
    });

    // Oculta aside e divider no tab social para dar mais espaço
    const divider = document.getElementById("um-divider-el");
    const aside = document.getElementById("um-right-el");
    if (divider) divider.style.display = tab === "social" ? "none" : "";
    if (aside) aside.style.display = tab === "social" ? "none" : "";

    // Ao abrir tab social, carrega o conteúdo
    if (tab === "social" && panels.social) {
      loadSocialPanel(panels.social);
    }

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

    // ativa hx-* dentro do HTML injetado
    htmxProcess(body);

    // Executa inline <script> tags (innerHTML não os roda automaticamente)
    body.querySelectorAll("script").forEach(function(old) {
      var ns = document.createElement("script");
      ns.textContent = old.textContent;
      old.parentNode.replaceChild(ns, old);
    });

    // garante abas e seleção sempre ok
    umInitFromDom();
    umRefreshAvatarSelection(document);

    // Carrega painel social no aside direito via fetch
    var aside = document.getElementById("um-right-el");
    if (aside) {
      loadSocialPanel(aside);
    }
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

    // 1) Header (base.html)
    const headerImg = document.querySelector("#open-user-settings img");
    if (headerImg) {
      headerImg.src = url;
    }

    // 2) Modal — avatar grande no topo
    const modalTopImg = document.querySelector("#um-root #um-avatar-img");
    if (modalTopImg) {
      modalTopImg.src = url;
    }

    // 3) Board — bolinha do próprio usuário
    try {
      const me = Number(window.CURRENT_USER_ID || 0);
      if (me) {
        const btn = document.querySelector(`.board-member-avatar[data-user-id="${me}"]`);
        if (btn) {
          let img = btn.querySelector("img");
          if (!img) {
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
