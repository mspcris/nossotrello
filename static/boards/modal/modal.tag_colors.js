//boards/static/boards/modal/modal.tag_colors.js

(function () {
  function getRoot() {
    return document.getElementById("cm-root");
  }

  window.cmOpenTagColor = function (btn) {
    const root = getRoot();
    if (!root || !btn) return;

    const tag = btn.getAttribute("data-tag");
    if (!tag) return;

    const picker = root.querySelector("#cm-tag-color-picker");
    const inpTag = root.querySelector("#cm-tag-color-tag");
    const inpColor = root.querySelector("#cm-tag-color-value");
    const form = root.querySelector("#cm-tag-color-form");

    if (!picker || !inpTag || !inpColor || !form) return;

    inpTag.value = tag;

    // garante mudança SEMPRE
    picker.value = inpColor.value || "#000000";
    picker.click();

    picker.onchange = function () {
      inpColor.value = picker.value;
      try {
        form.requestSubmit();
      } catch {
        form.submit();
      }
    };
  };
})();


//END boards/static/boards/modal/modal.tag_colors.js