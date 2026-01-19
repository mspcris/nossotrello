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

    function initChecklistCreateEnterSubmit() {
    const form = document.getElementById("cm-checklist-create-form");
    const input = document.getElementById("cm-checklist-create-input");
    if (!form || !input) return;

    if (input.dataset.enterBound === "1") return;
    input.dataset.enterBound = "1";

    input.addEventListener("keydown", (e) => {
      // Enter simples = adicionar checklist
      if (e.key !== "Enter") return;
      if (e.isComposing) return; // IME
      if (e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return;

      e.preventDefault();
      e.stopPropagation();

      const title = (input.value || "").trim();
      if (!title) return;

      // requestSubmit preserva HTMX (hx-post) e inclui o input via atributo form=""
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
        return;
      }

      // fallback (raro)
      if (window.htmx) {
        window.htmx.trigger(form, "submit");
      }
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
  // 1) achar o container real (robusto)
  const container =
    document.getElementById("checklists-container") ||
    document.getElementById("checklist-list") ||
    document.querySelector("[data-reorder-checklists-url]") ||
    document.querySelector("[data-reorder-items-url]");

  if (!container) {
    console.warn("[checklists] container not found");
    return;
  }

  if (!window.Sortable) {
    console.warn("[checklists] Sortable not loaded");
    return;
  }

  // Se o HTMX re-render trocou o DOM, esse dataset é novo.
  // Mesmo assim, não trave o init se algo falhou antes.
  if (container.dataset.sortableApplied === "1") return;

  const checklistBlockSel = ".checklist-block";
  const checklistListSel = ".checklist-items";

  // Handles: aceite variações do template
  const checklistHandleSel = ".checklist-drag, .checklist-handle, [data-checklist-drag]";
  const itemHandleSel = ".item-drag, .checklist-item-handle, [data-item-drag]";

  const blocks = container.querySelectorAll(checklistBlockSel);
  const lists = container.querySelectorAll(checklistListSel);

  console.log("[checklists] initDnD", {
    blocks: blocks.length,
    lists: lists.length,
    hasReorderChecklistsUrl: !!container.getAttribute("data-reorder-checklists-url"),
    hasReorderItemsUrl: !!container.getAttribute("data-reorder-items-url"),
  });

  // Não marque applied antes de terminar com sucesso.
  try {
    // 2) Drag de checklists (blocos)
    if (blocks.length) {
      new Sortable(container, {
        animation: 160,
        ghostClass: "drag-ghost",
        chosenClass: "drag-chosen",
        draggable: checklistBlockSel,
        handle: checklistHandleSel,

        // importante quando há elementos interativos
        forceFallback: true,
        fallbackOnBody: true,
        fallbackTolerance: 6,

        onEnd: async () => {
          const url = container.getAttribute("data-reorder-checklists-url");
          if (!url) return;

          const order = Array.from(container.querySelectorAll(checklistBlockSel))
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
    }

    // 3) Drag de itens dentro de cada checklist
    lists.forEach((list) => {
      if (list.dataset.sortableApplied === "1") return;

      // se não achar handle nenhum, loga (isso explica “nem inicia”)
      const anyHandle = list.querySelector(itemHandleSel);
      if (!anyHandle) {
        console.warn("[checklists] item handle not found in list", list);
      }

      new Sortable(list, {
        group: "checklist-items",
        animation: 160,
        ghostClass: "drag-ghost",
        chosenClass: "drag-chosen",
        draggable: ".checklist-item",
        handle: itemHandleSel,

        forceFallback: true,
        fallbackOnBody: true,
        fallbackTolerance: 6,

        onEnd: async () => {
          const url = container.getAttribute("data-reorder-items-url");
          if (!url) return;

          const updates = [];
          container.querySelectorAll(checklistListSel).forEach((itemsWrap) => {
            const checklistId = parseInt(itemsWrap.getAttribute("data-checklist-id"), 10);
            if (!checklistId) return;

            Array.from(itemsWrap.querySelectorAll(".checklist-item")).forEach((li, idx) => {
              const itemId = parseInt(li.getAttribute("data-item-id"), 10);
              if (!itemId) return;
              updates.push({ item_id: itemId, checklist_id: checklistId, position: idx });
            });
          });

          if (!updates.length) return;

          try {
            await postJSON(url, { updates });
          } catch (e) {
            console.error("checklist_items_reorder:", e);
          }
        },
      });

      list.dataset.sortableApplied = "1";
    });

    container.dataset.sortableApplied = "1";
  } catch (e) {
    console.error("[checklists] initDnD failed:", e);
    // não marca applied -> permite tentar de novo
  }
}


  
  function initChecklistCreateFormReset() {
  const form = document.getElementById("cm-checklist-create-form");
  if (!form) return;

  if (form.dataset.resetBound === "1") return;
  form.dataset.resetBound = "1";

  form.addEventListener("htmx:afterRequest", () => {
    const input = form.querySelector("input, textarea");
    if (input) input.value = "";
  });
}

  // ============================================================
  // PUBLIC INIT
  // ============================================================
  Modal.checklists.init = function () {
    initChecklistUX(document);
    initChecklistCreateFormReset();
    initChecklistCreateEnterSubmit();
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
      initChecklistCreateEnterSubmit();
      initChecklistDnD();
      reopenQuickAddIfNeeded();
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    Modal.checklists.init();
  });
})();
