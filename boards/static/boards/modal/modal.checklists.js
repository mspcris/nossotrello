// boards/static/boards/modal/modal.checklists.js
(() => {
  const Modal =
    (window.Modal && typeof window.Modal === "object") ? window.Modal : {};
  window.Modal = Modal;

  Modal.checklists = Modal.checklists || {};

  // Guarda o último checklist onde o usuário adicionou item,
  // para reabrir e focar após o HTMX re-render do #checklist-list.
  const state = {
    lastChecklistIdForQuickAdd: null,
  };

  function initChecklistUX(root) {
    const scope = root || document;

    scope.querySelectorAll(".checklist-add").forEach((wrap) => {
      if (wrap.dataset.binded === "1") return;
      wrap.dataset.binded = "1";

      const openBtn = wrap.querySelector(".checklist-add-open");
      const form = wrap.querySelector(".checklist-add-form");
      const cancel = wrap.querySelector(".checklist-add-cancel");
      const input = wrap.querySelector(".checklist-add-input");

      if (!openBtn || !form) return;

      openBtn.addEventListener("click", () => {
        form.classList.remove("hidden");
        openBtn.classList.add("hidden");
        setTimeout(() => input?.focus(), 0);
      });

      cancel?.addEventListener("click", () => {
        form.classList.add("hidden");
        openBtn.classList.remove("hidden");
        if (input) input.value = "";
      });

      // Ao submeter item, marca o checklist para reabrir após swap
      form.addEventListener("submit", () => {
        const block = wrap.closest("[data-checklist-id]");
        const checklistId = block?.getAttribute("data-checklist-id");
        if (checklistId) state.lastChecklistIdForQuickAdd = checklistId;
      });
    });
  }

  function reopenQuickAddIfNeeded() {
    const checklistId = state.lastChecklistIdForQuickAdd;
    if (!checklistId) return;

    const block = document.querySelector(
      `[data-checklist-id="${checklistId}"]`
    );
    if (!block) return;

    const wrap = block.querySelector(".checklist-add");
    const openBtn = wrap?.querySelector(".checklist-add-open");
    const form = wrap?.querySelector(".checklist-add-form");
    const input = wrap?.querySelector(".checklist-add-input");

    if (!openBtn || !form || !input) return;

    // Mantém o fluxo de “lista” (sempre pronto para o próximo item)
    form.classList.remove("hidden");
    openBtn.classList.add("hidden");
    input.value = "";
    setTimeout(() => input.focus(), 0);

    // Consome o estado
    state.lastChecklistIdForQuickAdd = null;
  }

  function initChecklistCreateFormReset() {
    // Form de "Novo checklist" fica no painel check.
    // A lista atualiza (#checklist-list), então limpamos o input manualmente após request.
    const form = document.getElementById("cm-checklist-create-form");
    const input = document.getElementById("cm-checklist-create-input");
    if (!form || !input) return;
    if (form.dataset.binded === "1") return;
    form.dataset.binded = "1";

    form.addEventListener("submit", () => {
      // limpa otimista (se falhar, o usuário digita de novo)
      setTimeout(() => {
        input.value = "";
      }, 0);
    });
  }

  // ============================================================
  // HELPERS (CSRF + POST JSON)
  // ============================================================
  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  async function postJSON(url, payload) {
    const csrftoken = getCookie("csrftoken");

    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrftoken,
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });

    let data = null;
    try {
      data = await resp.json();
    } catch (_e) {}

    if (!resp.ok) {
      const msg =
        data && (data.error || data.detail)
          ? data.error || data.detail
          : `HTTP ${resp.status}`;
      throw new Error(msg);
    }
    return data;
  }

  // ============================================================
  // DnD (SortableJS) + persistência backend
  // ============================================================
  function initChecklistDnD() {
    const container = document.getElementById("checklists-container");
    if (!container) return;

    // Se Sortable não carregou, NÃO marque como aplicado.
    // Assim, quando o script carregar depois, o init tenta de novo.
    if (!window.Sortable) return;

    // Agora sim: evita duplicar bindings
    if (container.dataset.sortableApplied === "1") return;
    container.dataset.sortableApplied = "1";

    // 1) Drag de checklists (blocos)
    new Sortable(container, {
      animation: 160,
      ghostClass: "drag-ghost",
      chosenClass: "drag-chosen",
      draggable: ".checklist-block",
      handle: ".checklist-drag",

      onEnd: async () => {
        const url = container.getAttribute("data-reorder-checklists-url");
        if (!url) return;

        const order = Array.from(
          container.querySelectorAll(".checklist-block")
        )
          .map((el) => parseInt(el.getAttribute("data-checklist-id"), 10))
          .filter(Boolean);

        if (!order.length) return;

        try {
          await postJSON(url, { order });
        } catch (e) {
          console.error("checklists_reorder:", e);
        }
      },
    });

    // 2) Drag de itens dentro de cada checklist
    container.querySelectorAll(".checklist-items").forEach((list) => {
      if (list.dataset.sortableApplied === "1") return;
      list.dataset.sortableApplied = "1";

      new Sortable(list, {
        group: "checklist-items",
        animation: 160,
        ghostClass: "drag-ghost",
        chosenClass: "drag-chosen",
        draggable: ".checklist-item",
        handle: ".checklist-item-handle",

        onEnd: async () => {
          const url = container.getAttribute("data-reorder-items-url");
          if (!url) return;

          // Monta updates para TODOS os itens (consistência total)
          const updates = [];
          container.querySelectorAll(".checklist-items").forEach((itemsWrap) => {
            const checklistId = parseInt(
              itemsWrap.getAttribute("data-checklist-id"),
              10
            );
            if (!checklistId) return;

            Array.from(itemsWrap.querySelectorAll(".checklist-item")).forEach(
              (li, idx) => {
                const itemId = parseInt(li.getAttribute("data-item-id"), 10);
                if (!itemId) return;
                updates.push({
                  item_id: itemId,
                  checklist_id: checklistId,
                  position: idx,
                });
              }
            );
          });

          if (!updates.length) return;

          try {
            await postJSON(url, { updates });
          } catch (e) {
            console.error("checklist_items_reorder:", e);
          }
        },
      });
    });
  }

  // ============================================================
  // PUBLIC INIT
  // ============================================================
  Modal.checklists.init = function () {
    initChecklistUX(document);
    initChecklistCreateFormReset();
    initChecklistDnD();
  };

  // Rebind em swaps HTMX (checklist-list e modal-body)
  document.body.addEventListener("htmx:afterSwap", (evt) => {
    const t = evt.target;
    if (!t) return;

    if (
      t.id === "checklist-list" ||
      t.id === "modal-body" ||
      t.closest?.("#modal-body")
    ) {
      initChecklistUX(t);
      initChecklistCreateFormReset();
      initChecklistDnD();
      reopenQuickAddIfNeeded();
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    Modal.checklists.init();
  });
})();
