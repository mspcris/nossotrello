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

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  function getEndpoints(root) {
    const boardId = getBoardId();

    // Se você preferir, pode setar isso via data-attrs no #cm-root:
    // data-tag-catalog-get="/board/123/tag-catalog/"
    // data-tag-catalog-set="/board/123/tag-catalog/set/"
    // data-tag-catalog-del="/board/123/tag-catalog/delete/"
    const ds = root && root.dataset ? root.dataset : {};

    const urlGet =
      ds.tagCatalogGet || (boardId !== "global" ? `/board/${boardId}/tag-catalog/` : `/board/${boardId}/tag-catalog/`);
    const urlSet =
      ds.tagCatalogSet || (boardId !== "global" ? `/board/${boardId}/tag-catalog/set/` : `/board/${boardId}/tag-catalog/set/`);
    const urlDel =
      ds.tagCatalogDel || (boardId !== "global" ? `/board/${boardId}/tag-catalog/delete/` : `/board/${boardId}/tag-catalog/delete/`);

    return { urlGet, urlSet, urlDel };
  }

  function normalizeTags(payload) {
    // Esperado: [{name:"Bug", color:"#ff0000"}, ...]
    // Compat: ["Bug", "Melhoria"] => converte para cor neutra
    const tags = Array.isArray(payload) ? payload : [];

    return tags
      .map((t) => {
        if (typeof t === "string") return { name: t, color: "#888888" };
        if (t && typeof t === "object") {
          const name = String(t.name || "").trim();
          const color = String(t.color || "#888888").trim();
          if (!name) return null;
          return { name, color: /^#[0-9a-fA-F]{6}$/.test(color) ? color : "#888888" };
        }
        return null;
      })
      .filter(Boolean);
  }

  async function apiGetCatalog(root) {
    const { urlGet } = getEndpoints(root);
    const r = await fetch(urlGet, {
      method: "GET",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
    });

    if (!r.ok) return [];
    const j = await r.json().catch(() => ({}));
    return normalizeTags(j.tags);
  }

  async function apiSetTag(root, name, color) {
    const { urlSet } = getEndpoints(root);
    const csrftoken = getCookie("csrftoken");

    const r = await fetch(urlSet, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrftoken,
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
      body: JSON.stringify({ tag: name, color }),
    });

    return r.ok;
  }

  async function apiDeleteTag(root, name) {
    const { urlDel } = getEndpoints(root);
    const csrftoken = getCookie("csrftoken");

    const r = await fetch(urlDel, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrftoken,
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
      body: JSON.stringify({ tag: name }),
    });

    return r.ok;
  }

  function safeText(s) {
    return String(s == null ? "" : s);
  }

  function setChipColor(chip, color) {
    // Visual simples e consistente: chip usa a cor
    chip.style.backgroundColor = color;
    chip.style.borderColor = color;

    // Texto: heurística básica (sem depender de libs)
    // Se cor for escura, texto branco.
    const c = color.replace("#", "");
    const r = parseInt(c.substring(0, 2), 16);
    const g = parseInt(c.substring(2, 4), 16);
    const b = parseInt(c.substring(4, 6), 16);
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    chip.style.color = luminance < 0.55 ? "#fff" : "#111";
  }

  async function renderTags(root) {
    const list = root?.querySelector("#cm-tag-list");
    if (!list) return;

    const tags = await apiGetCatalog(root);

    list.innerHTML = "";

    tags.forEach((tagObj) => {
      const tagName = tagObj.name;
      const tagColor = tagObj.color || "#888888";

      const chip = document.createElement("div");
      chip.className = "cm-tag-chip";
      chip.textContent = safeText(tagName);

      // aplica cor (chip + contraste)
      setChipColor(chip, tagColor);

      const remove = document.createElement("span");
      remove.className = "cm-tag-remove";
      remove.textContent = "×";

      remove.onclick = async (e) => {
        e.stopPropagation();
        await apiDeleteTag(root, tagName);
        await renderTags(root);
      };

      chip.onclick = () => addTagToInput(root, tagName);

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
    const colorInput = root.querySelector("#cm-tag-new-color");
    const deleteToggle = root.querySelector("#cm-tag-delete-toggle");
    const list = root.querySelector("#cm-tag-list");

    if (!addBtn || !newInput || !list) return;

    // evita bind duplicado por root
    if (root.dataset.cmTagCatalogBound === "1") return;
    root.dataset.cmTagCatalogBound = "1";

    async function addTag() {
      const value = String(newInput.value || "").trim();
      if (!value) return;

      const color = colorInput ? String(colorInput.value || "").trim() : "#888888";
      const normalizedColor = /^#[0-9a-fA-F]{6}$/.test(color) ? color : "#888888";

      // salva no backend (upsert)
      const ok = await apiSetTag(root, value, normalizedColor);
      if (ok) {
        await renderTags(root);
      }

      newInput.value = "";
      // mantém a cor selecionada (não reseta), por UX
    }

    addBtn.onclick = function () {
      // não deixa o onclick antigo sobreviver; sempre usa a versão async
      addTag();
    };

    if (deleteToggle) {
      deleteToggle.onclick = () => list.classList.toggle("delete-mode");
    }

    // render inicial
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
