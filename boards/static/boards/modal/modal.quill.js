// boards/static/boards/modal/modal.quill.js
(() => {
  if (!window.Modal) return;

  window.Modal.quill = window.Modal.quill || {};

  // ---------------------------
  // Helpers
  // ---------------------------

  /**
   * Força spellcheck=true de forma permanente:
   * Intercepta o próprio setAttribute do elemento para que NENHUM código
   * (incluindo o Quill) consiga setar spellcheck=false novamente.
   */
  function _enableSpellcheck(editorEl) {
    if (!editorEl) return;
    const _orig = editorEl.setAttribute.bind(editorEl);
    editorEl.setAttribute = function(name, value) {
      _orig(name, name === "spellcheck" ? "true" : value);
    };
    _orig("spellcheck", "true");
    _orig("lang", "pt-BR");
    // Aplica novamente nos próximos ticks para cobrir código deferido do Quill
    Promise.resolve().then(() => _orig("spellcheck", "true"));
    requestAnimationFrame(() => _orig("spellcheck", "true"));
  }

  /**
   * Autoformat de código: trecho "embrulhado" numa cerca — '''conteúdo''',
   * """conteúdo""", ```conteúdo``` ou ´´´conteúdo´´´ — vira um bloco de código
   * com o conteúdo dentro. As cercas PODEM estar em linhas diferentes (abre em
   * cima, cola o código, fecha embaixo): varremos o CAMPO INTEIRO, não só a linha
   * atual. Converte quando a cerca de fechamento completa o par. O ´´´ atende o
   * teclado ABNT, onde a tecla da crase produz ´ (acento agudo), não ` (backtick).
   */
  // par fechado em qualquer lugar do texto (multi-linha), mesmo tipo de cerca (\1).
  const _CODE_FENCE_RE = /(```|'''|"""|´´´)([\s\S]+?)\1/;
  function bindCodeFenceAutoformat(quill) {
    if (!quill || quill.__codeFenceBound) return;
    quill.__codeFenceBound = true;

    quill.on("text-change", (delta, _oldDelta, source) => {
      if (source !== "user" || quill.__codeFenceBusy) return;
      // só reage a inserção de texto (ignora pastes de imagem, deletes, etc.)
      const inserted = (delta.ops || []).some(
        (op) => typeof op.insert === "string" && op.insert && op.insert !== "\n"
      );
      if (!inserted) return;

      const full = quill.getText();
      const m = _CODE_FENCE_RE.exec(full);
      if (!m) return;

      const start = m.index;
      const whole = m[0];
      // tira uma quebra de linha colada em cada ponta (caso `'''` em linha própria),
      // mas mantém a indentação interna do código.
      let inner = m[2];
      if (inner.includes("\n")) {
        inner = inner.replace(/^[ \t]*\r?\n/, "").replace(/\r?\n[ \t]*$/, "");
      } else {
        inner = inner.trim();
      }

      quill.__codeFenceBusy = true;
      try {
        quill.deleteText(start, whole.length, "user");
        if (inner) quill.insertText(start, inner, "user");
        quill.formatLine(start, Math.max(1, inner.length), "code-block", true, "user");
        quill.setSelection(start + inner.length, 0, "silent");
      } finally {
        quill.__codeFenceBusy = false;
      }
    });
  }
  window.Modal.quill.bindCodeFenceAutoformat = bindCodeFenceAutoformat;

  /**
   * Adiciona um botão "Copiar" no canto de cada bloco de código já renderizado
   * (feed de atividade, etc.). Não mexe em blocos dentro de um editor (.ql-editor).
   */
  function decorateCodeBlocks(scope) {
    const root = scope && scope.querySelectorAll ? scope : document;
    const pres = root.querySelectorAll("pre:not([data-code-copy])");
    pres.forEach((pre) => {
      if (pre.closest(".ql-editor")) return; // bloco editável: não decora
      pre.setAttribute("data-code-copy", "1");

      const wrap = document.createElement("div");
      wrap.className = "code-copy-wrap";
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "code-copy-btn";
      // ícone </> à esquerda deixa claro que é código
      const ic = document.createElement("span");
      ic.className = "code-copy-ic";
      ic.textContent = "</>";
      const lbl = document.createElement("span");
      lbl.className = "code-copy-lbl";
      lbl.textContent = "Copiar";
      btn.append(ic, lbl);
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const code = pre.innerText.replace(/\n$/, ""); // tira o \n final do <pre>
        let flashed = false;
        const done = () => {
          if (flashed) return;
          flashed = true;
          lbl.textContent = "Copiado!";
          setTimeout(() => (lbl.textContent = "Copiar"), 1500);
        };
        // execCommand SÍNCRONO dentro do gesto (não depende de permissão/foco)…
        const okLegacy = legacyCopy(code);
        // …e a Clipboard API em paralelo (cobre quem faz execCommand virar no-op).
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(code).then(done).catch(() => { if (okLegacy) done(); });
        } else if (okLegacy) {
          done();
        }
      });
      wrap.appendChild(btn);
    });
  }
  // Recipe robusto: textarea readonly fora da tela (left:-9999px, NÃO opacity:0,
  // que faz alguns browsers retornarem ok sem copiar nada), seleção explícita.
  function legacyCopy(text) {
    let ok = false;
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      ta.style.top = "0";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      try { ta.setSelectionRange(0, text.length); } catch (_e) {}
      ok = document.execCommand("copy");
      ta.remove();
    } catch (_e) { ok = false; }
    return ok;
  }
  window.Modal.quill.decorateCodeBlocks = decorateCodeBlocks;

  // Decora o que já existe e tudo que aparecer depois. A atividade nova entra no
  // feed por WebSocket/JS (não dispara htmx:afterSwap), então um MutationObserver
  // garante o botão na hora do "Incluir", sem precisar de F5.
  let _decorScheduled = false;
  function scheduleDecorate() {
    if (_decorScheduled) return;
    _decorScheduled = true;
    requestAnimationFrame(() => {
      _decorScheduled = false;
      try { decorateCodeBlocks(document); } catch (_e) {}
    });
  }
  const _codeObserver = new MutationObserver((muts) => {
    for (const mu of muts) {
      for (const n of mu.addedNodes) {
        if (n.nodeType === 1 && (n.matches?.("pre") || n.querySelector?.("pre"))) {
          scheduleDecorate();
          return;
        }
      }
    }
  });
  function startCodeDecoration() {
    try { decorateCodeBlocks(document); } catch (_e) {}
    try { _codeObserver.observe(document.body, { childList: true, subtree: true }); } catch (_e) {}
  }
  if (document.body) startCodeDecoration();
  else document.addEventListener("DOMContentLoaded", startCodeDecoration);
  // mantém o hook htmx por garantia (troca de aba/feed render server-side)
  document.body?.addEventListener("htmx:afterSwap", () => scheduleDecorate());

    function pruneQuillOrphans(scope) {
    const root = scope || document;

    // 1) Remove toolbars que não têm um container logo em seguida
    root.querySelectorAll(".ql-toolbar").forEach((tb) => {
      const next = tb.nextElementSibling;
      if (!next || !next.classList || !next.classList.contains("ql-container")) {
        try { tb.remove(); } catch (_e) {}
      }
    });

    // 2) Remove containers que não têm editor interno
    root.querySelectorAll(".ql-container").forEach((ct) => {
      if (!ct.querySelector(".ql-editor")) {
        try { ct.remove(); } catch (_e) {}
      }
    });

    // 3) Se ainda sobrar mais de um toolbar “válido”, mantém só o primeiro
    const valid = Array.from(root.querySelectorAll(".ql-toolbar")).filter((tb) => {
      const next = tb.nextElementSibling;
      return next && next.classList && next.classList.contains("ql-container");
    });
    if (valid.length > 1) {
      valid.slice(1).forEach((tb) => { try { tb.remove(); } catch (_e) {} });
    }
  }


  function getBoardIdFromUrl() {
    const m = (window.location.pathname || "").match(/\/board\/(\d+)\b/);
    return m ? m[1] : null;
  }

  function ensureModalScrollable(modalScroll) {
    if (!modalScroll) return;
    modalScroll.style.setProperty("overflow-y", "auto", "important");
    modalScroll.style.setProperty("overflow-x", "hidden", "important");
    modalScroll.style.setProperty("-webkit-overflow-scrolling", "touch", "important");
  }

  function renderMentionCard(item) {
    const handle = (item?.handle || "").trim();
    const display_name = (item?.display_name || "").trim();
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
      avatarEl.textContent = (handle || "?").slice(0, 2).toUpperCase();
    }

    const meta = document.createElement("div");
    meta.className = "mention-meta";

    const handleEl = document.createElement("div");
    handleEl.className = "mention-name";
    handleEl.textContent = `@${handle}`;
    meta.appendChild(handleEl);

    if (display_name) {
      const nameEl = document.createElement("div");
      nameEl.className = "mention-handle";
      nameEl.textContent = display_name;
      meta.appendChild(nameEl);
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

      // popup escapa do editor (anexa no body com position:fixed)
      positioningStrategy: "fixed",
      defaultMenuOrientation: "bottom",
      mentionContainer: document.body,

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

  function pasteHtmlIntoQuill(quill, html) {
    try {
      const range = quill.getSelection(true) || { index: quill.getLength(), length: 0 };
      quill.clipboard.dangerouslyPasteHTML(range.index, html, "user");
      // posiciona caret no final do conteúdo inserido
      quill.setSelection(Math.min(quill.getLength(), range.index + 1), 0, "user");
      try { quill.__autoGrowApply?.(); } catch (_e) {}
    } catch (_e) {}
  }

  // ---------------------------
  // AutoGrow (estável, sem “pulo” no click)
  // ---------------------------
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

  const modalScroll = resolveModalScrollContainer();

  let stylesApplied = false;
  function applyStaticStyles() {
    if (stylesApplied) return;
    stylesApplied = true;

    // Quem rola é o modal, nunca o quill internamente
    container.style.setProperty("display", "block", "important");
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
  }

  function isActuallyVisible(el) {
    // evita medir quando a aba/painel está hidden
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    return (r.width > 0 && r.height > 0);
  }

  function applyHeight() {
    applyStaticStyles();

    // Se ainda não está visível, não mede (isso é o teu bug)
    if (!isActuallyVisible(editor)) return;

    const manualMin = getManualMinHeight();
    const needed = (editor.scrollHeight || 0) + 2;
    const target = Math.max(min, manualMin, needed);

    const current = Math.round(container.getBoundingClientRect().height || 0);
    const next = Math.ceil(target);

    if (Math.abs(current - next) < 2) return;

    // evita “pulo”: preserva scroll do container que está rolando
    const st = modalScroll ? modalScroll.scrollTop : 0;
    container.style.setProperty("height", `${next}px`, "important");
    if (modalScroll) modalScroll.scrollTop = st;
  }

  let scheduled = false;
  function scheduleApply() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      applyHeight();
    });
  }

  // 1) Conteúdo muda (ok)
  quill.on("text-change", scheduleApply);

  // 2) Quando o editor ganha foco/clique (aba pode ter acabado de abrir)
  editor.addEventListener("focusin", scheduleApply, true);
  editor.addEventListener("mousedown", scheduleApply, true);

  // 3) Imagens e recursos que alteram altura depois
  editor.addEventListener("load", scheduleApply, true);

  // 4) ResizeObserver: pega mudanças de layout/visibilidade sem depender de tecla
  let ro = null;
  try {
    ro = new ResizeObserver(() => scheduleApply());
    ro.observe(editor);
  } catch (_e) {}

  // boot (várias tentativas curtas para cobrir timing de swap/paint)
  scheduleApply();
  setTimeout(scheduleApply, 0);
  setTimeout(scheduleApply, 50);
  setTimeout(scheduleApply, 150);

  quill.__autoGrowApply = applyHeight;
  quill.__autoGrowSchedule = scheduleApply;

  return applyHeight;
}




    function cleanupQuillInModal() {
    const scope = document.querySelector("#modal-body") || document;

    // Remove toolbars/containers órfãos que ficaram de swaps anteriores
    scope.querySelectorAll(".ql-toolbar, .ql-container").forEach((el) => {
      // só remove se estiver dentro de um host nosso (.cm-quill) OU do quill-editor
      const insideOurHost = el.closest(".cm-quill") || el.closest("#quill-editor");
      if (insideOurHost) {
        try { el.remove(); } catch (_e) {}
      }
    });

    // Remove hosts duplicados (mantém só o primeiro por textarea)
    const hosts = Array.from(scope.querySelectorAll(".cm-quill"));
    if (hosts.length > 1) {
      hosts.slice(1).forEach((h) => { try { h.remove(); } catch (_e) {} });
    }
  }



  // ---------------------------
  // Bindings
  // ---------------------------
function bindQuillToTextarea(textarea, boardId) {
  if (!textarea) return null;

  const taId = textarea.id || textarea.getAttribute("name") || "description";
  const hostId = `cm-quill-host-${taId}`;

  // remove hosts duplicados do mesmo textarea
  const allHosts = Array.from(
    document.querySelectorAll(`#${CSS.escape(hostId)}, .cm-quill[data-for="${taId}"]`)
  );
  if (allHosts.length > 1) {
    allHosts.slice(1).forEach((h) => { try { h.remove(); } catch (_e) {} });
  }

  let host = document.getElementById(hostId);
  if (!host) {
    host = document.createElement("div");
    host.className = "cm-quill";
    host.id = hostId;
    host.dataset.for = taId;
    textarea.insertAdjacentElement("afterend", host);
  } else {
    const hasQuillDom = !!host.querySelector(".ql-container");
    if (hasQuillDom) {
      textarea.dataset.quillBound = "1";
      textarea.style.display = "none";
      return null;
    }
    try { host.innerHTML = ""; } catch (_e) {}
  }

  textarea.dataset.quillBound = "1";
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
        ["code", "code-block"],
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
  _enableSpellcheck(quill.root);
  bindCodeFenceAutoformat(quill);
  quill.__cmModalScroll = modalScroll || null;
  window.Modal.quill._descQuill = quill;

  // carrega HTML inicial como HTML (renderiza)
  const initial = (textarea.value || "").trim();
  if (initial) {
    try { quill.clipboard.dangerouslyPasteHTML(0, initial, "silent"); }
    catch (_e) { quill.root.innerHTML = initial; }
  }

  const container = quill.root.closest(".ql-container");
  if (container) delete container.dataset.cmManualMinHeight;

  autoGrowQuill(quill, { min: 100 });

  const syncToTextarea = () => {
    try {
      textarea.value = quill.root.innerHTML || "";
      try { textarea.dispatchEvent(new Event("input", { bubbles: true })); } catch (_e) {}
    } catch (_e) {}
  };

  quill.on("text-change", syncToTextarea);
  syncToTextarea();

  const form = textarea.closest("form");
  if (form && !form.dataset.quillSyncBoundTextarea) {
    form.dataset.quillSyncBoundTextarea = "1";
    const syncToTextarea = () => {
      try { quill.update?.("silent"); } catch (_e) {}
      try { textarea.value = quill.root.innerHTML || ""; } catch (_e) {}
    };

    // document.body.addEventListener("htmx:configRequest", () => {
    //   try { syncToTextarea(); } catch (_e) {}
    // }, true);

    // document.body.addEventListener("htmx:beforeRequest", () => {
    //   try { syncToTextarea(); } catch (_e) {}
    // }, true);
  } // ✅ FECHA o if(form...)

  // toolbar image (fora do if)
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

  // paste: imagem > html
  quill.root.addEventListener("paste", (e) => {
    try {
      const cd = e.clipboardData;
      if (!cd) return;

      const items = cd?.items ? Array.from(cd.items) : [];
      const imgItem = items.find((it) => (it.type || "").startsWith("image/"));
      if (imgItem) {
        const file = imgItem.getAsFile?.();
        if (file) {
          e.preventDefault();
          insertBase64ImageIntoQuill(quill, file);
        }
        return;
      }

      const html = cd.getData("text/html");
      if (html && html.trim()) {
        e.preventDefault();
        pasteHtmlIntoQuill(quill, html);
      }
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
        ["code", "code-block"],
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
  _enableSpellcheck(quill.root);
  bindCodeFenceAutoformat(quill);
  quill.__cmModalScroll = modalScroll || null;
  window.Modal.quill._descQuill = quill;

  // carrega HTML inicial como HTML (renderiza)
  const initial = (hiddenInput.value || "").trim();
  if (initial) {
    try { quill.clipboard.dangerouslyPasteHTML(0, initial, "silent"); }
    catch (_e) { quill.root.innerHTML = initial; }
  }

  const syncToHiddenInput = () => {
    try {
      hiddenInput.value = quill.root.innerHTML || "";
      try { hiddenInput.dispatchEvent(new Event("input", { bubbles: true })); } catch (_e) {}
    } catch (_e) {}
  };

  quill.on("text-change", syncToHiddenInput);
  syncToHiddenInput();

  const form = hiddenInput.closest("form");
  if (form && !form.dataset.quillSyncBoundHidden) {
    form.dataset.quillSyncBoundHidden = "1";
    form.addEventListener("submit", syncToHiddenInput, { capture: true });

    document.body.addEventListener("htmx:configRequest", () => {
      try { syncToHiddenInput(); } catch (_e) {}
    }, true);

    document.body.addEventListener("htmx:beforeRequest", () => {
      try { syncToHiddenInput(); } catch (_e) {}
    }, true);
  } // ✅ FECHA o if(form...)

  const container = quill.root.closest(".ql-container");
  if (container) delete container.dataset.cmManualMinHeight;

  autoGrowQuill(quill, { min: 100 });

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
      if (!cd) return;

      const items = cd?.items ? Array.from(cd.items) : [];
      const imgItem = items.find((it) => (it.type || "").startsWith("image/"));
      if (imgItem) {
        const file = imgItem.getAsFile?.();
        if (file) {
          e.preventDefault();
          insertBase64ImageIntoQuill(quill, file);
        }
        return;
      }

      const html = cd.getData("text/html");
      if (html && html.trim()) {
        e.preventDefault();
        pasteHtmlIntoQuill(quill, html);
      }
    } catch (_e) {}
  });

  return quill;
}





























  // ---------------------------
  // Public init
  // ---------------------------
  window.Modal.quill.init = function () {
    const boardId = getBoardIdFromUrl();
    const modal = document.querySelector("#modal-body") || document;

    // limpa lixo anterior (toolbars/containers órfãos)
    pruneQuillOrphans(modal);

    const descDiv = modal.querySelector("#quill-editor");
    const descHidden = modal.querySelector("#description-input");
    if (descDiv && descHidden) {
      bindQuillToDiv(descDiv, descHidden, boardId);

      // poda de novo após o Quill montar DOM
      requestAnimationFrame(() => pruneQuillOrphans(modal));
      return;
    }

    const descTa =
      modal.querySelector('#cm-root textarea[name="description"]') ||
      modal.querySelector('textarea[name="description"]');

    if (descTa) {
      bindQuillToTextarea(descTa, boardId);
      requestAnimationFrame(() => pruneQuillOrphans(modal));
    }
  };



(function watchActiveTabForDescAutogrow(){
  if (window.__cmWatchDescTab) return;
  window.__cmWatchDescTab = true;

  const root = document.getElementById("cm-root");
  if (!root) return;

  const mo = new MutationObserver(() => {
    const active = root.getAttribute("data-cm-active") || root.dataset.cmActive;
    if (active === "desc") {
      const q = window.Modal?.quill?._descQuill;
      try { q?.__autoGrowSchedule?.(); } catch (_e) {}
      try { requestAnimationFrame(() => q?.__autoGrowSchedule?.()); } catch (_e) {}
    }
  });

  mo.observe(root, { attributes: true, attributeFilter: ["data-cm-active"] });
})();




  // rebind em swaps do modal
    let __cmQuillInitRaf = 0;

   document.body.addEventListener("htmx:afterSwap", function (e) {
    const target = e?.target;
    if (!target) return;

    if (target.id === "modal-body" || target.closest?.("#modal-body")) {
      try { window.Modal?.quill?.init?.(); } catch (_e) {}
      try {
        const modal = document.querySelector("#modal-body") || document;
        requestAnimationFrame(() => pruneQuillOrphans(modal));
      } catch (_e) {}
    }
  });



  // ---------------------------
  // Click em imagem abre em nova aba
  // ---------------------------
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

  // ---------------------------
  // Resize Grip flutuante (não interfere no layout/overflow)
  // ---------------------------
  (function installDescResizeGripFloating() {
    if (window.__cmDescGripInstalled) return;
    window.__cmDescGripInstalled = true;

    let grip = null;
    let rafId = 0;

    function clamp(n, min, max) {
      return Math.max(min, Math.min(max, n));
    }

    function getDescContainer() {
      const root = document.getElementById("cm-root");
      if (!root) return null;

      // só quando a aba descrição estiver ativa (se existir esse controle)
      const active = root.getAttribute("data-cm-active") || root.dataset.cmActive;
      if (active && active !== "desc") return null;

      const host =
        document.querySelector("#modal-body #quill-editor") ||
        document.querySelector("#modal-body .cm-quill") ||
        document.querySelector("#modal-body textarea[name='description']")?.nextElementSibling;

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

      // fallback visual caso CSS não carregue
      grip.style.position = "fixed";
      grip.style.width = "18px";
      grip.style.height = "18px";
      grip.style.cursor = "nwse-resize";
      grip.style.zIndex = "40";
      grip.style.opacity = "0.8";

      document.body.appendChild(grip);
      bindDrag(grip);
      return grip;
    }

    function positionGrip() {
      const container = getDescContainer();
      const g = ensureGrip();

      if (!container) {
        g.style.display = "none";
        return;
      }

      const r = container.getBoundingClientRect();
      g.style.left = `${Math.max(0, r.right - 22)}px`;
      g.style.top = `${Math.max(0, r.bottom - 22)}px`;
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

      function getY(e) {
        return (e.touches ? e.touches[0].clientY : e.clientY);
      }

      function onDown(e) {
        container = getDescContainer();
        if (!container) return;

        dragging = true;
        startY = getY(e);
        startH = container.getBoundingClientRect().height;

        // trava altura explícita e marca manual (prioridade sobre auto-grow)
        container.style.setProperty("height", `${Math.round(startH)}px`, "important");
        container.dataset.cmManualMinHeight = String(Math.round(startH));

        e.preventDefault();
        e.stopPropagation();

        document.addEventListener("mousemove", onMove, true);
        document.addEventListener("mouseup", onUp, true);
        document.addEventListener("touchmove", onMove, { passive: false, capture: true });
        document.addEventListener("touchend", onUp, true);
      }

      function onMove(e) {
        if (!dragging || !container) return;

        const y = getY(e);
        const dy = y - startY;

        const vh = window.innerHeight || 800;
        const maxH = clamp(Math.floor(vh * 0.60), 260, 900);
        const newH = clamp(startH + dy, 180, maxH);

        container.style.setProperty("height", `${Math.round(newH)}px`, "important");
        container.dataset.cmManualMinHeight = String(Math.round(newH));

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
        try { requestAnimationFrame(() => window.Modal?.quill?._descQuill?.__autoGrowApply?.()); } catch (_e) {}
      }

      g.addEventListener("mousedown", onDown, true);
      g.addEventListener("touchstart", onDown, { passive: false, capture: true });
    }

    // triggers
    document.body.addEventListener("htmx:afterSwap", schedulePosition);
    document.body.addEventListener("htmx:afterSettle", schedulePosition);
    document.addEventListener("scroll", schedulePosition, true);
    window.addEventListener("resize", schedulePosition);

    document.addEventListener("modal:closed", function () {
      if (grip) grip.style.display = "none";
    });

    setTimeout(schedulePosition, 0);
  })();

  // init inicial
  try { window.Modal?.quill?.init?.(); } catch (_e) {}
})();







function syncActiveDesc() {
  const root = document.getElementById("cm-root");
  if (!root) return;

  const ta = root.querySelector('#cm-description, textarea[name="description"]');
  const q = window.Modal?.quill?._descQuill;

  if (!ta || !q || !q.root) return;

  // 🔒 força o Quill a “commitar” estado pendente antes de ler HTML
  try { q.update?.("silent"); } catch (_e) {}

  try { ta.value = q.root.innerHTML || ""; } catch (_e) {}
}
