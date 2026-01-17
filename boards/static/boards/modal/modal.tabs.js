// modal.tabs.js — Tabs do CM modal (cm-root)
// - Delegado (não depende de bind por swap)
// - Alterna painéis por data-cm-tab / data-cm-panel
// - Mantém estado em data-cm-active + dataset.cmActive
// - Dispara "cm:tabchange" (para módulos como activity_quill, tracktime, etc.)

(function () {
  const STATE_KEY = "__cmTabsDelegatedBound";

  function getRoot() {
    return document.getElementById("cm-root");
  }

  function activate(root, tab) {
    if (!root) return;

    const t = String(tab || "").trim() || "desc";

    // estado
    root.setAttribute("data-cm-active", t);
    root.dataset.cmActive = t;

    // tabs
    root.querySelectorAll(".cm-tabbtn[data-cm-tab]").forEach((b) => {
      b.classList.toggle("is-active", (b.getAttribute("data-cm-tab") || "").trim() === t);
    });

    // panels
    root.querySelectorAll(".cm-panel[data-cm-panel]").forEach((p) => {
      p.classList.toggle("is-active", (p.getAttribute("data-cm-panel") || "").trim() === t);
    });

    // integra com módulos
    try {
      root.dispatchEvent(new CustomEvent("cm:tabchange", { detail: { tab: t } }));
    } catch (_e) {}
  }

  // Boot: garante que o painel inicial bate com data-cm-active
  function boot() {
    const root = getRoot();
    if (!root) return;

    const initial =
      (root.getAttribute("data-cm-active") || root.dataset.cmActive || "desc").trim() || "desc";

    activate(root, initial);
  }

  // Click delegado (funciona mesmo após HTMX swap)
  function bindDelegatedClickOnce() {
    if (document.body.dataset[STATE_KEY] === "1") return;
    document.body.dataset[STATE_KEY] = "1";

    document.addEventListener(
      "click",
      function (e) {
        const btn = e.target && e.target.closest
          ? e.target.closest(".cm-tabbtn[data-cm-tab]")
          : null;
        if (!btn) return;

        // Se for “pseudo-aba”/disabled, não troca painel
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
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindDelegatedClickOnce();
    boot();
  });

  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.target && e.target.id === "modal-body") {
      // não precisa rebind (delegado), só re-sincroniza estado/painel
      boot();
    }
  });
})();
