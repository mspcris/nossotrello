// ============================================================
// /boards/static/modal/modal.acitivity_quill.js
// ============================================================
(function () {
  const STATE_KEY = "__cmActivityQuill";
  const STATE_EL_KEY = "__cmActivityQuillEl";

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

  // ===== Mentions =====
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

  // ============================================================
  // UI: Toggle do composer "Nova Atividade"
  // ============================================================
  function getComposerEl() {
    return document.getElementById("cm-activity-composer");
  }

  function getGapEl() {
    return document.getElementById("cm-activity-gap");
  }

  function getToggleBtn() {
    return document.getElementById("cm-activity-toggle");
  }

  function getTabFeedBtn() {
    return document.getElementById("cm-activity-tab-feed");
  }

  function getTabNewBtn() {
    return document.getElementById("cm-activity-tab-new");
  }

  function setActivityTab(which /* 'feed' | 'new' */) {
    const feedBtn = getTabFeedBtn();
    const newBtn = getTabNewBtn();
    const composer = getComposerEl();

    const isNew = which === "new";

    if (feedBtn) {
      feedBtn.classList.toggle("is-active", !isNew);
      feedBtn.setAttribute("aria-selected", (!isNew).toString());
    }
    if (newBtn) {
      newBtn.classList.toggle("is-active", isNew);
      newBtn.setAttribute("aria-selected", (isNew).toString());
    }

    if (composer) composer.classList.toggle("is-hidden", !isNew);

    const gap = getGapEl();
    if (gap) gap.classList.toggle("is-hidden", !isNew);
  }

  function isComposerOpen() {
    const el = getComposerEl();
    return !!(el && !el.classList.contains("is-hidden"));
  }

  function openComposer() {
    const composer = getComposerEl();
    const gap = getGapEl();
    const btn = getToggleBtn();
    if (!composer) return;

    composer.classList.remove("is-hidden");
    if (gap) gap.classList.remove("is-hidden");
    if (btn) btn.setAttribute("aria-expanded", "true");

    ensureQuill();

    try {
      const q = window[STATE_KEY];
      if (q && typeof q.focus === "function") q.focus();
    } catch (_e) {}
  }

  function closeComposer() {
    const composer = getComposerEl();
    const gap = getGapEl();
    const btn = getToggleBtn();
    if (!composer) return;

    composer.classList.add("is-hidden");
    if (gap) gap.classList.add("is-hidden");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  document.addEventListener(
    "click",
    function (e) {
      const feedBtn = e.target?.closest?.("#cm-activity-tab-feed");
      if (feedBtn) {
        setActivityTab("feed");
        closeComposer();
        return;
      }

      const newBtn = e.target?.closest?.("#cm-activity-tab-new");
      if (newBtn) {
        setActivityTab("new");
        openComposer();
        return;
      }

      const legacyToggle = e.target?.closest?.("#cm-activity-toggle");
      if (legacyToggle) {
        if (isComposerOpen()) {
          setActivityTab("feed");
          closeComposer();
        } else {
          setActivityTab("new");
          openComposer();
        }
      }
    },
    true
  );

  // ============================================================
  // Detectar se a aba ATIVIDADE está realmente ativa no DOM
  // ============================================================
  function isActivityTabActive() {
    const root = getRoot();
    if (!root) return false;

    const panel = root.querySelector('section[data-cm-panel="ativ"]');
    if (panel && panel.classList.contains("is-active")) return true;

    const btn = root.querySelector('.cm-tabbtn[data-cm-tab="ativ"]');
    if (btn && btn.classList.contains("is-active")) return true;

    if (root.getAttribute("data-cm-active") === "ativ") return true;

    return !!document.getElementById("cm-activity-editor");
  }

  function destroyQuillIfStale(elNow) {
    const q = window[STATE_KEY];
    const elPrev = window[STATE_EL_KEY];
    if (!q) return;

    const prevGone = elPrev && !document.contains(elPrev);
    const changed = elNow && elPrev && elNow !== elPrev;

    if (prevGone || changed) {
      try {
        const toolbar = elPrev?.previousSibling;
        if (toolbar && toolbar.classList && toolbar.classList.contains("ql-toolbar")) {
          toolbar.remove();
        }
      } catch (_e) {}

      try {
        if (elPrev) elPrev.innerHTML = "";
      } catch (_e) {}

      window[STATE_KEY] = null;
      window[STATE_EL_KEY] = null;
    }
  }

  // ============================================================
  // AUTO-GROW
  // ============================================================
  function getModalScrollContainer() {
    return (
      document.querySelector("#modal-body.card-modal-scroll") ||
      document.querySelector("#modal-body") ||
      document.querySelector("#card-modal-root .card-modal-scroll")
    );
  }

  function autoGrowQuill(quill, opts = {}) {
    const min = Number(opts.min ?? 140);
    const max = Number(opts.max ?? 3000);

    const editor = quill?.root;
    if (!editor) return;

    const container = editor.closest(".ql-container");
    if (!container) return;

    const clamp = (n, a, b) => Math.max(a, Math.min(b, n));

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

    function apply() {
      container.style.setProperty("display", "block", "important");
      container.style.setProperty("max-height", "none", "important");
      container.style.setProperty("overflow", "visible", "important");

      editor.style.setProperty("display", "block", "important");
      editor.style.setProperty("height", "auto", "important");
      editor.style.setProperty("min-height", "0", "important");
      editor.style.setProperty("overflow", "visible", "important");
      editor.style.setProperty("padding-bottom", "14px", "important");

      const bottomPad = 14;
      const needed = (editor.scrollHeight || 0) + bottomPad;

      const manualMin = getManualMinHeight();
      const target = clamp(Math.max(min, manualMin, needed), min, max);

      container.style.setProperty("height", `${target}px`, "important");

      requestAnimationFrame(() => {
        resetInternalScroll();
        requestAnimationFrame(resetInternalScroll);
      });

      try {
        window.dispatchEvent(new Event("resize"));
      } catch (_e) {}
    }

    quill.on("text-change", () => {
      apply();
      requestAnimationFrame(apply);
    });

    quill.on("selection-change", () => {
      resetInternalScroll();
      requestAnimationFrame(resetInternalScroll);
    });

    editor.addEventListener("load", () => requestAnimationFrame(apply), true);

    requestAnimationFrame(apply);
    setTimeout(apply, 0);

    quill.__autoGrowApply = apply;
    return apply;
  }

  // ============================================================
  // Pós-submit: remove "Nenhuma atividade ainda" e força refresh do painel
  // ============================================================
  function removeActivityEmptyState() {
    const host =
      document.getElementById("cm-activity-panel") ||
      document.getElementById("activity-panel-wrapper") ||
      document;

    const nodes = host.querySelectorAll("*");
    for (const n of nodes) {
      const t = (n.textContent || "").trim();
      if (t === "Nenhuma atividade ainda.") {
        n.remove();
        break;
      }
    }
  }

  function applyPostSuccessActivityUI(responseText) {
    removeActivityEmptyState();

    const raw = String(responseText || "").trim();
    if (!raw) return;

    const doc = new DOMParser().parseFromString(raw, "text/html");
    doc.querySelectorAll("[hx-swap-oob]").forEach((n) => n.remove());

    const newPanel = doc.getElementById("card-activity-panel");
    if (!newPanel) return;

    const panelNow = document.getElementById("card-activity-panel");
    if (!panelNow) return;

    panelNow.outerHTML = newPanel.outerHTML;

    try {
      cleanupActivityLogSpacing();
    } catch (_e) {}
    setTimeout(() => {
      try {
        cleanupActivityLogSpacing();
      } catch (_e) {}
    }, 60);

    try {
      updateActivityFeedCount();
    } catch (_e) {}
    setTimeout(() => {
      try {
        updateActivityFeedCount();
      } catch (_e) {}
    }, 80);

    // ✅ rebinda e reaplica filtro após trocar o HTML do painel
    try {
      bindFeedFilterUI();
    } catch (_e) {}
    try {
      applyFeedFilter();
    } catch (_e) {}
  }

  function updateActivityFeedCount() {
    try {
      const badge = document.getElementById("cm-activity-feed-count");
      const host = document.getElementById("cm-activity-panel");
      if (!badge || !host) return;

      let items = host.querySelectorAll("[data-activity-id]");
      if (!items || !items.length) items = host.querySelectorAll(".activity-item");
      if (!items || !items.length) items = host.querySelectorAll(".cm-activity-item");
      if (!items || !items.length) items = host.querySelectorAll("article");
      if (!items || !items.length) items = host.querySelectorAll("li");

      let n = items ? items.length : 0;

      const txt = (host.textContent || "").trim();
      if (txt === "Nenhuma atividade ainda.") n = 0;

      badge.textContent = String(n);
      badge.classList.toggle("hidden", n <= 0);
    } catch (_e) {}
  }

  // ============================================================
  // FEED FILTER (Comentários / Arquivos / Sistema / Tudo)
  // ============================================================
  function getFeedEl() {
    return document.getElementById("cm-feed");
  }

  function applyFeedFilter() {
    const sel = document.getElementById("cm-feed-filter");
    const q = document.getElementById("cm-feed-q");
    const feed = getFeedEl();
    if (!sel || !feed) return;

    const filter = (sel.value || "comments").toLowerCase();
    const term = (q?.value || "").trim().toLowerCase();

    const items = feed.querySelectorAll(".cm-feed-item");
    items.forEach((it) => {
      const type = (it.getAttribute("data-type") || "").trim().toLowerCase();
      const text = (it.getAttribute("data-text") || "").toLowerCase();

      const okType = filter === "all" || type === filter;
      const okText = !term || text.includes(term);

      it.classList.toggle("is-hidden", !(okType && okText));
    });

    const days = feed.querySelectorAll(".cm-feed-dayhdr");
    days.forEach((hdr) => {
      let node = hdr.nextElementSibling;
      let hasVisible = false;
      while (node && !node.classList.contains("cm-feed-dayhdr")) {
        if (node.classList.contains("cm-feed-item") && !node.classList.contains("is-hidden")) {
          hasVisible = true;
          break;
        }
        node = node.nextElementSibling;
      }
      hdr.classList.toggle("is-hidden", !hasVisible);
    });
  }

  function bindFeedFilterUI() {
    const sel = document.getElementById("cm-feed-filter");
    const q = document.getElementById("cm-feed-q");

    if (sel && sel.dataset.cmBound !== "1") {
      sel.dataset.cmBound = "1";
      sel.addEventListener("change", applyFeedFilter);
    }
    if (q && q.dataset.cmBound !== "1") {
      q.dataset.cmBound = "1";
      q.addEventListener("input", applyFeedFilter);
    }
  }

  function cleanupActivityLogSpacing() {
    try {
      const wrapper =
        document.getElementById("activity-panel-wrapper") ||
        document.querySelector("#cm-activity-panel") ||
        document.querySelector("#activity-panel-wrapper");

      if (!wrapper) return;

      const contentBlocks = wrapper.querySelectorAll(".activity-content, .cm-activity-content");
      if (!contentBlocks || !contentBlocks.length) return;

      const normalizeHtml = (html) =>
        String(html || "")
          .replace(/\u00A0/g, " ")
          .replace(/&nbsp;/gi, " ")
          .replace(/\s+/g, "")
          .toLowerCase();

      const hasMedia = (el) =>
        !!el.querySelector("img, video, audio, iframe, object, embed, table, ul, ol, blockquote");

      const isEmptyNode = (node) => {
        if (!node) return true;
        if (hasMedia(node)) return false;

        const tmp = node.cloneNode(true);

        tmp
          .querySelectorAll("span.ql-ui, span[data-ql-ui], span[contenteditable='false']")
          .forEach((s) => s.remove());

        tmp.querySelectorAll("br").forEach((b) => b.remove());

        const txt = (tmp.textContent || "").replace(/\u00A0/g, " ").trim();
        const html = normalizeHtml(tmp.innerHTML);

        if (!txt && (!html || html.replace(/<[^>]+>/g, "") === "")) return true;
        return false;
      };

      contentBlocks.forEach((block) => {
        Array.from(block.querySelectorAll("p, div")).forEach((el) => {
          if (isEmptyNode(el)) el.remove();
        });

        const isIgnorableText = (n) => n.nodeType === 3 && (n.textContent || "").trim() === "";
        const isBr = (n) => n.nodeType === 1 && n.tagName === "BR";

        while (block.firstChild && (isIgnorableText(block.firstChild) || isBr(block.firstChild))) {
          block.firstChild.remove();
        }
        while (block.lastChild && (isIgnorableText(block.lastChild) || isBr(block.lastChild))) {
          block.lastChild.remove();
        }
      });
    } catch (_e) {}
  }

  // ============================================================
  // REPLY (Responder)
  // ============================================================
  function ensureReplyFields(form) {
    if (!form) return { input: null, label: null };

    let input = document.getElementById("cm-activity-reply-to");
    if (!input) {
      input = document.createElement("input");
      input.type = "hidden";
      input.name = "reply_to";
      input.id = "cm-activity-reply-to";
      input.value = "";
      form.appendChild(input);
    }

    let label = document.getElementById("cm-activity-reply-label");
    if (!label) {
      label = document.createElement("div");
      label.id = "cm-activity-reply-label";
      label.className = "hidden text-xs text-gray-600 mb-2";
      const composer = document.getElementById("cm-activity-composer") || form;
      composer.insertBefore(label, composer.firstChild);
    }

    return { input, label };
  }

  function clearReplyContext() {
    const form =
      document.getElementById("cm-activity-form") ||
      document.querySelector('section[data-cm-panel="ativ"] form');

    if (!form) return;

    const { input, label } = ensureReplyFields(form);
    if (input) input.value = "";
    if (label) {
      label.textContent = "";
      label.classList.add("hidden");
    }
  }

  document.addEventListener(
    "click",
    function (e) {
      const btn = e.target?.closest?.(".cm-activity-reply-btn");
      if (!btn) return;

      const replyTo = (btn.getAttribute("data-reply-to") || "").trim();
      const replyUser = (btn.getAttribute("data-reply-user") || "").trim();

      const form =
        document.getElementById("cm-activity-form") ||
        document.querySelector('section[data-cm-panel="ativ"] form');

      if (!form) return;

      openComposer();

      const { input, label } = ensureReplyFields(form);
      if (input) input.value = replyTo;

      const me = "@crisss";
      if (label) {
        label.textContent = `${me} está respondendo ${replyUser}.`;
        label.classList.remove("hidden");
      }

      try {
        ensureQuill();
        const q = window[STATE_KEY];
        if (q && typeof q.focus === "function") q.focus();
      } catch (_e) {}
    },
    true
  );

  // ============================================================
  // Upload de IMAGEM do Quill (paste/toolbar) — NÃO cria CardLog
  // ============================================================
  async function uploadQuillImageAndInsertEmbed(quill, file) {
    const uploadUrl = `/quill/upload/`;

    const form = new FormData();
    form.append("image", file); // view quill_upload espera "image"

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

    const data = await res.json().catch(() => ({}));
    const fileUrl = data && data.url ? String(data.url) : "";
    if (!fileUrl) throw new Error("Upload não retornou URL.");

    const range = quill.getSelection(true) || { index: quill.getLength() };

    quill.insertEmbed(range.index, "image", fileUrl);
    quill.insertText(range.index + 1, "\n");
    quill.setSelection(range.index + 2);

    try {
      quill.__autoGrowApply?.();
    } catch (_e) {}
  }

  // ============================================================
  // Upload de ANEXO (áudio/arquivo) — fluxo legado (pode criar log separado)
  // ============================================================
  async function uploadAttachmentAndInsertLink(quill, file, description) {
    const cardId = getCardId();
    if (!cardId) throw new Error("cardId ausente.");

    const uploadUrl = `/card/${cardId}/attachments/add/`;

    const form = new FormData();
    form.append("file", file);
    form.append("description", description || "Arquivo anexado na atividade");

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

    const raw = await res.text();

    const doc = new DOMParser().parseFromString(raw, "text/html");
    doc.querySelectorAll("[hx-swap-oob]").forEach((n) => n.remove());

    const list = document.getElementById("attachments-list");
    if (list) {
      const item =
        doc.querySelector("[id^='attachment-']") ||
        doc.querySelector(".attachment-item") ||
        doc.body.firstElementChild;

      if (item) list.insertAdjacentHTML("beforeend", item.outerHTML);
    }

    const a = doc.querySelector("a[href]");
    const img = doc.querySelector("img[src]");
    const fileUrl = (img && img.getAttribute("src")) || (a && a.getAttribute("href")) || "";

    const range = quill.getSelection(true) || { index: quill.getLength() };

    if (fileUrl) {
      quill.insertText(range.index, "🎤 Áudio", { link: fileUrl });
      quill.insertText(range.index + 7, "\n");
      quill.setSelection(range.index + 8);
    } else {
      quill.insertText(range.index, "[áudio anexado]\n");
      quill.setSelection(range.index + 15);
    }
  }

  // ============================================================
  // Quill init
  // ============================================================
  function ensureQuill() {
    if (typeof Quill === "undefined") return;
    if (!isComposerOpen()) return;

    const el = document.getElementById("cm-activity-editor");
    if (!el) return;

    destroyQuillIfStale(el);
    if (window[STATE_KEY]) return;

    const boardId = getBoardIdFromUrl();
    const modalScroll = getModalScrollContainer();

    const quillOptions = {
      theme: "snow",
      placeholder: "",
      modules: {
        toolbar: [
          [{ header: [1, 2, 3, false] }],
          ["bold", "italic", "underline", "strike"],
          [{ list: "ordered" }, { list: "bullet" }],
          ["link", "image", "audio"],
          ["clean"],
        ],
        mention: makeMentionConfig(boardId),
      },
    };

    if (modalScroll) quillOptions.scrollingContainer = modalScroll;

    const quill = new Quill(el, quillOptions);

    // ============================================================
    // ✅ IMAGEM: toolbar + paste => /quill/upload/ + embed (miniatura no texto)
    // ============================================================
    try {
      const toolbar = quill.getModule("toolbar");
      if (toolbar) {
        toolbar.addHandler("image", () => {
          const input = document.createElement("input");
          input.type = "file";
          input.accept = "image/*";
          input.onchange = async () => {
            try {
              const file = input.files && input.files[0];
              if (!file) return;
              await uploadQuillImageAndInsertEmbed(quill, file);
            } catch (err) {
              notifyActivityError(err?.message || "Erro ao enviar imagem.");
            }
          };
          input.click();
        });
      }
    } catch (_e) {}

    // paste (Ctrl+V) com imagem
    try {
      quill.root.addEventListener(
        "paste",
        async (e) => {
          const items = e?.clipboardData?.items || [];
          for (const it of items) {
            if (it && it.type && it.type.startsWith("image/")) {
              e.preventDefault();
              const file = it.getAsFile();
              if (!file) return;
              try {
                await uploadQuillImageAndInsertEmbed(quill, file);
              } catch (err) {
                notifyActivityError(err?.message || "Erro ao colar imagem.");
              }
              return;
            }
          }
        },
        true
      );
    } catch (_e) {}

    // ============================================================
    // AUDIO bind (mantém seu fluxo atual)
    // ============================================================
    try {
      const tb = quill.getModule("toolbar");
      const btn = tb?.container?.querySelector?.(".ql-audio");

      if (btn) {
        btn.setAttribute("type", "button");
        btn.setAttribute("title", "Gravar áudio");
        btn.setAttribute("aria-label", "Gravar áudio");
        btn.classList.toggle("is-recording", !!window.__cmAudioRec?.recording);

        const fire = (e) => {
          e.preventDefault();
          e.stopPropagation();
          toggleAudioRecording(quill);
        };

        if (btn.__cmAudioHandlers?.click) {
          btn.removeEventListener("click", btn.__cmAudioHandlers.click, true);
        }
        if (btn.__cmAudioHandlers?.touch) {
          btn.removeEventListener("touchstart", btn.__cmAudioHandlers.touch, true);
        }

        btn.addEventListener("click", fire, true);
        btn.addEventListener("touchstart", fire, { passive: false, capture: true });

        btn.__cmAudioHandlers = { click: fire, touch: fire };
      }
    } catch (_e) {}

    try {
      const toolbar = quill.getModule("toolbar");
      if (toolbar) toolbar.addHandler("audio", () => toggleAudioRecording(quill));
    } catch (_e) {}

    window[STATE_KEY] = quill;
    window[STATE_EL_KEY] = el;

    const container = quill.root.closest(".ql-container");
    if (container) delete container.dataset.cmManualMinHeight;
    autoGrowQuill(quill, { min: 140, max: 3000 });
  }

  // ============================================================
  // AUDIO
  // ============================================================
  window.__cmAudioRec = window.__cmAudioRec || {
    recording: false,
    recorder: null,
    stream: null,
    chunks: [],
  };

  function isAndroidUA() {
    const ua = (navigator.userAgent || "").toLowerCase();
    return ua.includes("android");
  }

  function isIOSUA() {
    const ua = (navigator.userAgent || "").toLowerCase();
    return /iphone|ipad|ipod/.test(ua);
  }

  function isMobileUA() {
    return isAndroidUA() || isIOSUA();
  }

  function notifyActivityError(msg) {
    const box = document.getElementById("activity-error");
    if (box) {
      box.textContent = msg || "";
      box.classList.toggle("hidden", !msg);
      return;
    }
    if (msg) {
      console.error("[activity-audio]", msg);
      try {
        alert(msg);
      } catch (_e) {}
    }
  }

  function getAudioButtonElFromQuill(quill) {
    const toolbar = quill?.getModule?.("toolbar");
    return toolbar?.container?.querySelector?.(".ql-audio") || null;
  }

  function setAudioButtonRecordingUI(quill, isOn) {
    const btn = getAudioButtonElFromQuill(quill);
    if (!btn) return;
    btn.classList.toggle("is-recording", !!isOn);
    btn.setAttribute("title", isOn ? "Gravando… clique para parar" : "Gravar áudio");
    btn.setAttribute("aria-label", isOn ? "Gravando… clique para parar" : "Gravar áudio");
  }

  function pickAudioMimeType() {
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg"];
    for (const c of candidates) {
      try {
        if (window.MediaRecorder && MediaRecorder.isTypeSupported(c)) return c;
      } catch (_e) {}
    }
    return "";
  }

  function fileExtFromMime(mime) {
    const m = (mime || "").toLowerCase();
    if (m.includes("ogg")) return "ogg";
    if (m.includes("webm")) return "webm";
    return "webm";
  }

  function ensureAudioFileInput() {
    let input = document.getElementById("cm-audio-capture-input");
    if (input) return input;

    input = document.createElement("input");
    input.type = "file";
    input.accept = "audio/*";
    input.id = "cm-audio-capture-input";
    input.style.display = "none";

    document.body.appendChild(input);
    return input;
  }

  function configureCaptureAttribute(input) {
    try {
      input.removeAttribute("capture");
    } catch (_e) {}

    if (!isMobileUA()) return;

    if (isAndroidUA()) {
      try {
        input.setAttribute("capture", "microphone");
      } catch (_e) {}
    } else {
      try {
        input.setAttribute("capture", "user");
      } catch (_e) {}
    }
  }

  async function startAudioRecording(quill) {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Gravação não suportada (getUserMedia indisponível).");
    }

    const isSecure = location.protocol === "https:" || location.hostname === "localhost";
    if (!isSecure) {
      throw new Error("Gravação exige HTTPS para acessar o microfone.");
    }

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = pickAudioMimeType();

    let recorder;
    try {
      recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    } catch (_e) {
      recorder = new MediaRecorder(stream);
    }

    window.__cmAudioRec.stream = stream;
    window.__cmAudioRec.recorder = recorder;
    window.__cmAudioRec.chunks = [];

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) window.__cmAudioRec.chunks.push(e.data);
    };

    recorder.start();
    window.__cmAudioRec.recording = true;
    setAudioButtonRecordingUI(quill, true);
  }

  async function stopAudioRecordingAndUpload(quill) {
    const rec = window.__cmAudioRec.recorder;
    if (!rec) return;

    const mime = rec.mimeType || "";
    await new Promise((resolve) => {
      rec.onstop = resolve;
      rec.stop();
    });

    const blob = new Blob(window.__cmAudioRec.chunks, { type: mime || "audio/webm" });

    try {
      window.__cmAudioRec.stream?.getTracks?.().forEach((t) => t.stop());
    } catch (_e) {}

    window.__cmAudioRec.recording = false;
    window.__cmAudioRec.recorder = null;
    window.__cmAudioRec.stream = null;
    window.__cmAudioRec.chunks = [];
    setAudioButtonRecordingUI(quill, false);

    const ext = fileExtFromMime(mime);
    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    const file = new File([blob], `audio-${ts}.${ext}`, { type: mime || "audio/webm" });

    // ✅ aqui era o bug: você chamava uma função que não existe
    await uploadAttachmentAndInsertLink(quill, file, "Áudio gravado na atividade");
  }

  async function fallbackCaptureAudioFile(quill) {
    const input = ensureAudioFileInput();
    configureCaptureAttribute(input);

    input.value = "";
    input.onchange = async () => {
      try {
        const file = input.files && input.files[0];
        if (!file) return;
        // ✅ aqui era o bug: você chamava uma função que não existe
        await uploadAttachmentAndInsertLink(quill, file, "Áudio enviado na atividade");
      } catch (err) {
        notifyActivityError(err?.message || "Erro ao enviar áudio.");
      }
    };

    input.click();
  }

  async function toggleAudioRecording(quill) {
    try {
      clearActivityError?.();

      const hasGetUserMedia = !!navigator.mediaDevices?.getUserMedia;
      const isSecure = location.protocol === "https:" || location.hostname === "localhost";

      if (!hasGetUserMedia || !isSecure || !window.MediaRecorder) {
        await fallbackCaptureAudioFile(quill);
        return;
      }

      if (!window.__cmAudioRec.recording) {
        await startAudioRecording(quill);
      } else {
        await stopAudioRecordingAndUpload(quill);
      }
    } catch (err) {
      setAudioButtonRecordingUI(quill, false);

      window.__cmAudioRec.recording = false;
      try {
        window.__cmAudioRec.stream?.getTracks?.().forEach((t) => t.stop());
      } catch (_e) {}

      window.__cmAudioRec.stream = null;
      window.__cmAudioRec.recorder = null;
      window.__cmAudioRec.chunks = [];

      notifyActivityError(err?.message || "Erro ao gravar/enviar áudio.");
    }
  }

  // ============================================================
  // ✅ Sync (HTML + Delta + Text)
  // ============================================================
  function syncPayload() {
    const quill = window[STATE_KEY];
    if (!quill) return { html: "", delta: "{}", text: "" };

    const html = String(quill.root?.innerHTML || "").trim();

    let delta = "{}";
    try {
      const d = quill.getContents();
      delta = JSON.stringify(d || {});
    } catch (_e) {}

    let text = "";
    try {
      text = String(quill.getText() || "").replace(/\s+$/g, "").trim();
    } catch (_e) {}

    return { html, delta, text };
  }

  function resetEditor() {
    const quill = window[STATE_KEY];
    if (!quill) return;
    quill.setText("");
  }

  window.resetActivityQuill = resetEditor;

  function bindActivityForm() {
    const form =
      document.getElementById("cm-activity-form") ||
      document.querySelector('section[data-cm-panel="ativ"] form');
    if (!form) return;

    if (form.dataset.cmBound === "1") return;
    form.dataset.cmBound = "1";

    form.addEventListener("htmx:configRequest", function (evt) {
      ensureQuill();
      clearActivityError();

      const { input } = ensureReplyFields(form);
      const replyTo = (input?.value || "").trim();

      const payload = syncPayload();

      if (evt.detail && evt.detail.parameters) {
        evt.detail.parameters["content"] = payload.html;
        evt.detail.parameters["delta"] = payload.delta;
        evt.detail.parameters["text"] = payload.text;
        if (replyTo) evt.detail.parameters["reply_to"] = replyTo;
      }
    });

    form.addEventListener("htmx:afterRequest", function (evt) {
      if (evt.detail?.successful === true) {
        try {
          const resp = evt.detail?.xhr?.responseText || "";
          applyPostSuccessActivityUI(resp);

          try {
            cleanupActivityLogSpacing();
          } catch (_e) {}
          setTimeout(() => {
            try {
              cleanupActivityLogSpacing();
            } catch (_e) {}
          }, 60);
        } catch (_e) {}

        resetEditor();
        clearActivityError();
        clearReplyContext();
        setActivityTab("feed");
        closeComposer();

        try {
          updateActivityFeedCount();
        } catch (_e) {}
        setTimeout(() => {
          try {
            updateActivityFeedCount();
          } catch (_e) {}
        }, 60);
      }
    });
  }

  function initActivityModule() {
    if (!isActivityTabActive()) return;
    bindActivityForm();
    if (isComposerOpen()) ensureQuill();
  }

  document.addEventListener(
    "click",
    function (e) {
      const btn = e.target?.closest?.('.cm-tabbtn[data-cm-tab="ativ"]');
      if (!btn) return;
      setTimeout(initActivityModule, 0);
      setTimeout(initActivityModule, 50);
    },
    true
  );

  getRoot()?.addEventListener("cm:tabchange", function (e) {
    if (e.detail?.tab === "ativ") {
      setTimeout(initActivityModule, 0);
      setTimeout(initActivityModule, 50);
    }
  });

  // ============================================================
  // GATILHO 3: modal renderizado / swaps do HTMX
  // ============================================================
  function afterModalPaint() {
    setTimeout(initActivityModule, 0);
    setTimeout(initActivityModule, 50);
    setTimeout(initActivityModule, 150);

    setTimeout(function () {
      const composer = getComposerEl();

      if (composer && !composer.classList.contains("is-hidden")) {
        setActivityTab("new");
      } else {
        setActivityTab("feed");
        closeComposer();
      }
    }, 0);

    try {
      bindFeedFilterUI();
    } catch (_e) {}
    try {
      applyFeedFilter();
    } catch (_e) {}

    try {
      cleanupActivityLogSpacing();
    } catch (_e) {}
    setTimeout(() => {
      try {
        cleanupActivityLogSpacing();
      } catch (_e) {}
    }, 120);

    try {
      updateActivityFeedCount();
    } catch (_e) {}
    setTimeout(() => {
      try {
        updateActivityFeedCount();
      } catch (_e) {}
    }, 140);
  }

  document.addEventListener("DOMContentLoaded", afterModalPaint);

  document.body.addEventListener("htmx:afterSettle", function (e) {
    const target = e.detail?.target || e.target;
    if (!target) return;
    if (target.id === "modal-body" || target.closest?.("#modal-body")) {
      afterModalPaint();
    }
  });

  document.body.addEventListener("htmx:afterSwap", function (e) {
    const target = e.detail?.target || e.target;
    if (!target || target.id !== "modal-body") return;

    const cmRoot = document.getElementById("cm-root");
    if (!cmRoot) return;

    if (typeof window.applySavedTagColorsToModal === "function") {
      window.applySavedTagColorsToModal(cmRoot);
    }

    if (typeof window.applySavedTermColorsToModal === "function") {
      window.applySavedTermColorsToModal(cmRoot);
    }

    afterModalPaint();
    setTimeout(bindActivityForm, 0);
  });
})();

// ============================================================
// END /boards/static/modal/modal.acitivity_quill.js
// ============================================================
