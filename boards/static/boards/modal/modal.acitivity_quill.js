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

    // Só inicializa Quill quando abriu
    ensureQuill();

    // foco
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
      const btn = e.target?.closest?.("#cm-activity-toggle");
      if (!btn) return;

      if (isComposerOpen()) closeComposer();
      else openComposer();
    },
    true
  );

  // ============================================================
  // Detectar se a aba ATIVIDADE está realmente ativa no DOM
  // (não confiar só em data-cm-active)
  // ============================================================
  function isActivityTabActive() {
    const root = getRoot();
    if (!root) return false;

    // 1) layout com aba (card_modal_body)
    const panel = root.querySelector('section[data-cm-panel="ativ"]');
    if (panel && panel.classList.contains("is-active")) return true;

    const btn = root.querySelector('.cm-tabbtn[data-cm-tab="ativ"]');
    if (btn && btn.classList.contains("is-active")) return true;

    if (root.getAttribute("data-cm-active") === "ativ") return true;

    // 2) layout split (card_modal_split): atividade pode existir no DOM
    return !!document.getElementById("cm-activity-editor");
  }
  // ============================================================

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
  // AUTO-GROW (mesmo comportamento da Descrição)
  // - sem scroll interno no editor
  // - quem rola é o modal (scroll único)
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
      // Layout previsível
      container.style.setProperty("display", "block", "important");
      container.style.setProperty("max-height", "none", "important");

      // ✅ EVITA “scroll invisível”: não clipar o conteúdo
      container.style.setProperty("overflow", "visible", "important");

      editor.style.setProperty("display", "block", "important");
      editor.style.setProperty("height", "auto", "important");
      editor.style.setProperty("min-height", "0", "important");

      // ✅ placeholder/texto não pode ser cortado
      editor.style.setProperty("overflow", "visible", "important");
      // ✅ respiro no fundo (evita a última linha encostar na borda)
      editor.style.setProperty("padding-bottom", "14px", "important");


      const bottomPad = 14; // precisa bater com o padding-bottom acima
      const needed = (editor.scrollHeight || 0) + bottomPad;

      const manualMin = getManualMinHeight();
      const target = clamp(Math.max(min, manualMin, needed), min, max);

      container.style.setProperty("height", `${target}px`, "important");

      // ✅ O Quill pode ajustar scrollTop depois do seu cálculo.
      // Então zera em 2 frames para “ganhar” do Quill.
      requestAnimationFrame(() => {
        resetInternalScroll();
        requestAnimationFrame(resetInternalScroll);
      });

      try { window.dispatchEvent(new Event("resize")); } catch (_e) {}
    }

    // digitação / enter / deletar
    quill.on("text-change", () => {
      apply();
      requestAnimationFrame(apply);
    });

    // movimentar cursor também pode disparar scroll interno
    quill.on("selection-change", () => {
      resetInternalScroll();
      requestAnimationFrame(resetInternalScroll);
    });

    // imagens carregando mudam altura depois
    editor.addEventListener("load", () => requestAnimationFrame(apply), true);

    // inicial
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

  function refreshActivityPanel() {
    // tenta achar um container com hx-get para dar refresh de verdade
    const hxHost =
      document.querySelector("#cm-activity-panel[hx-get]") ||
      document.querySelector("#cm-activity-panel [hx-get]") ||
      document.querySelector("#activity-panel-wrapper[hx-get]") ||
      document.querySelector("#activity-panel-wrapper [hx-get]");

    if (!hxHost) return;

    const url = hxHost.getAttribute("hx-get");
    if (!url) return;

    if (window.htmx && typeof window.htmx.ajax === "function") {
      try {
        window.htmx.ajax("GET", url, {
          target: hxHost,
          swap: hxHost.getAttribute("hx-swap") || "innerHTML",
        });
      } catch (_e) {}
    }
  }

  function applyPostSuccessActivityUI(responseText) {
  removeActivityEmptyState();

  const html = String(responseText || "").trim();
  if (!html) return;

  // 1) Se o backend devolveu o painel inteiro, substitui o painel (anti-duplicação)
  const panel = document.getElementById("card-activity-panel");
  if (panel && (html.includes('id="card-activity-panel"') || html.includes('id="activity-panel-wrapper"'))) {
    panel.outerHTML = html;
    return;
  }

  // 2) Se devolveu só um item, insere no topo da lista
  const list =
    document.querySelector("#activity-panel-wrapper .cm-activity-list") ||
    document.querySelector("#cm-activity-panel .cm-activity-list");

  const looksLikeItem = html.includes("activity-item") || html.includes("cm-activity-item");

  if (list && looksLikeItem) {
    try {
      list.insertAdjacentHTML("afterbegin", html);
      return;
    } catch (_e) {}
  }
}



  // ============================================================
  // REPLY (Responder)
  // - botão ↩ no item da atividade seta reply_to
  // - mostra label "@crisss está respondendo @fulano."
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
      // tenta inserir perto do editor
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

      // abre o composer (precisa do seu openComposer/ensureQuill)
      openComposer();

      const { input, label } = ensureReplyFields(form);
      if (input) input.value = replyTo;

      // label (sem trazer o texto original pro editor)
      const me = "@crisss";
      if (label) {
        label.textContent = `${me} está respondendo ${replyUser}.`;
        label.classList.remove("hidden");
      }

      // foco no editor
      try {
        ensureQuill();
        const q = window[STATE_KEY];
        if (q && typeof q.focus === "function") q.focus();
      } catch (_e) {}
    },
    true
  );



function ensureQuill() {
  if (typeof Quill === "undefined") return;

  // não monta Quill quando composer está oculto
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

  // ✅ BIND “duro” no botão de áudio (click + touchstart) e estado “gravando”
  try {
    const tb = quill.getModule("toolbar");
    const btn = tb?.container?.querySelector?.(".ql-audio");

    if (btn) {
      btn.setAttribute("type", "button");
      btn.setAttribute("title", "Gravar áudio");
      btn.setAttribute("aria-label", "Gravar áudio");
      btn.classList.toggle("is-recording", !!window.__cmAudioRec.recording);

      const fire = (e) => {
        e.preventDefault();
        e.stopPropagation();
        toggleAudioRecording(quill);
      };

      // remove binds antigos (click + touchstart) se o DOM reusar
      if (btn.__cmAudioHandlers?.click) {
        btn.removeEventListener("click", btn.__cmAudioHandlers.click, true);
      }
      if (btn.__cmAudioHandlers?.touch) {
        btn.removeEventListener("touchstart", btn.__cmAudioHandlers.touch, true);
      }

      btn.addEventListener("click", fire, true);
      btn.addEventListener("touchstart", fire, { passive: false, capture: true });

      btn.__cmAudioHandlers = { click: fire, touch: fire };
    } else {
      console.warn("[activity-audio] .ql-audio não encontrado");
    }
  } catch (e) {
    console.error("[activity-audio] erro ao bindar botão", e);
  }

  // handler do toolbar (mantém compatibilidade com o mecanismo do Quill)
  try {
    const toolbar = quill.getModule("toolbar");
    if (toolbar) toolbar.addHandler("audio", () => toggleAudioRecording(quill));
  } catch (_e) {}

  window[STATE_KEY] = quill;
  window[STATE_EL_KEY] = el;

  // auto-grow
  const container = quill.root.closest(".ql-container");
  if (container) delete container.dataset.cmManualMinHeight;
  autoGrowQuill(quill, { min: 140, max: 3000 });
}








// ============================================================
// AUDIO (Gravação + Upload como anexo + Inserção de link no Quill)
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
    try { alert(msg); } catch (_e) {}
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
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/ogg",
  ];
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

async function uploadFileAndInsertLink(quill, file, description) {
  const cardId = getCardId();
  if (!cardId) throw new Error("cardId ausente.");

  const uploadUrl = `/card/${cardId}/attachments/add/`;

  const form = new FormData();
  form.append("file", file);
  form.append("description", description || "Áudio gravado na atividade");

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

  const list = document.getElementById("attachments-list");
  if (list) list.insertAdjacentHTML("beforeend", html);

  const tmp = document.createElement("div");
  tmp.innerHTML = html;

  const a = tmp.querySelector("a[href]");
  const img = tmp.querySelector("img[src]");
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

/**
 * Ajusta capture APENAS no mobile.
 * - Android: "microphone" costuma funcionar melhor.
 * - iOS: "user" ou sem capture varia; mantemos "user" como tentativa.
 * - Desktop: remove capture (evita quebrar picker/fluxo).
 */
function configureCaptureAttribute(input) {
  try { input.removeAttribute("capture"); } catch (_e) {}

  if (!isMobileUA()) return;

  if (isAndroidUA()) {
    try { input.setAttribute("capture", "microphone"); } catch (_e) {}
  } else {
    // iOS (não testado por você): tentativa conservadora
    try { input.setAttribute("capture", "user"); } catch (_e) {}
  }
}

async function startAudioRecording(quill) {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("Gravação não suportada (getUserMedia indisponível).");
  }

  // getUserMedia exige https (exceto localhost)
  const isSecure = (location.protocol === "https:" || location.hostname === "localhost");
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

  try { window.__cmAudioRec.stream?.getTracks?.().forEach((t) => t.stop()); } catch (_e) {}

  window.__cmAudioRec.recording = false;
  window.__cmAudioRec.recorder = null;
  window.__cmAudioRec.stream = null;
  window.__cmAudioRec.chunks = [];
  setAudioButtonRecordingUI(quill, false);

  const ext = fileExtFromMime(mime);
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const file = new File([blob], `audio-${ts}.${ext}`, { type: mime || "audio/webm" });

  await uploadFileAndInsertLink(quill, file, "Áudio gravado na atividade");
}

async function fallbackCaptureAudioFile(quill) {
  const input = ensureAudioFileInput();
  configureCaptureAttribute(input);

  input.value = "";
  input.onchange = async () => {
    try {
      const file = input.files && input.files[0];
      if (!file) return;
      await uploadFileAndInsertLink(quill, file, "Áudio enviado na atividade");
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
    const isSecure = (location.protocol === "https:" || location.hostname === "localhost");

    // Se não tiver caminho “real” de gravação, cai no fallback (Android em HTTP/IP local, Safari, etc.)
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
    try { window.__cmAudioRec.stream?.getTracks?.().forEach((t) => t.stop()); } catch (_e) {}

    window.__cmAudioRec.stream = null;
    window.__cmAudioRec.recorder = null;
    window.__cmAudioRec.chunks = [];

    notifyActivityError(err?.message || "Erro ao gravar/enviar áudio.");
  }
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

      const html = syncToHidden();

      if (evt.detail && evt.detail.parameters) {
        evt.detail.parameters["content"] = html;
        if (replyTo) evt.detail.parameters["reply_to"] = replyTo;
      }
    });


    form.addEventListener("htmx:afterRequest", function (evt) {
      if (evt.detail?.successful === true) {
        // ✅ corrige “Nenhuma atividade ainda” sem F5
        try {
          const resp = evt.detail?.xhr?.responseText || "";
          applyPostSuccessActivityUI(resp);
        } catch (_e) {}

        resetEditor();
        clearActivityError();
        clearReplyContext();
        closeComposer(); // ✅ após incluir, volta a ocultar
      }
    });
  }

  function initActivityModule() {
    if (!isActivityTabActive()) return;

    // ✅ garante que o form esteja bindado mesmo com composer fechado
    bindActivityForm();

    // ✅ só monta Quill quando composer abrir
    if (isComposerOpen()) ensureQuill();
  }

  // ============================================================
  // GATILHO 1: click direto na aba "Atividade" (delegado)
  // ============================================================
  document.addEventListener(
    "click",
    function (e) {
      const btn = e.target?.closest?.('.cm-tabbtn[data-cm-tab="ativ"]');
      if (!btn) return;

      // deixa o script das tabs ativar a aba primeiro, depois inicializa
      setTimeout(initActivityModule, 0);
      setTimeout(initActivityModule, 50);
    },
    true
  );

  // ============================================================
  // GATILHO 2: evento de tabchange (se existir)
  // ============================================================
  getRoot()?.addEventListener("cm:tabchange", function (e) {
    if (e.detail?.tab === "ativ") {
      setTimeout(initActivityModule, 0);
      setTimeout(initActivityModule, 50);
    }
  });


    // ============================================================
  // ATIVIDADE (LISTA) — limpar espaços “fantasmas” do HTML do log
  // Remove <p><br></p>, <p>&nbsp;</p> e blocos vazios no começo/fim
  // ============================================================
  function cleanupActivityLogSpacing() {
    try {
      const wrapper =
        document.getElementById("activity-panel-wrapper") ||
        document.querySelector("#cm-activity-panel") ||
        document.querySelector("#activity-panel-wrapper");

      if (!wrapper) return;

      const contentBlocks = wrapper.querySelectorAll(
        ".activity-content, .cm-activity-content"
      );

      const isEmptyParagraph = (p) => {
        if (!p) return true;

        // Texto “visível” (remove espaços e NBSP unicode)
        const txt = (p.textContent || "").replace(/\u00A0/g, " ").trim();

        // HTML interno “normalizado” (remove whitespace e &nbsp;)
        const html = (p.innerHTML || "")
          .replace(/\u00A0/g, " ")
          .replace(/&nbsp;/gi, " ")
          .replace(/\s+/g, "")
          .toLowerCase();

        // Casos clássicos do Quill
        if (html === "" || html === "<br>" || html === "<br/>" || html === "<br/>") return true;

        // Se não tem texto e só tem BR(s)
        if (txt === "") {
          const onlyBr =
            p.querySelectorAll("*").length === p.querySelectorAll("br").length &&
            p.querySelectorAll("br").length >= 1;
          if (onlyBr) return true;
        }

        // Ex.: <p>&nbsp;</p> ou <p> </p>
        if (txt === "" && html === "") return true;

        return false;
      };

      contentBlocks.forEach((block) => {
        // 1) Remove todos os <p> vazios do bloco
        const ps = Array.from(block.querySelectorAll("p"));
        ps.forEach((p) => {
          if (isEmptyParagraph(p)) p.remove();
        });

        // 2) Remove <br> solto que sobrou no começo/fim do bloco
        const killEdgeBr = () => {
          // início
          while (block.firstChild) {
            const n = block.firstChild;
            if (n.nodeType === 3 && (n.textContent || "").trim() === "") {
              n.remove();
              continue;
            }
            if (n.nodeType === 1 && n.tagName === "BR") {
              n.remove();
              continue;
            }
            break;
          }

          // fim
          while (block.lastChild) {
            const n = block.lastChild;
            if (n.nodeType === 3 && (n.textContent || "").trim() === "") {
              n.remove();
              continue;
            }
            if (n.nodeType === 1 && n.tagName === "BR") {
              n.remove();
              continue;
            }
            break;
          }
        };

        killEdgeBr();
      });
    } catch (_e) {}
  }

  // ============================================================
  // GATILHO 3: modal renderizado / swaps do HTMX
  // ============================================================
  function afterModalPaint() {
    setTimeout(initActivityModule, 0);
    setTimeout(initActivityModule, 50);
    setTimeout(initActivityModule, 150); // ✅ último “tiro” quando CSS/layout estabiliza

    // ✅ estado inicial: composer oculto (se existir no template)
    setTimeout(function () {
      const composer = getComposerEl();
      const btn = getToggleBtn();
      if (composer && !composer.classList.contains("is-hidden")) {
        closeComposer();
      } else if (btn) {
        btn.setAttribute("aria-expanded", isComposerOpen() ? "true" : "false");
      }
    }, 0);
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

    // ✅ sempre tenta inicializar depois do swap (mas só efetiva se aba ativ)
    afterModalPaint();

    // ✅ e garante rebind do form mesmo que não esteja na aba ainda
    setTimeout(bindActivityForm, 0);
  });
})();

// ============================================================
// END /boards/static/modal/modal.acitivity_quill.js
// ============================================================
