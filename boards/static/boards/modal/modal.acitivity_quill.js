// ============================================================
// Quill da aba atividade
// ============================================================
(function () {
  const STATE_KEY = "__cmActivityQuill";

  function getRoot() {
    return document.getElementById("cm-root");
  }

  function getCardId() {
    const root = getRoot();
    return root?.getAttribute("data-card-id") || root?.dataset?.cardId || "";
  }

  function getCSRF() {
    return document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
  }

  function showActivityError(msg) {
    const box = document.getElementById("activity-error");
    if (!box) return;
    box.textContent = msg || "";
    box.classList.toggle("hidden", !msg);
  }

  function clearActivityError() {
    showActivityError("");
  }

  // ===== Mentions (mesmo padrão do modal.quill.js) =====
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

  function ensureQuill() {
    if (window[STATE_KEY] || typeof Quill === "undefined") return;

    const el = document.getElementById("cm-activity-editor");
    if (!el) return;

    const boardId = getBoardIdFromUrl();

    const quill = new Quill(el, {
      theme: "snow",
      placeholder: "Escreva aqui...",
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
    });

    window[STATE_KEY] = quill;

    // ✅ COLAR IMAGEM: usa endpoint REAL e trata HTML
    quill.root.addEventListener("paste", async function (e) {
      try {
        const items = e.clipboardData?.items || [];
        let file = null;

        for (const item of items) {
          if (item.type && item.type.startsWith("image/")) {
            file = item.getAsFile();
            break;
          }
        }

        if (!file) return; // texto segue normal

        e.preventDefault();
        clearActivityError();

        const cardId = getCardId();
        if (!cardId) throw new Error("cardId ausente.");

        const uploadUrl = `/card/${cardId}/attachments/add/`;

        const form = new FormData();
        form.append("file", file);
        form.append("description", "Imagem colada na atividade");

        const res = await fetch(uploadUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "X-CSRFToken": getCSRF(),
            "X-Requested-With": "XMLHttpRequest",
          },
          body: form,
        });

        if (!res.ok) {
          const t = await res.text().catch(() => "");
          throw new Error(t || `Upload falhou (${res.status}).`);
        }

        const html = await res.text();

        // 1) mantém o anexo na aba Anexos
        const list = document.getElementById("attachments-list");
        if (list) list.insertAdjacentHTML("beforeend", html);

        // 2) extrai URL do HTML (href ou src)
        const tmp = document.createElement("div");
        tmp.innerHTML = html;

        const a = tmp.querySelector("a[href]");
        const img = tmp.querySelector("img[src]");
        const fileUrl =
          (img && img.getAttribute("src")) ||
          (a && a.getAttribute("href")) ||
          "";

        // 3) insere no quill (imagem inline se der, senão link)
        const range = quill.getSelection(true) || { index: quill.getLength() };

        if (fileUrl) {
          quill.insertEmbed(range.index, "image", fileUrl);
          quill.insertText(range.index + 1, "\n");
          quill.setSelection(range.index + 2);
        } else {
          quill.insertText(range.index, "[anexo criado]\n");
          quill.setSelection(range.index + 14);
        }
      } catch (err) {
        showActivityError(err?.message || "Erro ao colar imagem na atividade.");
      }
    });
  }

  function syncToHidden() {
    const quill = window[STATE_KEY];
    if (!quill) return "";
    const html = (quill.root.innerHTML || "").trim();
    const hidden = document.getElementById("cm-activity-content");
    if (hidden) hidden.value = html;
    return html;
  }

  function resetEditor() {
    const quill = window[STATE_KEY];
    if (!quill) return;
    quill.setText("");
    const hidden = document.getElementById("cm-activity-content");
    if (hidden) hidden.value = "";
  }

  // expõe para o botão "Limpar" do template
  window.resetActivityQuill = resetEditor;

  function bindActivityForm() {
    const form = document.querySelector('section[data-cm-panel="ativ"] form');
    if (!form) return;

    if (form.dataset.cmBound === "1") return;
    form.dataset.cmBound = "1";

    form.addEventListener("htmx:configRequest", function (evt) {
      ensureQuill();
      clearActivityError();

      const html = syncToHidden();
      if (evt.detail && evt.detail.parameters) {
        evt.detail.parameters["content"] = html;
      }
    });

    form.addEventListener("htmx:afterRequest", function (evt) {
      if (evt.detail?.successful === true) {
        resetEditor();
        clearActivityError();
      }
    });
  }

  function initActivityModule() {
    ensureQuill();
    bindActivityForm();
  }

  // ao abrir aba atividade
  getRoot()?.addEventListener("cm:tabchange", function (e) {
    if (e.detail?.tab === "ativ") {
      setTimeout(initActivityModule, 0);
      setTimeout(initActivityModule, 50);
    }
  });

  // fallback se abriu direto
  if (getRoot()?.getAttribute("data-cm-active") === "ativ") {
    setTimeout(initActivityModule, 0);
    setTimeout(initActivityModule, 50);
  }

  // rebind pós swap do HTMX (apenas modal principal) + reaplica cores
  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (!e.target || e.target.id !== "modal-body") return;

    const cmRoot = document.getElementById("cm-root");
    if (!cmRoot) return;

    if (typeof window.applySavedTagColorsToModal === "function") {
      window.applySavedTagColorsToModal(cmRoot);
    }

    if (typeof window.applySavedTermColorsToModal === "function") {
      window.applySavedTermColorsToModal(cmRoot);
    }

    // garante rebind do form após swap
    setTimeout(bindActivityForm, 0);
  });
})();
