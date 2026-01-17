// modal.tabs.js — Tabs do CM modal (cm-root)
// - Delegado (não depende de bind por swap)
// - Alterna painéis por data-cm-tab / data-cm-panel
// - Mantém estado em data-cm-active + dataset.cmActive
// - Dispara "cm:tabchange"

(function () {
  function activate(root, tab) {
    if (!root || !tab) return;

    root.setAttribute("data-cm-active", tab);
    root.dataset.cmActive = tab;

    root.querySelectorAll(".cm-tabbtn[data-cm-tab]").forEach((b) => {
      b.classList.toggle("is-active", b.getAttribute("data-cm-tab") === tab);
    });

    root.querySelectorAll(".cm-panel[data-cm-panel]").forEach((p) => {
      p.classList.toggle("is-active", p.getAttribute("data-cm-panel") === tab);
    });

    try {
      root.dispatchEvent(new CustomEvent("cm:tabchange", { detail: { tab } }));
    } catch (_e) {}
  }

  // Click delegado (funciona mesmo após HTMX swap)
  document.addEventListener(
    "click",
    function (e) {
      const btn = e.target.closest(".cm-tabbtn[data-cm-tab]");
      if (!btn) return;

      // Se for “pseudo-aba”/disabled (ex.: legado), não troca painel
      if (btn.classList.contains("cm-tab-disabled") || btn.hasAttribute("data-cm-action")) {
        return;
      }

      const root = btn.closest("#cm-root");
      if (!root) return;

      const tab = (btn.getAttribute("data-cm-tab") || "").trim();
      if (!tab) return;

      e.preventDefault();
      e.stopPropagation();

      activate(root, tab);
    },
    true
  );

  // Boot: garante que o painel inicial bate com data-cm-active
  function boot(root) {
    if (!root) return;
    const initial =
      (root.getAttribute("data-cm-active") || root.dataset.cmActive || "desc").trim() || "desc";
    activate(root, initial);
  }

  document.addEventListener("DOMContentLoaded", function () {
    boot(document.getElementById("cm-root"));
  });

  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.target && e.target.id === "modal-body") {
      boot(document.getElementById("cm-root"));
    }
  });
})();
