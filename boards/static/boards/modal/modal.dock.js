// boards/static/boards/modal/modal.dock.js
(function () {
  if (window.__cmDockDelegated === true) return;
  window.__cmDockDelegated = true;

  function getDockParts(fromEl) {
    const root = fromEl?.closest?.("#cm-root") || document.getElementById("cm-root");
    if (!root) return {};

    const dock = root.querySelector("#cm-action-dock");
    if (!dock) return {};

    const btn = dock.querySelector("#cm-dock-toggle");
    const menu = dock.querySelector("#cm-dock-actions");
    return { root, dock, btn, menu };
  }

  function open(menu, btn) {
    if (!menu || !btn) return;
    menu.classList.remove("hidden");
    btn.setAttribute("aria-expanded", "true");
  }

  function close(menu, btn) {
    if (!menu || !btn) return;
    menu.classList.add("hidden");
    btn.setAttribute("aria-expanded", "false");
  }

  function toggle(menu, btn) {
    if (!menu || !btn) return;
    const isOpen = !menu.classList.contains("hidden");
    isOpen ? close(menu, btn) : open(menu, btn);
  }

  // Clique no botão: toggle
  document.addEventListener(
    "click",
    function (e) {
      const btn = e.target?.closest?.("#cm-dock-toggle");
      if (!btn) return;

      const { menu } = getDockParts(btn);
      if (!menu) return;

      e.preventDefault();
      e.stopPropagation();
      toggle(menu, btn);
    },
    true
  );

  // Clique fora do dock: fecha (se estiver aberto)
  document.addEventListener(
    "click",
    function (e) {
      const { dock, btn, menu } = getDockParts(e.target);
      if (!dock || !btn || !menu) return;

      if (menu.classList.contains("hidden")) return;
      if (e.target.closest("#cm-action-dock")) return;

      close(menu, btn);
    },
    true
  );

  // Garantia de estado inicial sempre fechado quando o modal renderizar
  function ensureClosed() {
    const { btn, menu } = getDockParts(document.getElementById("cm-root"));
    if (!btn || !menu) return;
    close(menu, btn);
  }

  document.addEventListener("DOMContentLoaded", ensureClosed);
  document.body.addEventListener("htmx:afterSwap", (evt) => {
    const t = evt.detail?.target || evt.target;
    if (t && (t.id === "modal-body" || t.closest?.("#modal-body"))) ensureClosed();
  });
  document.body.addEventListener("htmx:afterSettle", (evt) => {
    const t = evt.detail?.target || evt.target;
    if (t && (t.id === "modal-body" || t.closest?.("#modal-body"))) ensureClosed();
  });
})();
