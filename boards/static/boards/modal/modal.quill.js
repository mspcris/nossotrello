// boards/static/boards/modal/modal.quill.js
// boards/static/boards/modal/modal.quill.js
(() => {
  if (!window.Modal) return;

  window.Modal.quill = window.Modal.quill || {};

  function getBoardIdFromUrl() {
    const m = (window.location.pathname || "").match(/\/board\/(\d+)\b/);
    return m ? m[1] : null;
  }

  function renderMentionCard(item) {
    const name =
      (item?.display_name || "").trim() ||
      (item?.handle ? `@${item.handle}` : "") ||
      (item?.email || "").trim();

    const handle = (item?.handle || "").trim();
    const email = (item?.email || "").trim();
    const avatar = (item?.avatar_url || "").trim();

    const root = document.createElement("div");
    root.className = "mention-card";

    let avatarEl;
    if (avatar) {
      avatarEl = document.createElement("img");
      avatarEl.className = "mention-avatar";
      avatarEl.src = avatar;
      avatarEl.alt = "";
    } else {
      avatarEl = document.createElement("div");
      avatarEl.className = "mention-avatar mention-avatar-fallback";
      avatarEl.textContent = (handle || name || "?").slice(0, 2).toUpperCase();
    }

    const meta = document.createElement("div");
    meta.className = "mention-meta";

    const nameEl = document.createElement("div");
    nameEl.className = "mention-name";
    nameEl.textContent = name;
    meta.appendChild(nameEl);

    if (handle) {
      const handleEl = document.createElement("div");
      handleEl.className = "mention-handle";
      handleEl.textContent = `@${handle}`;
      meta.appendChild(handleEl);
    }

    if (email) {
      const emailEl = document.createElement("div");
      emailEl.className = "mention-email";
      emailEl.textContent = email;
      meta.appendChild(emailEl);
    }

    root.appendChild(avatarEl);
    root.appendChild(meta);
    return root;
  }

  function makeMentionConfig(boardId) {
    return {
      allowedChars: /^[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+$/,
      mentionDenotationChars: ["@"],
      showDenotationChar: true,

      source: async function (searchTerm, renderList) {
        try {
          if (!boardId) return renderList([], searchTerm);

          const url = `/board/${boardId}/mentions/?q=${encodeURIComponent(searchTerm || "")}`;
          const r = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
          if (!r.ok) return renderList([], searchTerm);

          const users = await r.json();
          renderList(users || [], searchTerm);
        } catch (_e) {
          renderList([], searchTerm);
        }
      },

      renderItem: function (item) {
        return renderMentionCard(item);
      },

      onSelect: function (item, insertItem) {
        insertItem(item);
      },
    };
  }

  function insertBase64ImageIntoQuill(quill, file) {
    try {
      const reader = new FileReader();
      reader.onload = function (ev) {
        const base64 = ev?.target?.result;
        if (!base64) return;

        const range = quill.getSelection(true) || { index: quill.getLength(), length: 0 };
        quill.insertEmbed(range.index, "image", base64, "user");
        quill.setSelection(range.index + 1, 0, "user");

        try { quill.__autoGrowApply?.(); } catch (_e) {}
        try { requestAnimationFrame(() => quill.__autoGrowApply?.()); } catch (_e) {}
      };
      reader.readAsDataURL(file);
    } catch (_e) {}
  }

  function ensureModalScrollable(modalScroll) {
    if (!modalScroll) return;
    modalScroll.style.setProperty("overflow-y", "auto", "important");
    modalScroll.style.setProperty("-webkit-overflow-scrolling", "touch", "important");
  }

  function keepCaretVisibleInScroll(quill, modalScroll) {
    try {
      if (!quill || !modalScroll) return;
      const range = quill.getSelection?.();
      if (!range) return;

      const b = quill.getBounds(range.index);
      const edRect = quill.root.getBoundingClientRect();
      const scRect = modalScroll.getBoundingClientRect();

      const caretY = edRect.top + b.top;
      const topLimit = scRect.top + 24;
      const botLimit = scRect.bottom - 24;

      if (caretY < topLimit) {
        modalScroll.scrollTop -= (topLimit - caretY);
      } else if (caretY > botLimit) {
        modalScroll.scrollTop += (caretY - botLimit);
      }
    } catch (_e) {}
  }

  function autoGrowQuill(quill, opts = {}) {
    const min = Number(opts.min ?? 220);

    const editor = quill?.root;
    if (!editor) return;

    const container = editor.closest(".ql-container");
    if (!container) return;

    function getManualMinHeight() {
      const v = parseInt(container.dataset.cmManualMinHeight || "0", 10);
      return Number.isFinite(v) ? v : 0;
    }

    function resetInternalScroll() {
      try {
        editor.scrollTop = 0;
        container.scrollTop = 0;
      } catch (_e) {}
    }

    function resolveModalScrollContainer() {
      if (quill.__cmModalScroll) return quill.__cmModalScroll;

      return (
        editor.closest(".card-modal-scroll") ||
        editor.closest("#modal-body") ||
        document.querySelector("#card-modal-root .card-modal-scroll") ||
        document.querySelector("#modal-body") ||
        null
      );
    }

    function ensureModalScroll(modalScroll) {
      if (!modalScroll) return;

      // scroll único: quem rola é o modal
      modalScroll.style.setProperty("overflow-y", "auto", "important");
      modalScroll.style.setProperty("overflow-x", "hidden", "important");
      modalScroll.style.setProperty("-webkit-overflow-scrolling", "touch", "important");

      // ❌ NÃO setar max-height aqui (CSS do modal governa isso)
      // modalScroll.style.setProperty("max-height", "80vh", "important");
    }

    function apply() {
      const modalScroll = resolveModalScrollContainer();
      ensureModalScroll(modalScroll);

      // Quill: nunca rolar internamente
      container.style.setProperty("display", "block", "important");
      container.style.setProperty("height", "auto", "important");
      container.style.setProperty("max-height", "none", "important");
      container.style.setProperty("overflow", "hidden", "important");

      editor.style.setProperty("display", "block", "important");
      editor.style.setProperty("height", "auto", "important");
      editor.style.setProperty("min-height", "0", "important");
      editor.style.setProperty("overflow", "visible", "important");

      editor.style.setProperty("box-sizing", "border-box", "important");
      editor.style.setProperty("width", "100%", "important");
      editor.style.setProperty("max-width", "none", "important");
      editor.style.setProperty("padding", "12px 14px 14px 14px", "important");

      const manualMin = getManualMinHeight();
      const needed = (editor.scrollHeight || 0) + 2;
      const target = Math.max(min, manualMin, needed);

      container.style.setProperty("height", `${Math.ceil(target)}px`, "important");

      requestAnimationFrame(() => {
        resetInternalScroll();
        requestAnimationFrame(resetInternalScroll);
      });
    }

    quill.on("text-change", () => {
      apply();
      requestAnimationFrame(apply);
      setTimeout(apply, 0);
      setTimeout(apply, 50);
    });

    quill.on("selection-change", () => {
      resetInternalScroll();
      requestAnimationFrame(resetInternalScroll);
    });

    editor.addEventListener(
      "load",
      () => {
        requestAnimationFrame(apply);
        setTimeout(apply, 0);
        setTimeout(apply, 50);
      },
      true
    );

    requestAnimationFrame(apply);
    setTimeout(apply, 0);
    setTimeout(apply, 50);

    quill.__autoGrowApply = apply;
    return apply;
  }

  function bindQuillToTextarea(textarea, boardId) {
    if (!textarea) return null;
    if (textarea.dataset.quillBound === "1") return null;
    textarea.dataset.quillBound = "1";

    const host = document.createElement("div");
    host.className = "cm-quill";
    textarea.insertAdjacentElement("afterend", host);

    textarea.style.display = "none";

    const modalScroll =
      document.querySelector("#modal-body.card-modal-scroll") ||
      document.querySelector("#modal-body") ||
      document.querySelector("#card-modal-root .card-modal-scroll");

    const quillOptions = {
      theme: "snow",
      modules: {
        toolbar: [
          [{ header: [1, 2, 3, false] }],
          ["bold", "italic", "underline", "strike"],
          [{ list: "ordered" }, { list: "bullet" }],
          ["link", "image"],
          ["clean"],
        ],
        mention: makeMentionConfig(boardId),
      },
      placeholder: textarea.getAttribute("placeholder") || "",
    };

    if (modalScroll) quillOptions.scrollingContainer = modalScroll;
    ensureModalScrollable(modalScroll);

    const quill = new Quill(host, quillOptions);
    quill.__cmModalScroll = modalScroll || null;

    window.Modal.quill._descQuill = quill;

    const initial = (textarea.value || "").trim();
    if (initial) quill.root.innerHTML = initial;

    const container = quill.root.closest(".ql-container");
    if (container) delete container.dataset.cmManualMinHeight;

    autoGrowQuill(quill, { min: 100, max: Infinity });

    quill.on("selection-change", () => {
      keepCaretVisibleInScroll(quill, quill.__cmModalScroll);
      requestAnimationFrame(() => keepCaretVisibleInScroll(quill, quill.__cmModalScroll));
    });

    quill.on("text-change", () => {
      textarea.value = quill.root.innerHTML;
      try { textarea.dispatchEvent(new Event("input", { bubbles: true })); } catch (_e) {}

      keepCaretVisibleInScroll(quill, quill.__cmModalScroll);
      requestAnimationFrame(() => keepCaretVisibleInScroll(quill, quill.__cmModalScroll));
    });

    const toolbar = quill.getModule("toolbar");
    if (toolbar) {
      toolbar.addHandler("image", () => {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*";
        input.onchange = () => {
          const file = input.files?.[0];
          if (file) insertBase64ImageIntoQuill(quill, file);
        };
        input.click();
      });
    }

    quill.root.addEventListener("paste", (e) => {
      try {
        const cd = e.clipboardData;
        const items = cd?.items ? Array.from(cd.items) : [];
        const imgItem = items.find((it) => (it.type || "").startsWith("image/"));
        if (!imgItem) return;

        const file = imgItem.getAsFile?.();
        if (!file) return;

        e.preventDefault();
        insertBase64ImageIntoQuill(quill, file);
      } catch (_e) {}
    });

    return quill;
  }

  function bindQuillToDiv(div, hiddenInput, boardId) {
    if (!div || !hiddenInput) return null;
    if (div.dataset.quillBound === "1") return null;
    div.dataset.quillBound = "1";

    const modalScroll =
      document.querySelector("#modal-body.card-modal-scroll") ||
      document.querySelector("#modal-body") ||
      document.querySelector("#card-modal-root .card-modal-scroll");

    const quillOptions = {
      theme: "snow",
      modules: {
        toolbar: [
          [{ header: [1, 2, 3, false] }],
          ["bold", "italic", "underline", "strike"],
          [{ list: "ordered" }, { list: "bullet" }],
          ["link", "image"],
          ["clean"],
        ],
        mention: makeMentionConfig(boardId),
      },
      placeholder: div.getAttribute("data-placeholder") || "",
    };

    if (modalScroll) quillOptions.scrollingContainer = modalScroll;
    ensureModalScrollable(modalScroll);

    const quill = new Quill(div, quillOptions);
    quill.__cmModalScroll = modalScroll || null;

    window.Modal.quill._descQuill = quill;

    const initial = (hiddenInput.value || "").trim();
    if (initial) quill.root.innerHTML = initial;

    const container = quill.root.closest(".ql-container");
    if (container) delete container.dataset.cmManualMinHeight;
    autoGrowQuill(quill, { min: 100, max: Infinity });

    quill.on("text-change", () => {
      hiddenInput.value = quill.root.innerHTML;
      try { hiddenInput.dispatchEvent(new Event("input", { bubbles: true })); } catch (_e) {}

      keepCaretVisibleInScroll(quill, quill.__cmModalScroll);
      requestAnimationFrame(() => keepCaretVisibleInScroll(quill, quill.__cmModalScroll));
    });

    quill.on("selection-change", () => {
      keepCaretVisibleInScroll(quill, quill.__cmModalScroll);
      requestAnimationFrame(() => keepCaretVisibleInScroll(quill, quill.__cmModalScroll));
    });

    const toolbar = quill.getModule("toolbar");
    if (toolbar) {
      toolbar.addHandler("image", () => {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*";
        input.onchange = () => {
          const file = input.files?.[0];
          if (file) insertBase64ImageIntoQuill(quill, file);
        };
        input.click();
      });
    }

    quill.root.addEventListener("paste", (e) => {
      try {
        const cd = e.clipboardData;
        const items = cd?.items ? Array.from(cd.items) : [];
        const imgItem = items.find((it) => (it.type || "").startsWith("image/"));
        if (!imgItem) return;

        const file = imgItem.getAsFile?.();
        if (!file) return;

        e.preventDefault();
        insertBase64ImageIntoQuill(quill, file);
      } catch (_e) {}
    });

    return quill;
  }

  window.Modal.quill.init = function () {
    const boardId = getBoardIdFromUrl();

    const descDiv = document.getElementById("quill-editor");
    const descHidden = document.getElementById("description-input");
    if (descDiv && descHidden) {
      bindQuillToDiv(descDiv, descHidden, boardId);
      return;
    }

    const descTa =
      document.querySelector('#cm-root textarea[name="description"]') ||
      document.querySelector('textarea[name="description"]');

    if (descTa) bindQuillToTextarea(descTa, boardId);
  };

  document.body.addEventListener("htmx:afterSwap", function (e) {
    const target = e?.target;
    if (!target) return;

    if (target.id === "modal-body" || target.closest?.("#modal-body")) {
      try { window.Modal?.quill?.init?.(); } catch (_e) {}
    }
  });

  (function installQuillImageOpenInNewTab() {
    if (window.__cmQuillImgOpenInstalled) return;
    window.__cmQuillImgOpenInstalled = true;

    document.addEventListener(
      "click",
      function (e) {
        const img = e.target?.closest?.(
          ".ql-editor img, .cm-quill img, #cm-activity-editor .ql-editor img, .cm-activity-content img"
        );
        if (!img) return;

        const src = img.getAttribute("src");
        if (!src) return;

        e.preventDefault();
        e.stopPropagation();
        window.open(src, "_blank", "noopener,noreferrer");
      },
      true
    );
  })();

 


// ============================================================
// Quill Descrição — Resize Handle (MVP) — COMPLETO (sem erro)
// - grava cmManualMinHeight no onDown e no onMove
// - garante height explícito antes de arrastar
// ============================================================
(function installQuillResizeHandle() {
  if (window.__cmQuillResizeInstalled) return;
  window.__cmQuillResizeInstalled = true;

  function ensureHandle() {
    const host =
      document.querySelector("#modal-body #quill-editor") ||
      document.querySelector("#modal-body .cm-quill") ||
      document.querySelector("#modal-body textarea[name='description']")?.nextElementSibling; // host criado

    if (!host) return;

    const container = host.querySelector(".ql-container");
    if (!container) return;

    if (container.querySelector(".cm-quill-resize-handle")) return;

    // altura inicial (SEM marcar manual)
    const h0 = container.getBoundingClientRect().height;
    if (!h0 || h0 < 180) {
      container.style.setProperty("height", "240px", "important");
      // NÃO setar dataset aqui
      delete container.dataset.cmManualMinHeight;
    }

    const handle = document.createElement("div");
    handle.className = "cm-quill-resize-handle";
    handle.setAttribute("title", "Arraste para aumentar/reduzir");
    handle.setAttribute("aria-label", "Redimensionar descrição");

    container.style.position = "relative";
    container.appendChild(handle);

    let startY = 0;
    let startH = 0;
    let dragging = false;

    function getY(e) {
      return (e.touches ? e.touches[0].clientY : e.clientY);
    }

    function onDown(e) {
      dragging = true;
      startY = getY(e);
      startH = container.getBoundingClientRect().height;

      // garante height explícito e marca manual SOMENTE aqui
      container.style.setProperty("height", `${startH}px`, "important");
      container.dataset.cmManualMinHeight = String(Math.round(startH));

      e.preventDefault();
      e.stopPropagation();

      document.addEventListener("mousemove", onMove, true);
      document.addEventListener("mouseup", onUp, true);
      document.addEventListener("touchmove", onMove, { passive: false, capture: true });
      document.addEventListener("touchend", onUp, true);
    }

    function onMove(e) {
      if (!dragging) return;

      const y = getY(e);
      const dy = y - startY;

      const newH = Math.max(180, Math.min(700, startH + dy));
      container.style.setProperty("height", `${newH}px`, "important");
      container.dataset.cmManualMinHeight = String(Math.round(newH));

      e.preventDefault();
      e.stopPropagation();
    }

    function onUp(e) {
      dragging = false;

      document.removeEventListener("mousemove", onMove, true);
      document.removeEventListener("mouseup", onUp, true);
      document.removeEventListener("touchmove", onMove, true);
      document.removeEventListener("touchend", onUp, true);

      e?.preventDefault?.();
      e?.stopPropagation?.();

      // força auto-grow recalcular depois do drag
      try { requestAnimationFrame(() => window.Modal?.quill?._descQuill?.__autoGrowApply?.()); } catch (_e) {}
    }

    handle.addEventListener("mousedown", onDown, true);
    handle.addEventListener("touchstart", onDown, { passive: false, capture: true });
  }

  document.addEventListener("DOMContentLoaded", () => setTimeout(ensureHandle, 0));
  document.body.addEventListener("htmx:afterSwap", () => setTimeout(ensureHandle, 0));
  document.body.addEventListener("htmx:afterSettle", () => setTimeout(ensureHandle, 0));

  setTimeout(ensureHandle, 0);
})();






// ============================================================
// Quill Descrição — Resize Grip (MVP robusto, fora do overflow)
// ============================================================
(function installDescResizeGripFloating() {
  if (window.__cmDescGripInstalled) return;
  window.__cmDescGripInstalled = true;

  let grip = null;
  let rafId = 0;

  function getDescContainer() {
    const root = document.getElementById("cm-root");
    if (!root) return null;

    // só quando a aba descrição estiver ativa
    const active = root.getAttribute("data-cm-active") || root.dataset.cmActive;
    if (active && active !== "desc") return null;

    const host =
      document.querySelector("#modal-body #quill-editor") ||
      document.querySelector("#modal-body .cm-quill") ||
      document.querySelector("#modal-body textarea[name='description']")?.nextElementSibling; // host criado


    if (!host) return null;

    const container = host.querySelector(".ql-container");
    return container || null;
  }

  function ensureGrip() {
    if (grip && document.contains(grip)) return grip;

    grip = document.createElement("div");
    grip.className = "cm-desc-resize-grip";
    grip.setAttribute("title", "Arraste para aumentar/reduzir");
    grip.setAttribute("aria-label", "Redimensionar descrição");
    document.body.appendChild(grip);

    bindDrag(grip);
    return grip;
  }

  function clamp(n, min, max) {
    return Math.max(min, Math.min(max, n));
  }

  function positionGrip() {
    const container = getDescContainer();
    const g = ensureGrip();

    if (!container) {
      g.style.display = "none";
      return;
    }

    const r = container.getBoundingClientRect();
    // posiciona no canto inferior direito do container
    const left = r.right - 30;
    const top  = r.bottom - 30;

    g.style.left = `${left}px`;
    g.style.top = `${top}px`;
    g.style.display = "block";
  }

  function schedulePosition() {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(positionGrip);
  }

  function bindDrag(g) {
    let dragging = false;
    let startY = 0;
    let startH = 0;
    let container = null;

    function onDown(e) {
      container = getDescContainer();
      if (!container) return;

      dragging = true;
      startY = (e.touches ? e.touches[0].clientY : e.clientY);
      startH = container.getBoundingClientRect().height;

      // garante height explícito (senão fica “auto” e dá efeito doido)
      container.style.setProperty("height", `${startH}px`, "important");


      e.preventDefault();
      e.stopPropagation();

      document.addEventListener("mousemove", onMove, true);
      document.addEventListener("mouseup", onUp, true);
      document.addEventListener("touchmove", onMove, { passive: false, capture: true });
      document.addEventListener("touchend", onUp, true);
    }

    function onMove(e) {
      if (!dragging || !container) return;

      const y = (e.touches ? e.touches[0].clientY : e.clientY);
      const dy = y - startY;

      const vh = window.innerHeight || 800;
      const maxH = clamp(Math.floor(vh * 0.60), 260, 900); // alinhado com seu max-height 60vh
      const newH = clamp(startH + dy, 180, maxH);

      container.style.setProperty("height", `${newH}px`, "important");


      e.preventDefault();
      e.stopPropagation();

      schedulePosition();
    }

    function onUp(e) {
      dragging = false;

      document.removeEventListener("mousemove", onMove, true);
      document.removeEventListener("mouseup", onUp, true);
      document.removeEventListener("touchmove", onMove, true);
      document.removeEventListener("touchend", onUp, true);

      e?.preventDefault?.();
      e?.stopPropagation?.();

      schedulePosition();
    }

    g.addEventListener("mousedown", onDown, true);
    g.addEventListener("touchstart", onDown, { passive: false, capture: true });
  }

  // reposiciona em tudo que mexe no layout do modal
  function bindRepositionTriggers() {
    // swaps do modal
    document.body.addEventListener("htmx:afterSwap", schedulePosition);
    document.body.addEventListener("htmx:afterSettle", schedulePosition);

    // troca de abas
    const root = document.getElementById("cm-root");
    root?.addEventListener("cm:tabchange", schedulePosition);

    // scroll dentro do modal (seu modal tem card-modal-scroll)
    document.addEventListener("scroll", schedulePosition, true);
    window.addEventListener("resize", schedulePosition);

    // quando fechar modal, some com o grip
    document.addEventListener("modal:closed", function () {
      if (grip) grip.style.display = "none";
    });
  }

  bindRepositionTriggers();

  // primeira tentativa
  setTimeout(schedulePosition, 0);
})();


})();
//END modal.quill.js
