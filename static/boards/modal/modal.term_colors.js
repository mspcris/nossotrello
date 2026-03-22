// modal.term_colors.js — Cor de TERMOS no CM modal
// - Lê JSON de data-term-colors no #cm-root
// - Aplica em #cm-terms-wrap button[data-term]
// - (Opcional) usa form hidden #cm-term-color-form + picker #cm-term-color-picker

(function () {
  function getRoot() {
    return document.getElementById("cm-root");
  }

  function parseColors(root) {
    let colors = {};
    try {
      const raw = root?.getAttribute("data-term-colors") || "{}";
      colors = JSON.parse(raw);
      if (!colors || typeof colors !== "object") colors = {};
    } catch (_e) {
      colors = {};
    }
    return colors;
  }

  function applySavedTermColors(root) {
    if (!root) return;

    const colors = parseColors(root);
    const wrap = root.querySelector("#cm-terms-wrap");
    if (!wrap) return;

    wrap.querySelectorAll("button[data-term]").forEach((btn) => {
      const term = btn.getAttribute("data-term");
      const c = colors[term];
      if (!c) return;

      btn.style.backgroundColor = c + "20";
      btn.style.color = c;
      btn.style.borderColor = c;
    });
  }

  function initTermColorPicker(root) {
    if (!root) return;
    if (root.dataset.cmTermColorBound === "1") return;
    root.dataset.cmTermColorBound = "1";

    const wrap = root.querySelector("#cm-terms-wrap");
    const form = root.querySelector("#cm-term-color-form");
    const inpTerm = root.querySelector("#cm-term-color-term");
    const inpColor = root.querySelector("#cm-term-color-value");
    const picker = root.querySelector("#cm-term-color-picker");

    if (!wrap || !form || !inpTerm || !inpColor || !picker) return;

    let currentTerm = "";

    wrap.addEventListener("click", function (e) {
      const btn = e.target.closest("button[data-term]");
      if (!btn) return;

      currentTerm = btn.getAttribute("data-term") || "";
      if (!currentTerm) return;

      picker.value = "#3b82f6";
      picker.click();
    });

    picker.addEventListener("change", function () {
      if (!currentTerm) return;

      inpTerm.value = currentTerm;
      inpColor.value = picker.value;

      try {
        form.requestSubmit();
      } catch (_e) {
        form.submit();
      }
    });
  }

  window.applySavedTermColorsToModal = function (root) {
    applySavedTermColors(root || getRoot());
  };

  function boot() {
    const root = getRoot();
    initTermColorPicker(root);
    applySavedTermColors(root);
  }

  document.addEventListener("DOMContentLoaded", boot);

  document.body.addEventListener("htmx:afterSwap", function (e) {
    const t = e.target;
    if (!t) return;

    if (t.id === "modal-body") boot();
    if (t.id === "cm-terms-wrap") applySavedTermColors(getRoot());
  });
})();
