// ============================================================
// boards/static/boards/modal/modal.tag_catalog.js
// ============================================================
(function () {
  if (!window.Modal) window.Modal = {};
  if (window.Modal.tagCatalog) return;

  function getModalRoot() {
    const modalBody = document.getElementById("modal-body");
    if (modalBody) {
      const r = modalBody.querySelector("#cm-root");
      if (r) return r;
    }
    const all = document.querySelectorAll("#cm-root");
    return all && all.length ? all[all.length - 1] : null;
  }

  function getBoardId() {
    const m = location.pathname.match(/\/board\/(\d+)/);
    return m ? m[1] : "global";
  }

  function storageKey() {
    return `cm:tags:${getBoardId()}`;
  }

  function loadTags() {
    try { return JSON.parse(localStorage.getItem(storageKey()) || "[]"); }
    catch (_e) { return []; }
  }

  function saveTags(tags) {
    try { localStorage.setItem(storageKey(), JSON.stringify(tags)); }
    catch (_e) {}
  }

  function renderTags(root) {
    const list = root?.querySelector("#cm-tag-list");
    if (!list) return;

    const tags = loadTags();
    list.innerHTML = "";

    tags.forEach((tag) => {
      const chip = document.createElement("div");
      chip.className = "cm-tag-chip";
      chip.textContent = tag;

      const remove = document.createElement("span");
      remove.className = "cm-tag-remove";
      remove.textContent = "×";

      remove.onclick = (e) => {
        e.stopPropagation();
        const next = tags.filter((t) => t !== tag);
        saveTags(next);
        renderTags(root);
      };

      chip.onclick = () => addTagToInput(root, tag);
      chip.appendChild(remove);
      list.appendChild(chip);
    });
  }

  function addTagToInput(root, tag) {
    const input = root?.querySelector("#cm-tags-input");
    if (!input) return;

    const current = String(input.value || "")
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    if (current.includes(tag)) return;

    current.push(tag);
    input.value = current.join(", ");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function init() {
    const root = getModalRoot();
    if (!root) return;

    const addBtn = root.querySelector("#cm-tag-add");
    const newInput = root.querySelector("#cm-tag-new");
    const deleteToggle = root.querySelector("#cm-tag-delete-toggle");
    const list = root.querySelector("#cm-tag-list");

    if (!addBtn || !newInput || !list) return;

    // evita bind duplicado por root
    if (root.dataset.cmTagCatalogBound === "1") return;
    root.dataset.cmTagCatalogBound = "1";

    function addTag() {
      const value = String(newInput.value || "").trim();
      if (!value) return;

      const tags = loadTags();
      if (!tags.includes(value)) {
        tags.push(value);
        saveTags(tags);
        renderTags(root);
      }
      newInput.value = "";
    }

    addBtn.onclick = addTag;

    if (deleteToggle) {
      deleteToggle.onclick = () => list.classList.toggle("delete-mode");
    }

    renderTags(root);

    // ENTER GLOBAL (uma vez só)
    if (!window.__cmTagCatalogEnterBound) {
      window.__cmTagCatalogEnterBound = true;

      document.addEventListener(
        "keydown",
        function (e) {
          if (e.key !== "Enter") return;

          const r = getModalRoot();
          if (!r) return;

          const target = e.target;
          if (!target || target.id !== "cm-tag-new") return;

          e.preventDefault();
          e.stopPropagation();

          // reusa o addTag do root atual (sem depender de closure antiga)
          const btn = r.querySelector("#cm-tag-add");
          if (btn) btn.click();
        },
        true
      );
    }
  }

  window.Modal.tagCatalog = { init };

  document.addEventListener("DOMContentLoaded", init);
  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e?.target?.id === "modal-body") init();
  });
})();
// ============================================================
// end boards/static/boards/modal/modal.tag_catalog.js
// ============================================================
