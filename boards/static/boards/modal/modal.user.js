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

    // ativa hx-* dentro do HTML injetado
    htmxProcess(body);

    // garante abas e seleção sempre ok
    umInitFromDom();
    umRefreshAvatarSelection(document);

    /* Aqui o modal buscava a rede social inteira e injetava na coluna da direita.
       Era da época em que o Espaço Social morava dentro do modal; ele virou página
       própria e isto ficou para trás. No celular a coluna da direita empilha
       embaixo, então abrir a foto mostrava as configurações E o perfil social na
       mesma rolagem, com o Salvar do formulário por cima (chamado LZA-GBH-PA1M). */

    // Executa inline <script> tags (innerHTML não os roda automaticamente)
    // Protegido com try/catch para não bloquear o carregamento do social
    try {
      body.querySelectorAll("script").forEach(function(old) {
        try {
          var ns = document.createElement("script");
          ns.textContent = old.textContent;
          old.parentNode.replaceChild(ns, old);
        } catch(e) { console.error("[modal.user] script exec error:", e); }
      });
    } catch(e) { console.error("[modal.user] script loop error:", e); }
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

  /* Filme fumê + bolinha ao salvar qualquer coisa do modal da conta — o mesmo
     ntBusy já usado nas ações lentas do card. Fica aqui, delegado, em vez de um
     par de hx-on em cada um dos cinco formulários: assim vale também pros que
     forem criados depois.

     Casamento pelo XHR, não pelo elemento: o htmx troca o #modal-body na
     resposta, e no afterRequest o elemento que disparou pode já estar fora do
     DOM — aí o closest() falharia e a tela ficaria escura pra sempre. */
  const umBusyXhr = new WeakSet();

  document.body.addEventListener("htmx:beforeRequest", (evt) => {
    const el = evt.detail && evt.detail.elt;
    const xhr = evt.detail && evt.detail.xhr;
    if (!xhr || !el || !el.closest || !el.closest("#um-root")) return;
    umBusyXhr.add(xhr);
    if (typeof window.ntBusy === "function") window.ntBusy(true, "Salvando…");
  });

  document.body.addEventListener("htmx:afterRequest", (evt) => {
    const xhr = evt.detail && evt.detail.xhr;
    if (!xhr || !umBusyXhr.has(xhr)) return;
    umBusyXhr.delete(xhr);
    if (typeof window.ntBusy === "function") window.ntBusy(false);
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
