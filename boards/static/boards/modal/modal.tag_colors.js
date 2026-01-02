// modal.tag_colors.js — Cor das TAGs no CM modal
// - Lê JSON de data-tag-colors no #cm-root
// - Aplica em #cm-tags-wrap button[data-tag]
// - Usa form hidden #cm-tag-color-form + color input #cm-tag-color-picker (se existirem)
// Baseado no applySavedTagColors + initTagColorPicker do card_modal_body.html.

(function () {
  function getRoot() {
    return document.getElementById("cm-root");
  }

  function applySavedTagColors(root) {
    if (!root) return;

    let colors = {};
    try {
      const raw = root.getAttribute("data-tag-colors") || "{}";
      colors = JSON.parse(raw);
      if (!colors || typeof colors !== "object") colors = {};
    } catch (_e) {
      colors = {};
    }

    const wrap = root.querySelector("#cm-tags-wrap");
    if (!wrap) return;

    wrap.querySelectorAll("button[data-tag]").forEach((btn) => {
      const tag = btn.getAttribute("data-tag");
      const c = colors[tag];
      if (!c) return;

      btn.style.backgroundColor = c + "20";
      btn.style.color = c;
      btn.style.borderColor = c;
    });
  }

  function initTagColorPicker(root) {
    if (!root) return;
    if (root.dataset.cmTagColorBound === "1") return;
    root.dataset.cmTagColorBound = "1";

    const wrap = root.querySelector("#cm-tags-wrap");
    const form = root.querySelector("#cm-tag-color-form");
    const inpTag = root.querySelector("#cm-tag-color-tag");
    const inpColor = root.querySelector("#cm-tag-color-value");
    const picker = root.querySelector("#cm-tag-color-picker");

    // se o template ainda não tiver esses elementos, só não faz nada
    if (!wrap || !form || !inpTag || !inpColor || !picker) return;

    let currentTag = "";

    wrap.addEventListener("click", function (e) {
      const btn = e.target.closest("button[data-tag]");
      if (!btn) return;

      currentTag = btn.getAttribute("data-tag") || "";
      if (!currentTag) return;

      // default visual
      picker.value = "#3b82f6";
      picker.click();
    });

    picker.addEventListener("change", function () {
      if (!currentTag) return;

      inpTag.value = currentTag;
      inpColor.value = picker.value;

      try {
        form.requestSubmit();
      } catch (_e) {
        form.submit();
      }
    });
  }

  // expõe pro resto do modal (seu activity_quill chama isso após swap)
  window.applySavedTagColorsToModal = function (root) {
    applySavedTagColors(root || getRoot());
  };

  function boot() {
    const root = getRoot();
    initTagColorPicker(root);
    applySavedTagColors(root);
  }

  document.addEventListener("DOMContentLoaded", boot);

  document.body.addEventListener("htmx:afterSwap", function (e) {
    const t = e.target;
    if (!t) return;

    // reinit completo quando troca modal-body
    if (t.id === "modal-body") boot();

    // quando a barra de tags for re-renderizada, reaplica cores
    if (t.id === "cm-tags-wrap") {
      const root = getRoot();
      applySavedTagColors(root);
    }
  });
})();
