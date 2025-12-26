// modal.js — Modal do Card (HTMX + Quill)
// (arquivo “enxuto”: comentários curtos por função + blocos separados)

(() => {
  // =====================================================
  // Estado global
  // =====================================================
  window.currentCardId = null;
  let quillDesc = null;
  let quillAtiv = null;

  const tabsWithSave = new Set(["card-tab-desc", "card-tab-tags"]);

  // =====================================================
  // Helpers básicos
  // =====================================================
  function getCsrfToken() {
    return document.querySelector("meta[name='csrf-token']")?.content || "";
  }

  function qs(sel, root = document) {
    return root.querySelector(sel);
  }

  function qsa(sel, root = document) {
    return Array.from(root.querySelectorAll(sel));
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function getBoardIdFromUrl() {
    const m = (window.location.pathname || "").match(/\/board\/(\d+)\//);
    return m?.[1] ? Number(m[1]) : null;
  }

  function getModalEl() {
    return document.getElementById("modal");
  }

  function getModalBody() {
    return document.getElementById("modal-body");
  }

  function modalOpenBlockedNow() {
    const now = Date.now();

    if (window.__cardOpenGate?.isBlocked?.()) return true;

    if (window.__movedCardJustNowUntil && now < window.__movedCardJustNowUntil) return true;
    if (window.__cardDragCooldownUntil && now < window.__cardDragCooldownUntil) return true;
    if (window.__modalCloseCooldownUntil && now < window.__modalCloseCooldownUntil) return true;

    return false;
  }

  // =====================================================
  // Form (LEGADO)
  // =====================================================
  function getMainForm() {
    const body = getModalBody();
    if (!body) return null;
    return qs("#card-desc-form", body);
  }

  function getSavebarElements() {
    const form = getMainForm();
    if (!form) return { bar: null, saveBtn: null };
    const bar = qs("#desc-savebar", form);
    const saveBtn = qs("button[type='submit']", form);
    return { bar, saveBtn };
  }


    // =====================================================
// Fetch guard (mínimo) — evita reopen indevido e limpa URL após move-card
// =====================================================
(function installFetchGuardOnce() {
  if (window.__FETCH_GUARD_INSTALLED__) return;
  window.__FETCH_GUARD_INSTALLED__ = true;

  if (typeof window.fetch !== "function") return;
  if (window.fetch.__FETCH_GUARD_WRAPPED__) return;

  const originalFetch = window.fetch;

  window.fetch = function (input, init) {
    const url =
      typeof input === "string" ? input : input && input.url ? input.url : "";

    const method = String(
      (init && init.method) ||
        (input && typeof input === "object" && input.method) ||
        "GET"
    ).toUpperCase();

    const u = String(url || "");

    const isCardModal = method === "GET" && /\/card\/\d+\/modal\/?/.test(u);
    const isMoveCard = method === "POST" && /\/move-card\/?(?:\?.*)?$/.test(u);

    // bloqueia GET do modal quando gate/cooldowns ativos (sem fechar nada, só não abre)
    if (isCardModal && modalOpenBlockedNow()) {
      try {
        return Promise.resolve(new Response("", { status: 204 }));
      } catch (_e) {
        return Promise.resolve(null);
      }
    }

    // move-card OK: garante que não fique ?card=... na URL
    if (isMoveCard) {
      return originalFetch.call(this, input, init).then((res) => {
        try {
          if (res && res.ok) window.clearUrlCard?.({ replace: true });
        } catch (_e) {}
        return res;
      });
    }

    return originalFetch.call(this, input, init);
  };

  window.fetch.__FETCH_GUARD_WRAPPED__ = true;
})();


  // =====================================================
  // Move-reopen: marca "acabou de mover" + boing + auto-close
  // =====================================================
  (function installMoveReopenBoingOnce() {
    if (window.__MOVE_REOPEN_BOING_INSTALLED__) return;
    window.__MOVE_REOPEN_BOING_INSTALLED__ = true;

    window.__movedCardJustNowUntil = window.__movedCardJustNowUntil || 0;
    window.__movedCardJustNowCardId = window.__movedCardJustNowCardId || null;

    function ensureStyle() {
      if (document.getElementById("modal-move-boing-style")) return;
      const st = document.createElement("style");
      st.id = "modal-move-boing-style";
      st.textContent = `
        @keyframes modalBoingSlow {
          0%   { transform: translate3d(0,0,0) scale(1); opacity: 1; }
          25%  { transform: translate3d(0,-10px,0) scale(1.01); }
          55%  { transform: translate3d(0,6px,0) scale(0.995); }
          85%  { transform: translate3d(0,-4px,0) scale(1.003); }
          100% { transform: translate3d(0,0,0) scale(1); opacity: 1; }
        }
        .modal-boing-slow {
          animation: modalBoingSlow 1200ms cubic-bezier(.2, .8, .2, 1) both;
          will-change: transform;
        }
      `.trim();
      document.head.appendChild(st);
    }

    window.__markCardMovedNow = function (cardId, ms = 3500) {
      window.__movedCardJustNowUntil = Date.now() + Number(ms || 0);
      window.__movedCardJustNowCardId = Number(cardId || 0) || null;
      try {
        window.__cardOpenGate?.block?.(Number(ms || 0) + 1500, "moved-card");
      } catch (_e) {}
    };

    window.__shouldAutoCloseMoveReopen = function (cardId) {
      if (!window.__movedCardJustNowUntil) return false;
      if (Date.now() > window.__movedCardJustNowUntil) return false;

      const movedId = Number(window.__movedCardJustNowCardId || 0);
      const incoming = Number(cardId || 0);

      if (!incoming || !movedId) return true;
      return incoming === movedId;
    };

    window.__boingAndCloseModal = function () {
      ensureStyle();

      const modal = document.getElementById("modal");
      const body = document.getElementById("modal-body");
      if (!modal) return;

      modal.classList.remove("modal-boing-slow");
      void modal.offsetHeight;
      modal.classList.add("modal-boing-slow");

      setTimeout(() => {
        try {
          window.clearUrlCard?.({ replace: true });
        } catch (_e) {}

        try {
          if (typeof window.closeModal === "function") window.closeModal();
          else modal.classList.add("hidden");
        } catch (_e) {}

        try {
          if (body) body.innerHTML = "";
        } catch (_e) {}

        try {
          window.currentCardId = null;
        } catch (_e) {}
      }, 1100);
    };
  })();

  // =====================================================
  // CM Tabs
  // =====================================================
  function initCmModal(body) {
    const root = body?.querySelector?.("#cm-root");
    if (!root) return;

    const tabs = Array.from(root.querySelectorAll("[data-cm-tab]"));
    const panels = Array.from(root.querySelectorAll("[data-cm-panel]"));
    if (!tabs.length || !panels.length) return;

    const saveBtn = root.querySelector("#cm-save-btn");
    const form = root.querySelector("#cm-main-form");

    function setSaveVisibility(activeName) {
      const shouldShowSave = activeName === "desc" || activeName === "tags";
      if (!saveBtn) return;
      saveBtn.classList.toggle("hidden", !shouldShowSave);
      saveBtn.style.display = shouldShowSave ? "" : "none";
      saveBtn.disabled = !shouldShowSave;
    }

    function activate(name) {
      root.dataset.cmActive = name;

      tabs.forEach((b) =>
        b.classList.toggle("is-active", b.getAttribute("data-cm-tab") === name)
      );
      panels.forEach((p) =>
        p.classList.toggle("is-active", p.getAttribute("data-cm-panel") === name)
      );

      setSaveVisibility(name);
    }

    tabs.forEach((b) => {
      if (b.dataset.cmBound === "1") return;
      b.dataset.cmBound = "1";

      b.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const name = b.getAttribute("data-cm-tab");
        sessionStorage.setItem("cmActiveTab", name);
        activate(name);
      });
    });

    activate(sessionStorage.getItem("cmActiveTab") || "desc");

    if (saveBtn && form && saveBtn.dataset.cmBound !== "1") {
      saveBtn.dataset.cmBound = "1";
      saveBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();

        const active = root.dataset.cmActive || "desc";
        if (active !== "desc" && active !== "tags") return;

        try {
          form.requestSubmit();
        } catch (_e) {
          form.submit();
        }
      });
    }
  }

  // =====================================================
  // CM Extras: tag colors, errors, cover
  // =====================================================
  function cmGetRoot(body) {
    return body?.querySelector?.("#cm-root") || document.getElementById("cm-root");
  }

  function cmEnsureTagColorsState(root) {
    if (!root) return;
    if (!root.dataset.tagColors) {
      root.dataset.tagColors = root.getAttribute("data-tag-colors") || "{}";
    }
  }

  function cmApplySavedTagColors(root) {
    if (!root) return;

    let colors = {};
    try {
      const raw = root.dataset.tagColors || root.getAttribute("data-tag-colors") || "{}";
      colors = JSON.parse(raw);
      if (!colors || typeof colors !== "object") colors = {};
    } catch (_e) {
      colors = {};
    }

    const wrap = root.querySelector("#cm-tags-wrap");
    if (!wrap) return;

    wrap.querySelectorAll("button[data-tag]").forEach((btn) => {
      const tag = btn.getAttribute("data-tag");
      const c = colors[tag];
      if (!c) return;

      btn.style.backgroundColor = c + "20";
      btn.style.color = c;
      btn.style.borderColor = c;
    });
  }

  function applyBoardTagColorsNow() {
    if (typeof window.applySavedTagColorsToBoard === "function") {
      window.applySavedTagColorsToBoard(document);
    }
  }

  function cmInitTagColorPicker(root) {
    if (!root) return;
    if (root.dataset.cmTagColorBound === "1") return;
    root.dataset.cmTagColorBound = "1";

    const wrap = root.querySelector("#cm-tags-wrap");
    const picker = root.querySelector("#cm-tag-color-picker");
    const pop = root.querySelector("#cm-tag-color-popover");
    const save = root.querySelector("#cm-tag-color-save");
    const cancel = root.querySelector("#cm-tag-color-cancel");
    const form = root.querySelector("#cm-tag-color-form");
    const inpTag = root.querySelector("#cm-tag-color-tag");
    const inpCol = root.querySelector("#cm-tag-color-value");

    if (!wrap || !picker || !pop || !save || !cancel || !form || !inpTag || !inpCol)
      return;

    let currentBtn = null;

    wrap.addEventListener("click", function (e) {
      const btn = e.target.closest(".cm-tag-btn");
      if (!btn) return;

      currentBtn = btn;
      const tag = btn.dataset.tag;

      let colors = {};
      try {
        colors = JSON.parse(
          root.dataset.tagColors || root.getAttribute("data-tag-colors") || "{}"
        );
      } catch (_e) {}

      picker.value = colors[tag] || "#3b82f6";

      const mb = document.getElementById("modal-body");
      const mbRect = mb?.getBoundingClientRect() || { top: 0, left: 0 };

      const rect = btn.getBoundingClientRect();
      const top = rect.bottom - mbRect.top + (mb?.scrollTop || 0);
      const left = rect.left - mbRect.left + (mb?.scrollLeft || 0);

      pop.style.top = top + "px";
      pop.style.left = left + "px";

      pop.classList.remove("hidden");
    });

    cancel.addEventListener("click", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      pop.classList.add("hidden");
      currentBtn = null;
    });

    save.addEventListener("click", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();

      if (!currentBtn) return;

      const tag = currentBtn.dataset.tag;
      const color = picker.value;

      currentBtn.style.backgroundColor = color + "20";
      currentBtn.style.color = color;
      currentBtn.style.borderColor = color;

      let colors = {};
      try {
        colors = JSON.parse(
          root.dataset.tagColors || root.getAttribute("data-tag-colors") || "{}"
        );
      } catch (_e) {}
      colors[tag] = color;
      root.dataset.tagColors = JSON.stringify(colors);

      inpTag.value = tag;
      inpCol.value = color;

      pop.classList.add("hidden");

      fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        body: new FormData(form),
        headers: {
          "X-CSRFToken": form.querySelector('[name=csrfmiddlewaretoken]').value,
        },
      })
        .then((r) => {
          if (!r.ok) throw new Error("Falha ao salvar cor da tag");
          return r.json();
        })
        .then((data) => {
          const wrapEl = document.getElementById("cm-tags-wrap");
          if (wrapEl && data.modal) wrapEl.innerHTML = data.modal;

          const cardEl = document.getElementById("card-" + data.card_id);
          if (cardEl && data.snippet) cardEl.outerHTML = data.snippet;

          applyBoardTagColorsNow();

          const rootNow = document.getElementById("cm-root");
          cmEnsureTagColorsState(rootNow);
          cmApplySavedTagColors(rootNow);
          cmInitTagColorPicker(rootNow);
        })
        .catch((err) => console.error(err));
    });
  }

  function cmInstallAttachmentErrorsOnce() {
    if (document.body.dataset.cmAttachErrBound === "1") return;
    document.body.dataset.cmAttachErrBound = "1";

    function getRoot() {
      return document.getElementById("cm-root");
    }

    function showErr(root, msg) {
      const box = root?.querySelector?.("#attachments-error");
      if (!box) return;
      box.textContent = msg;
      box.classList.remove("hidden");
    }

    function clearErr(root) {
      const box = root?.querySelector?.("#attachments-error");
      if (!box) return;
      box.textContent = "";
      box.classList.add("hidden");
    }

    function resetFields(root) {
      const f = root?.querySelector?.("#attachment-file");
      const d = root?.querySelector?.("#attachment-desc");
      if (f) f.value = "";
      if (d) d.value = "";
    }

    document.body.addEventListener("htmx:beforeRequest", function (evt) {
      const root = getRoot();
      const elt = evt.detail?.elt;
      if (!root || !elt || !elt.matches?.("#attachment-file") || !root.contains(elt))
        return;

      root.dataset.cmUploading = "1";
      root.dataset.cmLastAttachmentDesc =
        (root.querySelector("#attachment-desc")?.value || "").trim();
      clearErr(root);
    });

    document.body.addEventListener("htmx:afterSwap", function (evt) {
      const root = getRoot();
      const target = evt.target;
      if (!root || !target || target.id !== "attachments-list") return;
      if (root.dataset.cmUploading !== "1") return;

      resetFields(root);
      clearErr(root);

      const desc = (root.dataset.cmLastAttachmentDesc || "").trim();
      if (desc) {
        const last = target.lastElementChild;
        if (last && !last.querySelector(".cm-attach-desc")) {
          const div = document.createElement("div");
          div.className = "cm-muted cm-attach-desc";
          div.style.marginTop = "4px";
          div.textContent = desc;
          last.appendChild(div);
        }
      }

      root.dataset.cmUploading = "0";
      root.dataset.cmLastAttachmentDesc = "";
    });

    document.body.addEventListener("htmx:responseError", function (evt) {
      const root = getRoot();
      const elt = evt.detail?.elt;
      const xhr = evt.detail?.xhr;
      if (!root || !elt || !elt.matches?.("#attachment-file") || !root.contains(elt))
        return;

      if (xhr && xhr.status === 413) {
        showErr(root, "Arquivo acima de 50MB. Comprima ou envie um link e tente novamente.");
      } else {
        showErr(root, "Não foi possível enviar o anexo agora. Tente novamente.");
      }

      resetFields(root);
      root.dataset.cmUploading = "0";
      root.dataset.cmLastAttachmentDesc = "";
    });

    document.body.addEventListener("htmx:afterRequest", function (evt) {
      const root = getRoot();
      const elt = evt.detail?.elt;
      const xhr = evt.detail?.xhr;
      if (!root || !elt || !elt.matches?.("#attachment-file") || !root.contains(elt))
        return;

      if (xhr && xhr.status >= 200 && xhr.status < 300) {
        resetFields(root);
        clearErr(root);
        root.dataset.cmUploading = "0";
        root.dataset.cmLastAttachmentDesc = "";
      }
    });
  }

  function cmInstallActivityErrorsOnce() {
    if (document.body.dataset.cmActivityErrBound === "1") return;
    document.body.dataset.cmActivityErrBound = "1";

    document.body.addEventListener("htmx:responseError", function (evt) {
      const elt = evt.detail?.elt;
      const xhr = evt.detail?.xhr;

      if (!elt || !elt.matches?.('form[hx-post*="add_activity"]')) return;

      const box = document.getElementById("activity-error");
      if (box) {
        box.textContent = xhr && xhr.responseText ? xhr.responseText : "Não foi possível incluir a atividade.";
        box.classList.remove("hidden");
      }

      try {
        elt.reset();
      } catch (_e) {}
    });
  }

  function cmInstallCoverPasteAndUploadOnce() {
    if (document.body.dataset.cmCoverBound === "1") return;
    document.body.dataset.cmCoverBound = "1";

    function showCoverErr(msg) {
      const box = document.getElementById("cm-cover-error");
      if (!box) return;
      if (!msg) {
        box.textContent = "";
        box.classList.add("hidden");
      } else {
        box.textContent = msg;
        box.classList.remove("hidden");
      }
    }

    function getRoot() {
      return document.getElementById("cm-root");
    }

    function getCoverForm(root) {
      if (!root) return null;
      return (
        root.querySelector("#cm-cover-form") ||
        root.querySelector("form[data-cm-cover-form]") ||
        root.querySelector('form[action*="cover"]') ||
        null
      );
    }

    function getCoverInput(root) {
      if (!root) return null;
      return (
        root.querySelector("#cm-cover-file") ||
        root.querySelector('input[name="cover"][type="file"]') ||
        root.querySelector('input[type="file"][accept*="image"]') ||
        root.querySelector('input[type="file"]') ||
        null
      );
    }

    function isPastingInsideQuill(e) {
      const ae = document.activeElement;
      if (
        ae &&
        ae.closest &&
        ae.closest(".ql-editor, .ql-container, #quill-editor, #quill-editor-ativ, #cm-quill-editor-ativ, #cm-quill-editor-desc")
      ) {
        return true;
      }

      const t = e.target;
      if (t && t.closest && t.closest(".ql-editor, .ql-container, #quill-editor, #quill-editor-ativ")) {
        return true;
      }

      const path = typeof e.composedPath === "function" ? e.composedPath() : [];
      if (
        path &&
        path.some(
          (n) =>
            n &&
            n.classList &&
            (n.classList.contains("ql-editor") || n.classList.contains("ql-container"))
        )
      ) {
        return true;
      }

      return false;
    }

    async function uploadCover(file) {
      const root = getRoot();
      if (!root) return;

      const form = getCoverForm(root);
      if (!form) return;

      showCoverErr(null);

      const fd = new FormData(form);
      fd.set("cover", file);

      let r;
      try {
        r = await fetch(form.action, {
          method: "POST",
          credentials: "same-origin",
          body: fd,
          headers: {
            "X-CSRFToken": form.querySelector('[name=csrfmiddlewaretoken]')?.value || "",
          },
        });
      } catch (_e) {
        showCoverErr("Falha de rede ao enviar a capa.");
        return;
      }

      if (!r.ok) {
        const t = await r.text().catch(() => "");
        showCoverErr(t || `Não foi possível salvar a capa (HTTP ${r.status}).`);
        return;
      }

      const html = await r.text();
      const modalBody = document.getElementById("modal-body");
      if (modalBody) modalBody.innerHTML = html;

      if (typeof window.initCardModal === "function") window.initCardModal();
    }

    document.body.addEventListener(
      "click",
      (e) => {
        const root = getRoot();
        if (!root) return;

        const pick =
          e.target.closest("#cm-cover-pick-btn") ||
          e.target.closest("[data-cm-cover-pick]") ||
          e.target.closest(".cm-cover-pick");

        if (!pick) return;

        const inp = getCoverInput(root);
        if (!inp) return;

        inp.click();
      },
      true
    );

    document.body.addEventListener(
      "change",
      (e) => {
        const root = getRoot();
        if (!root) return;

        const inp = e.target;
        if (!inp || inp.type !== "file") return;

        const isCoverInput =
          inp.matches?.("#cm-cover-file") ||
          inp.matches?.('input[name="cover"][type="file"]') ||
          !!inp.closest?.("#cm-cover-form");

        if (!isCoverInput) return;

        const file = inp.files?.[0];
        if (!file) return;

        if (!(file.type || "").startsWith("image/")) {
          showCoverErr("Arquivo inválido: envie uma imagem.");
          try {
            inp.value = "";
          } catch (_e) {}
          return;
        }

        uploadCover(file);
        try {
          inp.value = "";
        } catch (_e) {}
      },
      true
    );

    document.body.addEventListener(
      "paste",
      (e) => {
        const root = getRoot();
        if (!root) return;

        const active = root.dataset.cmActive || "desc";
        if (active !== "desc") return;

        if (isPastingInsideQuill(e)) return;

        const cd = e.clipboardData;
        if (!cd?.items?.length) return;

        const imgItem = Array.from(cd.items).find(
          (it) => it.kind === "file" && (it.type || "").startsWith("image/")
        );
        if (!imgItem) return;

        const file = imgItem.getAsFile();
        if (!file) return;

        e.preventDefault();
        uploadCover(file);
      },
      true
    );
  }

  function cmBoot(body) {
    const root = cmGetRoot(body);
    if (!root) return;

    cmEnsureTagColorsState(root);
    cmApplySavedTagColors(root);
    cmInitTagColorPicker(root);

    cmInstallAttachmentErrorsOnce();
    cmInstallActivityErrorsOnce();
    cmInstallCoverPasteAndUploadOnce();
  }

  // =====================================================
  // Modal open/close
  // =====================================================
  window.openModal = function () {
    if (modalOpenBlockedNow()) return;

    const modal = getModalEl();
    if (!modal) return;

    modal.classList.remove("hidden");
    modal.classList.remove("modal-closing");
    void modal.offsetHeight;
    modal.classList.add("modal-open");
  };

  window.closeModal = function () {
    const modal = getModalEl();
    const modalBody = getModalBody();

    try {
      const until = Date.now() + 800;
      const prev = Number(window.__modalCloseCooldownUntil || 0);
      window.__modalCloseCooldownUntil = Math.max(prev, until);
      window.__cardOpenGate?.block(1100, "close-modal");
      window.clearUrlCard?.({ replace: true });
    } catch (_e) {}

    if (!modal) return;

    modal.classList.remove("modal-open");
    modal.classList.add("modal-closing");

    setTimeout(() => {
      modal.classList.add("hidden");
      modal.classList.remove("modal-closing");

      if (modalBody) modalBody.innerHTML = "";

      window.currentCardId = null;
      quillDesc = null;
      quillAtiv = null;
    }, 230);
  };

  // =====================================================
  // Savebar (LEGADO)
  // =====================================================
  function hideSavebar() {
    const { bar, saveBtn } = getSavebarElements();
    if (!bar) return;
    bar.classList.add("hidden");
    bar.style.display = "none";
    if (saveBtn) saveBtn.disabled = true;
  }

  function showSavebar() {
    const { bar, saveBtn } = getSavebarElements();
    if (!bar) return;
    bar.classList.remove("hidden");
    bar.style.display = "";
    if (saveBtn) saveBtn.disabled = false;
  }

  function markDirty() {
    const form = getMainForm();
    if (!form) return;

    form.classList.add("is-dirty");
    const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
    if (tabsWithSave.has(active)) showSavebar();
  }

  function clearDirty() {
    const form = getMainForm();
    if (!form) return;
    form.classList.remove("is-dirty");
    hideSavebar();
  }

  function maybeShowSavebar() {
    const form = getMainForm();
    if (!form) return;
    if (form.classList.contains("is-dirty")) showSavebar();
    else hideSavebar();
  }

  // =====================================================
  // Tabs (LEGADO)
  // =====================================================
  window.cardOpenTab = function (panelId) {
    const modal = getModalEl();
    if (!modal) return;

    qsa(".card-tab-btn", modal).forEach((btn) => {
      btn.classList.toggle("card-tab-active", btn.getAttribute("data-tab-target") === panelId);
    });

    const body = getModalBody();
    if (!body) return;

    qsa(".card-tab-panel", body).forEach((panel) => {
      const isTarget = panel.id === panelId;
      panel.classList.toggle("block", isTarget);
      panel.classList.toggle("hidden", !isTarget);
    });

    sessionStorage.setItem("modalActiveTab", panelId);

    if (!tabsWithSave.has(panelId)) hideSavebar();
    else maybeShowSavebar();

    if (panelId === "card-tab-ativ") {
      const wrap = qs(".ativ-subtab-wrap", body);
      if (wrap?.__ativShowFromChecked) wrap.__ativShowFromChecked();
    }
  };

  // =====================================================
  // Quill helpers
  // =====================================================
  function insertBase64ImageIntoQuill(quill, file) {
    if (!quill || !file) return;

    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result;
      const range = quill.getSelection(true) || { index: quill.getLength() };

      quill.insertEmbed(range.index, "image", dataUrl, "user");
      quill.setSelection(range.index + 1, 0, "user");
      markDirty();
    };
    reader.readAsDataURL(file);
  }

  function bindDelegatedDirtyTracking() {
    const body = getModalBody();
    if (!body || body.dataset.dirtyDelegationBound) return;

    body.dataset.dirtyDelegationBound = "1";

    body.addEventListener("input", (ev) => {
      const form = getMainForm();
      if (!form) return;
      if (!form.contains(ev.target)) return;
      markDirty();
    });

    body.addEventListener("change", (ev) => {
      const form = getMainForm();
      if (!form) return;
      if (!form.contains(ev.target)) return;
      markDirty();
    });

    body.addEventListener("submit", (ev) => {
      const form = getMainForm();
      if (!form || ev.target !== form) return;
      const { saveBtn } = getSavebarElements();
      if (saveBtn) saveBtn.disabled = true;
    });
  }

  // =====================================================
  // Quill Desc (LEGADO + CM)
  // =====================================================
  function initQuillDesc(body) {
    if (!body) return;

    const legacyHost =
      qs("#quill-editor", body) ||
      qs("#quill-editor-desc", body) ||
      qs("[data-quill-desc]", body);

    if (legacyHost) {
      if (legacyHost.dataset.quillReady === "1") return;
      legacyHost.dataset.quillReady = "1";

      const hidden =
        qs("#desc-input", body) ||
        qs("#description-input", body) ||
        qs('input[name="description"]', body) ||
        qs('textarea[name="description"]', body) ||
        qs('textarea[name="desc"]', body) ||
        qs('input[name="desc"]', body);

      const selector = legacyHost.id
        ? `#${legacyHost.id}`
        : (() => {
            legacyHost.id = "quill-editor-desc";
            return "#quill-editor-desc";
          })();

      quillDesc = new Quill(selector, {
        theme: "snow",
        modules: {
          toolbar: {
            container: [
              [{ header: [1, 2, 3, false] }],
              ["bold", "italic", "underline"],
              ["link", "image"],
              [{ list: "ordered" }, { list: "bullet" }],
            ],
            handlers: {
              image: function () {
                const fileInput = document.createElement("input");
                fileInput.type = "file";
                fileInput.accept = "image/*";
                fileInput.onchange = () => {
                  const file = fileInput.files?.[0];
                  if (!file) return;
                  insertBase64ImageIntoQuill(quillDesc, file);
                };
                fileInput.click();
              },
            },
          },
        },
      });

      const initialHtml = (hidden?.value || "").trim();
      quillDesc.root.innerHTML = initialHtml || "";

      quillDesc.on("text-change", () => {
        if (hidden) hidden.value = quillDesc.root.innerHTML;
        markDirty();
      });

      quillDesc.root.addEventListener("paste", (e) => {
        const cd = e.clipboardData;
        if (!cd?.items?.length) return;

        const imgItems = Array.from(cd.items).filter(
          (it) => it.kind === "file" && (it.type || "").startsWith("image/")
        );
        if (!imgItems.length) return;

        e.preventDefault();
        imgItems.forEach((it) => {
          const file = it.getAsFile();
          if (file) insertBase64ImageIntoQuill(quillDesc, file);
        });
      });

      return;
    }

    const cmRoot = qs("#cm-root", body);
    if (!cmRoot) return;

    const descPanel = cmRoot.querySelector('[data-cm-panel="desc"]');
    if (!descPanel) return;

    const textarea = descPanel.querySelector('textarea[name="description"]');
    if (!textarea) return;

    if (textarea.dataset.cmQuillReady === "1") return;
    textarea.dataset.cmQuillReady = "1";

    const host = document.createElement("div");
    host.id = "cm-quill-editor-desc";
    host.className = "border rounded mb-2";
    host.style.minHeight = "220px";
    textarea.parentNode.insertBefore(host, textarea);

    textarea.style.display = "none";

    const boardId = getBoardIdFromUrl();

    const q = new Quill("#" + host.id, {
      theme: "snow",
      modules: {
        toolbar: {
          container: [
            [{ header: [1, 2, 3, false] }],
            ["bold", "italic", "underline"],
            ["link", "image"],
            [{ list: "ordered" }, { list: "bullet" }],
          ],
          handlers: {
            image: function () {
              const fileInput = document.createElement("input");
              fileInput.type = "file";
              fileInput.accept = "image/*";
              fileInput.onchange = () => {
                const file = fileInput.files?.[0];
                if (!file) return;
                insertBase64ImageIntoQuill(q, file);
              };
              fileInput.click();
            },
          },
        },

        mention: {
          allowedChars: /^[A-Za-zÀ-ÖØ-öø-ÿ0-9_ .-]*$/,
          mentionDenotationChars: ["@"],
          showDenotationChar: true,
          spaceAfterInsert: true,

          renderItem: function (item) {
            return renderMentionCard(item);
          },

          onSelect: function (item, insertItem) {
            const range = q.getSelection(true);
            if (!range) return;

            insertItem(item);

            setTimeout(() => {
              const root = q.root;
              const mentions = root.querySelectorAll("span.mention");
              const last = mentions[mentions.length - 1];
              if (!last) return;

              last.setAttribute("data-id", String(item.id));
              last.setAttribute("data-value", String(item.value));
              if (!last.textContent?.startsWith("@")) last.textContent = "@" + item.value;

              textarea.value = q.root.innerHTML;
            }, 0);
          },

          source: async function (searchTerm, renderList) {
            try {
              const qtxt = (searchTerm || "").trim();
              if (!boardId) return renderList([], searchTerm);

              const res = await fetch(
                `/board/${boardId}/mentions/?q=${encodeURIComponent(qtxt)}`,
                {
                  method: "GET",
                  credentials: "same-origin",
                  headers: { Accept: "application/json" },
                }
              );

              if (!res.ok) return renderList([], searchTerm);

              const data = await res.json();
              renderList(Array.isArray(data) ? data : data.results || [], searchTerm);
            } catch (_e) {
              renderList([], searchTerm);
            }
          },
        },
      },
    });

    q.root.innerHTML = (textarea.value || "").trim() || "";

    q.on("text-change", () => {
      textarea.value = q.root.innerHTML;
      markDirty();
    });

    const onPaste = (e) => {
      const cd = e.clipboardData;
      if (!cd?.items?.length) return;

      const imgItems = Array.from(cd.items).filter(
        (it) => it.kind === "file" && (it.type || "").startsWith("image/")
      );
      if (!imgItems.length) return;

      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation?.();

      imgItems.forEach((it) => {
        const file = it.getAsFile();
        if (file) insertBase64ImageIntoQuill(q, file);
      });
    };

    if (q.root.__onPasteCmDesc) {
      q.root.removeEventListener("paste", q.root.__onPasteCmDesc, true);
    }
    q.root.__onPasteCmDesc = onPaste;
    q.root.addEventListener("paste", onPaste, true);

    quillDesc = q;
  }

  // =====================================================
  // Quill Atividade (LEGADO + CM)
  // =====================================================
  function initQuillAtividade(body) {
    if (!body) return;

    const cmRoot = qs("#cm-root", body);
    if (cmRoot) {
      const ativPanel = cmRoot.querySelector('[data-cm-panel="ativ"]');
      if (!ativPanel) return;

      const form = ativPanel.querySelector('form[hx-post*="add_activity"], form');
      const textarea = ativPanel.querySelector('textarea[name="content"]');
      if (!form || !textarea) return;

      if (textarea.dataset.cmQuillReady === "1") return;
      textarea.dataset.cmQuillReady = "1";

      const host = document.createElement("div");
      host.id = "cm-quill-editor-ativ";
      host.className = "border rounded mb-2";
      host.style.minHeight = "140px";
      textarea.parentNode.insertBefore(host, textarea);

      textarea.style.display = "none";

      const boardId = getBoardIdFromUrl();

      const q = new Quill("#" + host.id, {
        theme: "snow",
        modules: {
          toolbar: {
            container: [
              [{ header: [1, 2, 3, false] }],
              ["bold", "italic", "underline"],
              ["link", "image"],
              [{ list: "ordered" }, { list: "bullet" }],
            ],
            handlers: {
              image: function () {
                const fileInput = document.createElement("input");
                fileInput.type = "file";
                fileInput.accept = "image/*";
                fileInput.onchange = () => {
                  const file = fileInput.files?.[0];
                  if (!file) return;
                  insertBase64ImageIntoQuill(q, file);
                };
                fileInput.click();
              },
            },
          },

          mention: {
            allowedChars: /^[A-Za-zÀ-ÖØ-öø-ÿ0-9_ .-]*$/,
            mentionDenotationChars: ["@"],
            showDenotationChar: true,
            spaceAfterInsert: true,

            renderItem: function (item) {
              return renderMentionCard(item);
            },

            onSelect: function (item, insertItem) {
              const range = q.getSelection(true);
              if (!range) return;

              insertItem(item);

              setTimeout(() => {
                const root = q.root;
                const mentions = root.querySelectorAll("span.mention");
                const last = mentions[mentions.length - 1];
                if (!last) return;

                last.setAttribute("data-id", String(item.id));
                last.setAttribute("data-value", String(item.value));
                if (!last.textContent?.startsWith("@")) last.textContent = "@" + item.value;

                textarea.value = q.root.innerHTML;
              }, 0);
            },

            source: async function (searchTerm, renderList) {
              try {
                const qtxt = (searchTerm || "").trim();
                if (!boardId) return renderList([], searchTerm);

                const res = await fetch(
                  `/board/${boardId}/mentions/?q=${encodeURIComponent(qtxt)}`,
                  {
                    method: "GET",
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                  }
                );

                if (!res.ok) return renderList([], searchTerm);

                const data = await res.json();
                renderList(Array.isArray(data) ? data : data.results || [], searchTerm);
              } catch (_e) {
                renderList([], searchTerm);
              }
            },
          },
        },
      });

      try {
        q.root.setAttribute("tabindex", "0");
      } catch (_e) {}

      q.root.innerHTML = (textarea.value || "").trim() || "";

      q.on("text-change", () => {
        textarea.value = q.root.innerHTML;
      });

      const onPasteCmAtiv = (e) => {
        const cd = e.clipboardData;
        if (!cd?.items?.length) return;

        const imgItems = Array.from(cd.items).filter(
          (it) => it.kind === "file" && (it.type || "").startsWith("image/")
        );
        if (!imgItems.length) return;

        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation?.();

        imgItems.forEach((it) => {
          const file = it.getAsFile();
          if (file) insertBase64ImageIntoQuill(q, file);
        });
      };

      if (q.root.__onPasteCmAtiv) {
        q.root.removeEventListener("paste", q.root.__onPasteCmAtiv, true);
      }
      q.root.__onPasteCmAtiv = onPasteCmAtiv;
      q.root.addEventListener("paste", onPasteCmAtiv, true);

      if (form.dataset.cmQuillResetBound !== "1") {
        form.dataset.cmQuillResetBound = "1";
        form.addEventListener("reset", () => {
          try {
            q.setText("");
          } catch (_e) {}
          textarea.value = "";
        });
      }

      return;
    }

    const activityHidden = qs("#activity-input", body);
    const quillAtivEl = qs("#quill-editor-ativ", body);
    if (!activityHidden || !quillAtivEl) return;

    if (quillAtivEl.dataset.quillReady === "1") return;
    quillAtivEl.dataset.quillReady = "1";

    quillAtiv = new Quill("#quill-editor-ativ", {
      theme: "snow",
      modules: {
        toolbar: {
          container: [
            [{ header: [1, 2, 3, false] }],
            ["bold", "italic", "underline"],
            ["link", "image"],
            [{ list: "ordered" }, { list: "bullet" }],
          ],
          handlers: {
            image: function () {
              const fileInput = document.createElement("input");
              fileInput.type = "file";
              fileInput.accept = "image/*";
              fileInput.onchange = () => {
                const file = fileInput.files?.[0];
                if (!file) return;
                insertBase64ImageIntoQuill(quillAtiv, file);
              };
              fileInput.click();
            },
          },
        },
      },
    });

    quillAtiv.root.innerHTML = "";
    activityHidden.value = "";

    quillAtiv.on("text-change", () => {
      activityHidden.value = quillAtiv.root.innerHTML;
    });

    const onPasteAtiv = (e) => {
      const cd = e.clipboardData;
      if (!cd?.items?.length) return;

      const imgItems = Array.from(cd.items).filter(
        (it) => it.kind === "file" && (it.type || "").startsWith("image/")
      );
      if (!imgItems.length) return;

      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation?.();

      imgItems.forEach((it) => {
        const file = it.getAsFile();
        if (file) insertBase64ImageIntoQuill(quillAtiv, file);
      });
    };

    if (quillAtiv.root.__onPasteAtiv) {
      quillAtiv.root.removeEventListener("paste", quillAtiv.root.__onPasteAtiv, true);
    }
    quillAtiv.root.__onPasteAtiv = onPasteAtiv;
    quillAtiv.root.addEventListener("paste", onPasteAtiv, true);
  }

  // =====================================================
  // Subtabs atividade (new/hist/move)
  // =====================================================
  function initAtivSubtabs3(body) {
    const wrap = qs(".ativ-subtab-wrap", body);
    if (!wrap) return;

    const rNew = qs("#ativ-tab-new", wrap);
    const rHist = qs("#ativ-tab-hist", wrap);
    const rMove = qs("#ativ-tab-move", wrap);

    const vNew = qs(".ativ-view-new", wrap);
    const vHist = qs(".ativ-view-hist", wrap);
    const vMove = qs(".ativ-view-move", wrap);

    function show(which) {
      if (vNew) {
        vNew.style.display = which === "new" ? "block" : "none";
        vNew.classList.toggle("hidden", which !== "new");
      }
      if (vHist) {
        vHist.style.display = which === "hist" ? "block" : "none";
        vHist.classList.toggle("hidden", which !== "hist");
      }
      if (vMove) {
        vMove.style.display = which === "move" ? "block" : "none";
        vMove.classList.toggle("hidden", which !== "move");
      }

      if (which === "move" && window.currentCardId && typeof window.loadMoveCardOptions === "function") {
        window.loadMoveCardOptions(window.currentCardId);
      }
    }

    function showFromChecked() {
      if (rMove?.checked) show("move");
      else if (rHist?.checked) show("hist");
      else show("new");
    }

    wrap.__ativShow = show;
    wrap.__ativShowFromChecked = showFromChecked;

    showFromChecked();

    if (wrap.dataset.ativ3Ready === "1") return;
    wrap.dataset.ativ3Ready = "1";

    rNew?.addEventListener("change", () => rNew.checked && show("new"));
    rHist?.addEventListener("change", () => rHist.checked && show("hist"));
    rMove?.addEventListener("change", () => rMove.checked && show("move"));

    qsa(".ativ-subtab-btn", wrap).forEach((lbl) => {
      lbl.addEventListener("click", () => setTimeout(showFromChecked, 0));
    });
  }

  // =====================================================
  // Init modal após swap
  // =====================================================
  window.initCardModal = function () {
    const body = getModalBody();
    if (!body) return;

    const cmRoot = qs("#cm-root", body);
    const legacyRoot = qs("#card-modal-root", body) || qs("#card-modal-root");

    const cid =
      cmRoot?.getAttribute?.("data-card-id") ||
      legacyRoot?.getAttribute?.("data-card-id");

    if (cid) window.currentCardId = Number(cid);

    bindDelegatedDirtyTracking();
    clearDirty();

    initQuillDesc(body);
    initQuillAtividade(body);
    initAtivSubtabs3(body);

    if (window.Prism) Prism.highlightAll();

    initCmModal(body);
    cmBoot(body);
  };

  // =====================================================
  // Abertura do modal por click no card (RADICAL)
  // =====================================================
  (function bindCardOpenRadical() {
    if (document.body.dataset.cardOpenRadicalBound === "1") return;
    document.body.dataset.cardOpenRadicalBound = "1";

    const SUPPRESS_MS = 1800;

    function shouldIgnoreClick(ev) {
      const t = ev.target;

      if (modalOpenBlockedNow()) return true;

      if (t?.closest?.("#modal")) return true;
      if (t?.closest?.("[data-no-modal]")) return true;

      const path = typeof ev.composedPath === "function" ? ev.composedPath() : [];
      const nodes = (path || []).filter((n) => n && n.nodeType === 1);

      const interactiveSelectors = [
        "button",
        "input",
        "textarea",
        "select",
        "form",
        "[role='menuitem']",
        "[contenteditable='true']",
        "[hx-get]",
        "[hx-post]",
        "[hx-trigger]",
      ];
      for (const n of nodes) {
        if (interactiveSelectors.some((sel) => n.matches?.(sel))) return true;
      }

      const menuToggleSelectors = [
        "[aria-haspopup='menu']",
        "[aria-haspopup='true']",
        "[aria-expanded]",
        "[data-bs-toggle]",
        "[data-toggle]",
        "[data-dropdown]",
        "[data-menu]",
        "[data-action='menu']",
        "[data-action='toggle']",
      ];
      for (const n of nodes) {
        if (menuToggleSelectors.some((sel) => n.matches?.(sel))) return true;
      }

      const menuContainerSelectors = [
        "[role='menu']",
        ".dropdown-menu",
        ".dropdown",
        ".menu",
        ".popover",
        ".popper",
        ".tooltip",
        ".card-actions",
        ".card-actions-menu",
        ".card-more",
        ".ellipsis",
      ];
      for (const n of nodes) {
        if (menuContainerSelectors.some((sel) => n.matches?.(sel))) return true;
      }

      return false;
    }

    function shieldFromModalInteraction() {
      try {
        window.__cardOpenGate?.block(SUPPRESS_MS, "modal-interaction");
      } catch (_e) {}
    }

    document.body.addEventListener(
      "pointerdown",
      (ev) => {
        if (ev.target?.closest?.("#modal")) shieldFromModalInteraction();
      },
      true
    );
    document.body.addEventListener(
      "mousedown",
      (ev) => {
        if (ev.target?.closest?.("#modal")) shieldFromModalInteraction();
      },
      true
    );
    document.body.addEventListener(
      "touchstart",
      (ev) => {
        if (ev.target?.closest?.("#modal")) shieldFromModalInteraction();
      },
      true
    );

    // Mobile: touchend abre (se não moveu)
    let touchStartY = 0;
    let touchMoved = false;

    document.body.addEventListener(
      "touchstart",
      (ev) => {
        const cardEl = ev.target.closest("li[data-card-id]");
        if (!cardEl) return;
        touchStartY = ev.touches[0].clientY;
        touchMoved = false;
      },
      { passive: true }
    );

    document.body.addEventListener(
      "touchmove",
      (ev) => {
        const deltaY = Math.abs(ev.touches[0].clientY - touchStartY);
        if (deltaY > 10) touchMoved = true;
      },
      { passive: true }
    );

    document.body.addEventListener(
      "touchend",
      (ev) => {
        const cardEl = ev.target.closest("li[data-card-id]");
        if (!cardEl) return;
        if (touchMoved) return;
        if (shouldIgnoreClick(ev)) return;

        const cardId = Number(cardEl.dataset.cardId || 0);
        if (!cardId) return;

        ev.preventDefault();
        ev.stopPropagation();

        window.openCardModalAndLoad(cardId, { replaceUrl: false });
      },
      true
    );

    // Desktop: click abre
    document.body.addEventListener(
      "click",
      (ev) => {
        const cardEl = ev.target.closest("li[data-card-id]");
        if (!cardEl) return;
        if (shouldIgnoreClick(ev)) return;

        const cardId = Number(cardEl.dataset.cardId || 0);
        if (!cardId) return;

        ev.preventDefault();
        ev.stopPropagation();

        window.openCardModalAndLoad(cardId, { replaceUrl: false });
      },
      true
    );
  })();

  // =====================================================
  // HTMX afterSwap do modal-body (BLINDADO)
  // =====================================================
  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (!e.detail?.target || e.detail.target.id !== "modal-body") return;

    if (modalOpenBlockedNow()) {
      try {
        window.clearUrlCard?.({ replace: true });
      } catch (_e) {}

      try {
        const mb = document.getElementById("modal-body");
        if (mb) mb.innerHTML = "";
      } catch (_e) {}

      try {
        const modal = document.getElementById("modal");
        if (modal) {
          modal.classList.remove("modal-open");
          modal.classList.add("hidden");
        }
      } catch (_e) {}

      try {
        window.currentCardId = null;
      } catch (_e) {}
      return;
    }

    const body = e.detail.target;
    const cid =
      body.querySelector("#cm-root")?.getAttribute("data-card-id") ||
      body.querySelector("#card-modal-root")?.getAttribute("data-card-id") ||
      null;

    if (window.__shouldAutoCloseMoveReopen?.(cid)) {
      window.openModal();
      try {
        window.initCardModal?.();
      } catch (_e) {}

      try {
        window.__boingAndCloseModal?.();
      } catch (_e) {
        try {
          window.closeModal?.();
        } catch (_e2) {}
      }
      return;
    }

    window.openModal();
    window.initCardModal();

    if (!document.querySelector("#cm-root")) {
      const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
      window.cardOpenTab(active);
    }
  });

  // =====================================================
  // Remover tag / set cor tag (instantâneo)
  // =====================================================
  window.removeTagInstant = async function (cardId, tag) {
    const formData = new FormData();
    formData.append("tag", tag);

    const response = await fetch(`/card/${cardId}/remove_tag/`, {
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() },
      body: formData,
      credentials: "same-origin",
    });

    if (!response.ok) return;

    const data = await response.json();

    const modalBody = getModalBody();
    if (modalBody) modalBody.innerHTML = data.modal;

    const card = document.querySelector(`#card-${data.card_id}`);
    if (card) card.outerHTML = data.snippet;

    applyBoardTagColorsNow();

    window.initCardModal();

    if (!document.querySelector("#cm-root")) {
      const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
      window.cardOpenTab(active);
    }
  };

  window.setTagColorInstant = async function (cardId, tag, color) {
    const formData = new FormData();
    formData.append("tag", tag);
    formData.append("color", color);

    const response = await fetch(`/card/${cardId}/set_tag_color/`, {
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() },
      body: formData,
      credentials: "same-origin",
    });

    if (!response.ok) return;

    const data = await response.json();

    const modalBody = getModalBody();
    if (modalBody) modalBody.innerHTML = data.modal;

    const card = document.querySelector(`#card-${data.card_id}`);
    if (card) card.outerHTML = data.snippet;

    window.initCardModal();
  };

  // =====================================================
  // Atividade (LEGADO)
  // =====================================================
  function htmlImageCount(html) {
    const tmp = document.createElement("div");
    tmp.innerHTML = html || "";
    return tmp.querySelectorAll("img").length;
  }

  function toastError(msg) {
    alert(msg);
  }

  window.clearActivityEditor = function () {
    const body = getModalBody();
    if (!body) return;

    const activityHidden = qs("#activity-input", body);
    if (quillAtiv) quillAtiv.setText("");
    if (activityHidden) activityHidden.value = "";
  };

  window.submitActivity = async function (cardId) {
    const body = getModalBody();
    if (!body) return;

    const activityInput = qs("#activity-input", body);
    if (!activityInput) return;

    const content = (activityInput.value || "").trim();
    if (!content) return;

    const imgCount = htmlImageCount(content);
    if (imgCount > 1) {
      toastError("No momento, cada atividade aceita no máximo 1 imagem.");
      return;
    }

    const formData = new FormData();
    formData.append("content", content);

    let response;
    try {
      response = await fetch(`/card/${cardId}/activity/add/`, {
        method: "POST",
        headers: { "X-CSRFToken": getCsrfToken() },
        body: formData,
        credentials: "same-origin",
      });
    } catch (_err) {
      toastError("Falha de rede ao incluir atividade.");
      return;
    }

    if (!response.ok) {
      const msg = await response.text().catch(() => "");
      toastError(msg || `Falha ao incluir atividade (HTTP ${response.status}).`);
      return;
    }

    const html = await response.text();

    const panel = qs("#card-activity-panel", body);
    if (panel) panel.outerHTML = html;
    else {
      const wrapper = qs("#activity-panel-wrapper", body);
      if (wrapper) wrapper.innerHTML = html;
    }

    window.clearActivityEditor();

    const histRadio = document.getElementById("ativ-tab-hist");
    if (histRadio) {
      histRadio.checked = true;
      histRadio.dispatchEvent(new Event("change", { bubbles: true }));
    }

    const wrap = qs(".ativ-subtab-wrap", body);
    if (wrap?.__ativShow) wrap.__ativShow("hist");

    if (window.Prism) Prism.highlightAll();
  };

  // =====================================================
  // Refresh snippet
  // =====================================================
  window.refreshCardSnippet = function (cardId) {
    if (!cardId) return;
    htmx.ajax("GET", `/card/${cardId}/snippet/`, {
      target: `#card-${cardId}`,
      swap: "outerHTML",
    });
  };

  // =====================================================
  // Move Card (DOM + backend) — RADICAL anti-reopen
  // =====================================================
  function getCurrentBoardIdFromUrl() {
    const m = (window.location.pathname || "").match(/\/board\/(\d+)\//);
    return m?.[1] ? Number(m[1]) : null;
  }

  function findColumnContainer(columnId) {
    const selectors = [
      `#column-${columnId} .cards`,
      `#column-${columnId} ul`,
      `#column-${columnId}`,
      `#col-${columnId} .cards`,
      `#col-${columnId} ul`,
      `#col-${columnId}`,
      `[data-column-id="${columnId}"] .cards`,
      `[data-column-id="${columnId}"] ul`,
      `[data-column-id="${columnId}"]`,
    ];

    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) return el;
    }
    return null;
  }

  function moveCardDom(cardId, newColumnId, newPosition0) {
    const cardEl = document.getElementById(`card-${cardId}`);
    if (!cardEl) return false;

    const target = findColumnContainer(newColumnId);
    if (!target) return false;

    const items = Array.from(
      target.querySelectorAll("[data-card-id], li[id^='card-'], #card-" + cardId + ", .card")
    );

    const idx = Math.max(0, Number(newPosition0 || 0));

    if (items[idx]) target.insertBefore(cardEl, items[idx]);
    else target.appendChild(cardEl);

    return true;
  }

  function removeCardParamOnce() {
    try {
      const u = new URL(window.location.href);
      if (u.searchParams.has("card")) {
        u.searchParams.delete("card");
        history.replaceState({}, "", u.toString());
      }
    } catch (_e) {}
  }

  function scrubCardParamFor(ms = 900) {
    const until = Date.now() + ms;

    const tick = () => {
      removeCardParamOnce();
      if (Date.now() < until) window.requestAnimationFrame(tick);
    };

    tick();
  }

  function closeModalHardAndCleanUrl() {
    try {
      window.__cardOpenGate?.block(2200, "move-close-hard");
      const until = Date.now() + 1200;
      const prev = Number(window.__modalCloseCooldownUntil || 0);
      window.__modalCloseCooldownUntil = Math.max(prev, until);
    } catch (_e) {}

    scrubCardParamFor(1200);
    try {
      window.clearUrlCard?.({ replace: true });
    } catch (_e) {}

    try {
      if (typeof window.closeModal === "function") window.closeModal();
      else {
        const modal = document.getElementById("modal");
        if (modal) {
          modal.classList.remove("modal-open");
          modal.classList.add("hidden");
        }
      }
    } catch (_e) {}

    try {
      const mb = document.getElementById("modal-body");
      if (mb) mb.innerHTML = "";
    } catch (_e) {}

    try {
      window.currentCardId = null;
    } catch (_e) {}

    scrubCardParamFor(1200);
  }

  (function bindMoveCardOnce() {
    if (window.__moveCardHookInstalled) return;
    window.__moveCardHookInstalled = true;

    function setMoveError(msg) {
      const body = getModalBody();
      if (!body) return;
      const err = qs("#move-error", body);
      if (!err) return;

      if (!msg) {
        err.textContent = "";
        err.classList.add("hidden");
      } else {
        err.textContent = msg;
        err.classList.remove("hidden");
      }
    }

    function setCurrentLocationText(txt) {
      const body = getModalBody();
      if (!body) return;
      const loc = qs("#move-current-location", body);
      if (loc) loc.textContent = txt || "—";
    }

    function fillSelect(sel, optionsHtml, placeholderHtml) {
      if (!sel) return;
      sel.innerHTML = (placeholderHtml || "") + (optionsHtml || "");
    }

    function getMoveEls() {
      const body = getModalBody();
      if (!body) return {};
      return {
        body,
        boardSel: qs("#move-board", body),
        colSel: qs("#move-column", body),
        posSel: qs("#move-position", body),
      };
    }

    window.loadMoveCardOptions = async function (cardId) {
      const { boardSel, colSel, posSel } = getMoveEls();
      if (!boardSel || !colSel || !posSel) return;

      setMoveError(null);

      fillSelect(boardSel, `<option value="">Carregando…</option>`);
      fillSelect(colSel, `<option value="">Selecione um quadro</option>`);
      fillSelect(posSel, `<option value="">Selecione uma coluna</option>`);
      colSel.disabled = true;
      posSel.disabled = true;

      setCurrentLocationText("carregando…");

      let data;
      let status = 0;
      let raw = "";

      try {
        const r = await fetch(`/card/${cardId}/move/options/`, {
          headers: {
            "X-Requested-With": "XMLHttpRequest",
            Accept: "application/json",
          },
          credentials: "same-origin",
        });

        status = r.status;
        raw = await r.text();

        if (!r.ok) throw new Error(raw || `HTTP ${status}`);

        try {
          data = JSON.parse(raw);
        } catch (_e) {
          throw new Error(`Resposta não é JSON (HTTP ${status}). Início: ${raw.slice(0, 120)}`);
        }
      } catch (e) {
        setCurrentLocationText("—");
        setMoveError(
          `Falha ao carregar opções de mover. ${
            status ? `HTTP ${status}. ` : ""
          }${String(e?.message || "").slice(0, 180)}`
        );
        fillSelect(boardSel, `<option value="">Erro ao carregar</option>`);
        return;
      }

      const cur = data.current || {};
      const boards = Array.isArray(data.boards) ? data.boards : [];
      const columnsByBoard = data.columns_by_board || {};

      setCurrentLocationText(
        `${cur.board_name || "—"} > ${cur.column_name || "—"} > Posição ${cur.position || "—"}`
      );

      fillSelect(
        boardSel,
        boards.map((b) => `<option value="${b.id}">${b.name}</option>`).join(""),
        `<option value="">Selecione…</option>`
      );

      boardSel.onchange = () => {
        const bid = String(boardSel.value || "");
        const cols = Array.isArray(columnsByBoard[bid]) ? columnsByBoard[bid] : [];

        colSel.disabled = !bid;
        posSel.disabled = true;

        if (!bid) {
          fillSelect(colSel, `<option value="">Selecione um quadro</option>`);
          fillSelect(posSel, `<option value="">Selecione uma coluna</option>`);
          return;
        }

        fillSelect(
          colSel,
          cols
            .map(
              (c) =>
                `<option value="${c.id}" data-pos-max="${c.positions_total_plus_one}">${c.name}</option>`
            )
            .join(""),
          `<option value="">Selecione…</option>`
        );

        fillSelect(posSel, `<option value="">Selecione uma coluna</option>`);
      };

      colSel.onchange = () => {
        const opt = colSel.selectedOptions?.[0];
        const max = Number(opt?.getAttribute("data-pos-max") || 0);

        posSel.disabled = !opt || !max;

        if (!max) {
          fillSelect(posSel, `<option value="">Selecione uma coluna</option>`);
          return;
        }

        const opts = Array.from({ length: max }, (_x, i) => {
          const v = i + 1;
          return `<option value="${v}">${v}</option>`;
        }).join("");

        fillSelect(posSel, opts, `<option value="">Selecione…</option>`);
      };

      if (cur.board_id) {
        boardSel.value = String(cur.board_id);
        boardSel.onchange();
      }
      if (cur.column_id) {
        colSel.value = String(cur.column_id);
        colSel.onchange();
      }
      if (cur.position) {
        posSel.value = String(cur.position);
      }
    };

    window.submitMoveCard = async function (cardId, ev) {
      try {
        window.__markCardMovedNow?.(cardId, 9000);
      } catch (_e) {}
      try {
        window.__cardOpenGate?.block(9000, "submit-move");
      } catch (_e) {}
      try {
        window.__cardDragCooldownUntil = Date.now() + 9000;
      } catch (_e) {}
      try {
        window.__modalCloseCooldownUntil = Date.now() + 9000;
      } catch (_e) {}

      try {
        ev?.preventDefault?.();
        ev?.stopPropagation?.();
        ev?.stopImmediatePropagation?.();
      } catch (_e) {}

      setMoveError(null);
      const { boardSel, colSel, posSel } = getMoveEls();
      if (!boardSel || !colSel || !posSel) {
        setMoveError("UI de mover não encontrada no modal.");
        return;
      }

      const boardId = (boardSel.value || "").trim();
      const columnId = (colSel.value || "").trim();
      const position1 = (posSel.value || "").trim();

      if (!boardId || !columnId || !position1) {
        setMoveError("Selecione quadro, coluna e posição.");
        return;
      }

      const payload = {
        card_id: Number(cardId),
        new_column_id: Number(columnId),
        new_position: Number(position1) - 1,
      };

      let r;
      try {
        r = await fetch(`/move-card/`, {
          method: "POST",
          headers: {
            "X-CSRFToken": getCsrfToken(),
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
          },
          body: JSON.stringify(payload),
          credentials: "same-origin",
        });
      } catch (_e) {
        setMoveError("Falha de rede ao mover.");
        return;
      }

      if (!r.ok) {
        const t = await r.text().catch(() => "");
        setMoveError(t || `Falha ao mover (HTTP ${r.status}).`);
        return;
      }

      const currentBoardId = getCurrentBoardIdFromUrl();
      const targetBoardId = Number(boardId);

      if (currentBoardId && targetBoardId && currentBoardId !== targetBoardId) {
        closeModalHardAndCleanUrl();
        window.location.href = `/board/${targetBoardId}/`;
        return;
      }

      scrubCardParamFor(1200);
      try {
        window.clearUrlCard?.({ replace: true });
      } catch (_e) {}

      const moved = moveCardDom(cardId, Number(columnId), payload.new_position);

      if (moved) {
        try {
          window.refreshCardSnippet(cardId);
        } catch (_e) {}
        closeModalHardAndCleanUrl();
        return;
      }

      closeModalHardAndCleanUrl();
      window.location.reload();
    };
  })();

  // =====================================================
  // URL do Card no board: /board/X/?card=ID
  // =====================================================
  function getCardIdFromUrl() {
    const u = new URL(window.location.href);
    const v = u.searchParams.get("card");
    const id = v ? parseInt(v, 10) : null;
    return Number.isFinite(id) ? id : null;
  }

  function setUrlCard(cardId, { replace = false } = {}) {
    const u = new URL(window.location.href);
    u.searchParams.set("card", String(cardId));
    if (replace) history.replaceState({ cardId }, "", u.toString());
    else history.pushState({ cardId }, "", u.toString());
  }

  function clearUrlCard({ replace = false } = {}) {
    const u = new URL(window.location.href);
    u.searchParams.delete("card");
    if (replace) history.replaceState({}, "", u.toString());
    else history.pushState({}, "", u.toString());
  }

  // expõe para o hard-stop e outros scripts
  window.setUrlCard = setUrlCard;
  window.clearUrlCard = clearUrlCard;

  window.openCardModalAndLoad = function (cardId, { replaceUrl = false } = {}) {
    if (!cardId) return;
    if (modalOpenBlockedNow()) return;

    setUrlCard(cardId, { replace: !!replaceUrl });
    window.currentCardId = cardId;

    htmx.ajax("GET", `/card/${cardId}/modal/`, {
      target: "#modal-body",
      swap: "innerHTML",
    });
  };

  function shouldIgnoreUrlCardBoot() {
    if (modalOpenBlockedNow()) return true;
    return false;
  }

  (function bindCardUrlBootOnce() {
    if (document.body.dataset.cardUrlBootBound === "1") return;
    document.body.dataset.cardUrlBootBound = "1";

    document.addEventListener("DOMContentLoaded", () => {
      const cardId = getCardIdFromUrl();
      if (!cardId) return;

      if (shouldIgnoreUrlCardBoot()) {
        clearUrlCard({ replace: true });
        return;
      }

      window.openCardModalAndLoad(cardId, { replaceUrl: true });
    });

    window.addEventListener("popstate", () => {
      const cardId = getCardIdFromUrl();
      const modal = document.getElementById("modal");
      const modalIsOpen = modal && modal.classList.contains("modal-open");

      if (cardId) {
        if (shouldIgnoreUrlCardBoot()) {
          clearUrlCard({ replace: true });
          return;
        }
        window.openCardModalAndLoad(cardId, { replaceUrl: true });
      } else if (modalIsOpen) {
        if (typeof window.closeModal === "function") window.closeModal();
      }
    });
  })();

  // =====================================================
  // User Settings Modal (Conta)
  // =====================================================
  (function bindUserSettingsModalOnce() {
    if (document.body.dataset.userSettingsBound === "1") return;
    document.body.dataset.userSettingsBound = "1";

    document.body.addEventListener(
      "click",
      function (ev) {
        const btn = ev.target.closest("#open-user-settings");
        if (!btn) return;

        ev.preventDefault();
        ev.stopPropagation();

        try {
          window.__cardOpenGate?.block(1500, "user-settings-open");
        } catch (_e) {}

        htmx.ajax("GET", "/account/modal/", {
          target: "#modal-body",
          swap: "innerHTML",
        });
      },
      true
    );

    document.body.addEventListener("userAvatarUpdated", function (ev) {
      const url = ev.detail && ev.detail.url ? String(ev.detail.url) : "";
      if (!url) return;

      const img = document.querySelector("#open-user-settings img");
      if (img) img.src = url;
    });
  })();
})();