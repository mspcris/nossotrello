// modal.tabs.js — Tabs do CM modal (cm-root)
// - Alterna painéis por data-cm-tab / data-cm-panel
// - Mantém estado em data-cm-active
// - Dispara evento "cm:tabchange" (para módulos como activity_quill)
// Baseado no initRadicalTabs do card_modal_body.html, com dispatch do evento.

(function () {
  const STATE_KEY = "__cmTabsBound";

  function qs(sel, root = document) {
    return root.querySelector(sel);
  }
  function qsa(sel, root = document) {
    return Array.from(root.querySelectorAll(sel));
  }

  function getRoot() {
    return document.getElementById("cm-root");
  }

  function initTabs(root) {
    if (!root) return;
    if (root.dataset[STATE_KEY] === "1") return;
    root.dataset[STATE_KEY] = "1";

    const tabs = qsa("[data-cm-tab]", root);
    const panels = qsa("[data-cm-panel]", root);
    if (!tabs.length || !panels.length) return;

    function activate(name) {
      // estado (também controla visibilidade do salvar via CSS)
      root.dataset.cmActive = name;
      root.setAttribute("data-cm-active", name);

      tabs.forEach((b) =>
        b.classList.toggle("is-active", b.getAttribute("data-cm-tab") === name)
      );
      panels.forEach((p) =>
        p.classList.toggle("is-active", p.getAttribute("data-cm-panel") === name)
      );

      // integra com módulos (ex.: activity_quill)
      root.dispatchEvent(
        new CustomEvent("cm:tabchange", { detail: { tab: name } })
      );
    }

    tabs.forEach((btn) => {
      btn.addEventListener("click", function () {
        activate(btn.getAttribute("data-cm-tab"));
      });
    });

    // default
    const initial = root.getAttribute("data-cm-active") || "desc";
    activate(initial);
  }

  function boot() {
    initTabs(getRoot());
  }

  document.addEventListener("DOMContentLoaded", boot);

  // rebind pós swap do HTMX (modal-body re-render)
  document.body.addEventListener("htmx:afterSwap", function (e) {
    const t = e.target;
    if (!t) return;

    // seu fluxo costuma trocar o modal-body inteiro
    if (t.id === "modal-body") boot();
  });
})();
