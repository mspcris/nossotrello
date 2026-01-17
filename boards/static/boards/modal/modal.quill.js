// boards/static/boards/modal/modal.quill.js
(() => {
  if (!window.Modal) return;

  window.Modal.quill = window.Modal.quill || {};

  function getBoardIdFromUrl() {
    // /board/<id>/...
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

  // avatar
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

  // meta
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

  return root; // 🔑 HTMLElement
}

  function escapeHtml(s) {
    return String(s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
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
      };
      reader.readAsDataURL(file);
    } catch (_e) {}
  }

  function bindQuillToTextarea(textarea, boardId) {
    if (!textarea) return null;
    if (textarea.dataset.quillBound === "1") return null;
    textarea.dataset.quillBound = "1";

    // cria container do editor logo após o textarea
    const host = document.createElement("div");
    host.className = "cm-quill";
    textarea.insertAdjacentElement("afterend", host);

    // esconde textarea (mantém no form)
    textarea.style.display = "none";

    const quill = new Quill(host, {
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
    });

    // conteúdo inicial
    const initial = (textarea.value || "").trim();
    if (initial) quill.root.innerHTML = initial;

    // manter textarea atualizado
    // manter textarea atualizado + disparar input (dirty tracking / floatbar)
    quill.on("text-change", () => {
      textarea.value = quill.root.innerHTML;

      // garante que listeners que dependem de "input" enxerguem a mudança
      try {
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
      } catch (_e) {}
    });


    // upload image base64 quando inserir via toolbar
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

    // se colar imagem dentro do editor, mantém o comportamento antigo (base64 no conteúdo)
    quill.root.addEventListener("paste", (e) => {
      try {
        const cd = e.clipboardData;
        const items = cd?.items ? Array.from(cd.items) : [];
        const imgItem = items.find((it) => (it.type || "").startsWith("image/"));
        if (!imgItem) return;

        const file = imgItem.getAsFile?.();
        if (!file) return;

        // deixa o texto normal e intercepta imagem
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

  const quill = new Quill(div, {
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
    placeholder: div.getAttribute("data-placeholder") || "Escreva uma atualização...",
  });

  // inicial (se existir)
  const initial = (hiddenInput.value || "").trim();
  if (initial) quill.root.innerHTML = initial;

  // sync no hidden
  quill.on("text-change", () => {
    hiddenInput.value = quill.root.innerHTML;
    try { hiddenInput.dispatchEvent(new Event("input", { bubbles: true })); } catch (_e) {}
  });

  // toolbar image -> base64
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

  // paste image -> base64
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

  // botão "Limpar" do seu template
  window.resetActivityQuill = function () {
    try { quill.setText(""); } catch (_e) {}
    hiddenInput.value = "";
  };

  return quill;
}

window.Modal.quill.init = function () {
  const boardId = getBoardIdFromUrl();

  // 1) Descrição (textarea -> quill)
  const descTextarea = document.querySelector('#cm-main-form textarea[name="description"]');
  bindQuillToTextarea(descTextarea, boardId);

  // 2) Atividade: novo padrão (div + hidden)
  //mantida somente em modal.activity_quill.js

};

  // ============================================================
  // IMG CLICK: abre qualquer imagem do Quill em nova aba
  // (Descrição + Atividade + conteúdo renderizado)
  // ============================================================
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
  // Quill Descrição — Resize Handle (MVP)
  // ============================================================
  (function installQuillResizeHandle() {
    if (window.__cmQuillResizeInstalled) return;
    window.__cmQuillResizeInstalled = true;

    function ensureHandle() {
      const host = document.querySelector("#modal-body .cm-quill");
      if (!host) return;

      // quill container que vamos redimensionar
      const container = host.querySelector(".ql-container");
      if (!container) return;

      // já tem handle?
      if (container.querySelector(".cm-quill-resize-handle")) return;

      // altura inicial razoável (se não tiver)
      const h0 = container.getBoundingClientRect().height;
      if (!h0 || h0 < 180) container.style.height = "240px";

      const handle = document.createElement("div");
      handle.className = "cm-quill-resize-handle";
      handle.setAttribute("title", "Arraste para aumentar/reduzir");
      handle.setAttribute("aria-label", "Redimensionar descrição");

      container.style.position = "relative"; // ancora o handle
      container.appendChild(handle);


      let startY = 0;
      let startH = 0;
      let dragging = false;

      function onDown(e) {
        dragging = true;
        startY = (e.touches ? e.touches[0].clientY : e.clientY);
        startH = container.getBoundingClientRect().height;

        e.preventDefault();
        e.stopPropagation();

        document.addEventListener("mousemove", onMove, true);
        document.addEventListener("mouseup", onUp, true);
        document.addEventListener("touchmove", onMove, { passive: false, capture: true });
        document.addEventListener("touchend", onUp, true);
      }

      function onMove(e) {
        if (!dragging) return;

        const y = (e.touches ? e.touches[0].clientY : e.clientY);
        const dy = y - startY;

        const newH = Math.max(180, Math.min(700, startH + dy)); // limites MVP
        container.style.height = `${newH}px`;

        e.preventDefault();
        e.stopPropagation();
      }

      function onUp(e) {
        dragging = false;

        document.removeEventListener("mousemove", onMove, true);
        document.removeEventListener("mouseup", onUp, true);
        document.removeEventListener("touchmove", onMove, true);
        document.removeEventListener("touchend", onUp, true);

        e.preventDefault?.();
        e.stopPropagation?.();
      }

      handle.addEventListener("mousedown", onDown, true);
      handle.addEventListener("touchstart", onDown, { passive: false, capture: true });
    }

    // tenta quando o modal carrega e após swaps
    document.addEventListener("DOMContentLoaded", () => setTimeout(ensureHandle, 0));
    document.body.addEventListener("htmx:afterSwap", () => setTimeout(ensureHandle, 0));
    document.body.addEventListener("htmx:afterSettle", () => setTimeout(ensureHandle, 0));
    document.addEventListener("modal:closed", () => {}); // noop, mas mantém padrão

    // tentativa inicial imediata (caso já esteja aberto)
    setTimeout(ensureHandle, 0);
  })();



})();
//END modal.quill.js
