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
    quill.on("text-change", () => {
      textarea.value = quill.root.innerHTML;
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

  window.Modal.quill.init = function () {
    const boardId = getBoardIdFromUrl();

    // 1) Descrição
    const descTextarea = document.querySelector('#cm-main-form textarea[name="description"]');
    bindQuillToTextarea(descTextarea, boardId);

    // 2) Atividade (novo comentário)
    const actTextarea = document.querySelector('form[hx-post*="add_activity"] textarea[name="content"]');
    bindQuillToTextarea(actTextarea, boardId);
  };
})();
//END modal.quill.js
