// boards/static/modal/modal.dock.js
(function () {
  if (window.__cmDockBound === true) return;
  window.__cmDockBound = true;

  // Debug opcional:
  // window.__cmDockDebug = true;
  function debug(...args) {
    if (window.__cmDockDebug === true) console.log("[cm.dock]", ...args);
  }

  function qs(root, sel) {
    return root ? root.querySelector(sel) : null;
  }

  function getRoot(scope) {
    return scope?.querySelector?.("#cm-root") || document.getElementById("cm-root");
  }

  function getCardId(root) {
    return String(root?.getAttribute?.("data-card-id") || root?.dataset?.cardId || "").trim();
  }

  function ensureButtonType(btn) {
    if (!btn) return;
    if (!btn.getAttribute("type")) btn.setAttribute("type", "button");
  }

  function ensureHiddenWorks(el) {
    // Se Tailwind "hidden" não estiver ativo por algum motivo,
    // garantimos display none via inline.
    if (!el) return;
    if (el.classList.contains("hidden")) el.style.display = "none";
  }

  function forceDockZ(dock) {
    if (!dock) return;
    dock.style.position = "fixed";
    dock.style.right = "18px";
    dock.style.bottom = "18px";
    dock.style.zIndex = "2147483647";
    dock.style.pointerEvents = "auto";
  }

  function forceToggleVisible(dock) {
    const btn = qs(dock, "#cm-dock-toggle");
    if (!btn) return;

    ensureButtonType(btn);

    const t = (btn.textContent || "").trim();
    if (!t) btn.textContent = "⋮";

    btn.style.pointerEvents = "auto";
    btn.style.position = "relative";
    btn.style.zIndex = "2147483647";

    // fallback visual (caso CSS do template não aplique)
    btn.style.width = btn.style.width || "54px";
    btn.style.height = btn.style.height || "54px";
    btn.style.borderRadius = btn.style.borderRadius || "999px";
    btn.style.border = btn.style.border || "1px solid rgba(15,23,42,0.12)";
    btn.style.background = btn.style.background || "rgba(255,255,255,0.95)";
    btn.style.boxShadow = btn.style.boxShadow || "0 10px 30px rgba(2,6,23,0.18)";
    btn.style.display = btn.style.display || "flex";
    btn.style.alignItems = btn.style.alignItems || "center";
    btn.style.justifyContent = btn.style.justifyContent || "center";
    btn.style.fontSize = btn.style.fontSize || "22px";
    btn.style.lineHeight = btn.style.lineHeight || "1";
    btn.style.cursor = btn.style.cursor || "pointer";
  }

  function forceMenuLayout(dock) {
    const menu = qs(dock, "#cm-dock-menu");
    if (!menu) return;

    menu.style.pointerEvents = "auto";
    menu.style.position = menu.style.position || "absolute";
    menu.style.right = menu.style.right || "0";
    menu.style.bottom = menu.style.bottom || "64px";
    menu.style.minWidth = menu.style.minWidth || "210px";
    menu.style.borderRadius = menu.style.borderRadius || "14px";
    menu.style.border = menu.style.border || "1px solid rgba(15,23,42,0.12)";
    menu.style.background = menu.style.background || "rgba(255,255,255,0.98)";
    menu.style.boxShadow = menu.style.boxShadow || "0 10px 30px rgba(2,6,23,0.18)";
    menu.style.padding = menu.style.padding || "8px";
    menu.style.zIndex = menu.style.zIndex || "2147483647";

    ensureHiddenWorks(menu);
  }

  function ensureMenuItemClasses(dock) {
    const moveBtn = qs(dock, "#cm-dock-move");
    const dupBtn = qs(dock, "#cm-dock-duplicate");
    const copyBtn = qs(dock, "#cm-dock-copylink");

    [moveBtn, dupBtn, copyBtn].forEach((b) => {
      if (!b) return;
      b.classList.add("dock-action"); // garante estilo consistente (CSS do template)
      ensureButtonType(b);
      b.style.pointerEvents = "auto";
    });
  }

  function getDataUrlFromDock(dock, sel, attr) {
    const el = qs(dock, sel);
    const v = el?.getAttribute?.(attr);
    return v ? String(v).trim() : "";
  }

  // =========================
  // DOCK DISCOVERY + PORTAL
  // =========================
  function findDock(root) {
    // 1) Dock no HTML atual do modal
    const inRoot = qs(root, "#cm-action-dock");

    // 2) Dock já portado (de um bind anterior)
    const inBody = document.body.querySelector('#cm-action-dock[data-cm-portaled="1"]');

    // Se o modal renderizou um novo dock, prioriza ele e substitui o do body
    if (inRoot) {
      if (inBody && inBody !== inRoot) {
        inBody.remove();
      }
      return inRoot;
    }

    // Se não veio no root (porque já foi portado), usa o do body
    if (inBody) return inBody;

    return null;
  }

  function portalToBody(dock) {
    if (!dock) return null;

    // Marca e move para o body (mantém o id!)
    dock.dataset.cmPortaled = "1";
    if (dock.parentElement !== document.body) {
      document.body.appendChild(dock);
    }

    forceDockZ(dock);
    forceToggleVisible(dock);
    forceMenuLayout(dock);
    ensureMenuItemClasses(dock);

    // Painel do dock (Mover)
    const panel = qs(dock, "#cm-action-dock-panel");
    if (panel) {
      panel.style.pointerEvents = "auto";
      panel.style.zIndex = "2147483647";
      ensureHiddenWorks(panel);
    }

    return dock;
  }

  function closeMenu(dock) {
    const menu = qs(dock, "#cm-dock-menu");
    const btn = qs(dock, "#cm-dock-toggle");
    if (menu) {
      menu.classList.add("hidden");
      menu.style.display = "none";
    }
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function openMenu(dock) {
    const menu = qs(dock, "#cm-dock-menu");
    const btn = qs(dock, "#cm-dock-toggle");
    if (menu) {
      menu.classList.remove("hidden");
      menu.style.display = "block";
    }
    if (btn) btn.setAttribute("aria-expanded", "true");
  }

  function toggleMenu(dock) {
    const menu = qs(dock, "#cm-dock-menu");
    if (!menu) return;
    menu.classList.contains("hidden") ? openMenu(dock) : closeMenu(dock);
  }

  function openPanel(dock) {
    const panel = qs(dock, "#cm-action-dock-panel");
    if (!panel) return;
    panel.classList.remove("hidden");
    panel.style.display = "block";
    panel.style.pointerEvents = "auto";
  }

  function closePanel(dock) {
    const panel = qs(dock, "#cm-action-dock-panel");
    const body = qs(dock, "#cm-dock-panel-body");
    if (panel) {
      panel.classList.add("hidden");
      panel.style.display = "none";
    }
    if (body) body.innerHTML = "";
  }

  // =========================
  // BIND
  // =========================
  function bindDock(scope) {
    const root = getRoot(scope);
    if (!root) return;

    let dock = findDock(root);
    if (!dock) return;

    dock = portalToBody(dock);
    if (!dock) return;

    // evita bind duplicado
    if (dock.dataset.cmDockBound === "1") return;
    dock.dataset.cmDockBound = "1";

    const toggleBtn = qs(dock, "#cm-dock-toggle");
    const menu = qs(dock, "#cm-dock-menu");
    const panelBody = qs(dock, "#cm-dock-panel-body");

    if (!toggleBtn || !menu) return;

    // Estado inicial
    closeMenu(dock);
    closePanel(dock);

    // Toggle menu
    toggleBtn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggleMenu(dock);
    });

    // Clique fora fecha menu/painel
    document.addEventListener("click", function (e) {
      const inside = e.target && e.target.closest && e.target.closest("#cm-action-dock");
      if (!inside) {
        closeMenu(dock);
        closePanel(dock);
      }
    });

    // Delegação: robusto contra swaps
    dock.addEventListener("click", async function (e) {
      const btn = e.target && e.target.closest ? e.target.closest("button") : null;
      if (!btn) return;

      if (btn.id === "cm-dock-toggle") return;

      e.preventDefault();
      e.stopPropagation();

      const cardId = getCardId(root);
      if (!cardId) {
        debug("Sem cardId no #cm-root");
        closeMenu(dock);
        return;
      }

      if (btn.id === "cm-dock-copylink") {
        const url = window.location.href;
        try {
          await navigator.clipboard.writeText(url);
        } catch (_e) {
          const tmp = document.createElement("input");
          tmp.value = url;
          document.body.appendChild(tmp);
          tmp.select();
          document.execCommand("copy");
          tmp.remove();
        }
        closeMenu(dock);
        return;
      }

      if (btn.id === "cm-dock-duplicate") {
        closeMenu(dock);

        const url =
          getDataUrlFromDock(dock, "#cm-dock-duplicate", "data-url-duplicate") ||
          `/cards/${cardId}/duplicate/`;

        debug("Duplicate POST", url);

        if (!window.htmx) {
          root.dispatchEvent(new CustomEvent("cm:dock:duplicate", { bubbles: true }));
          return;
        }

        window.htmx.ajax("POST", url, { swap: "none" });

        if (typeof window.refreshCardSnippet === "function") {
          try { window.refreshCardSnippet(cardId); } catch (_e) {}
        }
        return;
      }

      if (btn.id === "cm-dock-move") {
        closeMenu(dock);

        const url =
          getDataUrlFromDock(dock, "#cm-dock-move", "data-url-move") ||
          `/cards/${cardId}/move/`;

        debug("Move GET", url);

        if (!window.htmx || !panelBody) {
          root.dispatchEvent(new CustomEvent("cm:dock:move", { bubbles: true }));
          return;
        }

        openPanel(dock);

        window.htmx.ajax("GET", url, {
          target: panelBody,
          swap: "innerHTML",
        });

        return;
      }
    });

    debug("Dock bound OK");
  }

  // =========================
  // LIFECYCLE
  // =========================
  document.addEventListener("DOMContentLoaded", () => bindDock(document));

  document.body.addEventListener("htmx:afterSwap", (evt) => {
    const t = evt.detail?.target || evt.target;
    if (!t) return;
    if (t.id === "modal-body" || (t.closest && t.closest("#modal-body"))) {
      // importante: rebind quando o body do modal troca
      bindDock(document);
    }
  });

  document.body.addEventListener("htmx:afterSettle", (evt) => {
    const t = evt.detail?.target || evt.target;
    if (!t) return;
    if (t.id === "modal-body" || (t.closest && t.closest("#modal-body"))) {
      bindDock(document);
    }
  });

  // Quando o modal fechar, remove o dock portado (evita fantasma)
  document.addEventListener("modal:closed", () => {
    const dock = document.body.querySelector('#cm-action-dock[data-cm-portaled="1"]');
    if (dock) dock.remove();
  });
})();
