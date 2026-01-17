// ============================================================
// boards/static/boards/modal/modal.tag_catalog.js
// ============================================================
(function () {
  function getBoardId() {
    const m = location.pathname.match(/\/board\/(\d+)/);
    return m ? m[1] : "global";
  }

  function storageKey() {
    return `cm:tags:${getBoardId()}`;
  }

  function loadTags() {
    try {
      return JSON.parse(localStorage.getItem(storageKey()) || "[]");
    } catch {
      return [];
    }
  }

  function saveTags(tags) {
    localStorage.setItem(storageKey(), JSON.stringify(tags));
  }

  function renderTags() {
    const list = document.getElementById("cm-tag-list");
    if (!list) return;

    const tags = loadTags();
    list.innerHTML = "";

    tags.forEach(tag => {
      const chip = document.createElement("div");
      chip.className = "cm-tag-chip";
      chip.textContent = tag;

      const remove = document.createElement("span");
      remove.className = "cm-tag-remove";
      remove.textContent = "×";

      remove.onclick = (e) => {
        e.stopPropagation();
        const next = tags.filter(t => t !== tag);
        saveTags(next);
        renderTags();
      };

      chip.onclick = () => addTagToInput(tag);
      chip.appendChild(remove);
      list.appendChild(chip);
    });
  }

  function addTagToInput(tag) {
    const input = document.getElementById("cm-tags-input");
    if (!input) return;

    const current = input.value
      .split(",")
      .map(t => t.trim())
      .filter(Boolean);

    if (current.includes(tag)) return;

    current.push(tag);
    input.value = current.join(", ");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function init() {
    const addBtn = document.getElementById("cm-tag-add");
    const newInput = document.getElementById("cm-tag-new");
    const deleteToggle = document.getElementById("cm-tag-delete-toggle");
    const list = document.getElementById("cm-tag-list");

    if (!addBtn || !newInput || !list) return;

    // -------- função única ----------
    function addTag() {
      const value = newInput.value.trim();
      if (!value) return;

      const tags = loadTags();
      if (!tags.includes(value)) {
        tags.push(value);
        saveTags(tags);
        renderTags();
      }
      newInput.value = "";
    }

    // botão Incluir
    addBtn.onclick = addTag;

    // toggle excluir
    if (deleteToggle) {
      deleteToggle.onclick = () => {
        list.classList.toggle("delete-mode");
      };
    }

    renderTags();

    // -----------------------------------------
    // ENTER GLOBAL (solução definitiva)
    // -----------------------------------------
    if (!window.__cmTagCatalogEnterBound) {
      window.__cmTagCatalogEnterBound = true;

      document.addEventListener(
        "keydown",
        function (e) {
          if (e.key !== "Enter") return;

          const target = e.target;
          if (!target || target.id !== "cm-tag-new") return;

          e.preventDefault();
          e.stopPropagation();

          addTag();
        },
        true // 🔑 CAPTURE: antes do form/HTMX
      );
    }
  }

  document.addEventListener("DOMContentLoaded", init);
  document.body.addEventListener("htmx:afterSwap", init);
})();
// ============================================================
// end boards/static/boards/modal/modal.tag_catalog.js
// ============================================================
