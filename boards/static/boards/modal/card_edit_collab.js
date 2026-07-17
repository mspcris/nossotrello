// boards/static/boards/modal/card_edit_collab.js
//
// ======================================================================
// Edição colaborativa (soft lock + live preview via WS)  — Phase 5
// ----------------------------------------------------------------------
// Cada campo editável do modal (title, description) tem um "dono" efêmero
// enquanto está focado:
//
//   focus  -> POST /card/<id>/field/<name>/lock/    (Redis SETNX TTL 15s)
//            -> publica "card.field.locked"  (bridge -> board_<id>)
//            -> outros clientes veem o campo em read-only + overlay
//
//   input  -> POST .../typing/                     (throttled 150ms)
//            -> renova TTL + publica "card.field.typing" {value}
//            -> outros clientes recebem preview ao vivo
//
//   blur   -> POST .../release/                    (salva no DB)
//            -> publica "card.field.released" {value}
//            -> outros clientes: remove overlay, aplica valor final
//
// Eventos chegam do board.ws.js como CustomEvent no window:
//   window.addEventListener("board:card.field.locked",   (e) => ...)
//   window.addEventListener("board:card.field.typing",   (e) => ...)
//   window.addEventListener("board:card.field.released", (e) => ...)
// ======================================================================

(function () {
  if (window.__CARD_EDIT_COLLAB_INSTALLED__) return;
  window.__CARD_EDIT_COLLAB_INSTALLED__ = true;

  const THROTTLE_MS = 150;
  const HEARTBEAT_MS = 8000;
  const DEBUG = false;

  const log = (...a) => DEBUG && console.log("[card_edit_collab]", ...a);

  // ============================================================
  // Estado local: um "controller" por campo ativo no modal
  //   controllers[fieldKey] = { field, cardId, el, ownedByMe, remoteOverlay }
  // fieldKey = `${cardId}:${field}`
  // ============================================================
  const controllers = new Map();

  function getMe() {
    return Number(window.CURRENT_USER_ID || 0);
  }

  function getCsrfToken() {
    const name = "csrftoken=";
    const parts = (document.cookie || "").split(";");
    for (const p of parts) {
      const s = p.trim();
      if (s.startsWith(name)) return s.slice(name.length);
    }
    return "";
  }

  async function postForm(url, params) {
    const body = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => body.append(k, v ?? ""));
    try {
      const res = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCsrfToken(),
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: body.toString(),
      });
      const ct = (res.headers.get("content-type") || "").toLowerCase();
      const data = ct.includes("application/json") ? await res.json() : null;
      return { ok: res.ok, status: res.status, data };
    } catch (e) {
      log("postForm falhou", url, e);
      return { ok: false, status: 0, data: null };
    }
  }

  function throttle(fn, ms) {
    let lastCall = 0;
    let pendingArgs = null;
    let timer = null;
    return function (...args) {
      const now = Date.now();
      const since = now - lastCall;
      if (since >= ms) {
        lastCall = now;
        fn.apply(null, args);
      } else {
        pendingArgs = args;
        if (!timer) {
          timer = setTimeout(() => {
            timer = null;
            lastCall = Date.now();
            if (pendingArgs) {
              const a = pendingArgs;
              pendingArgs = null;
              fn.apply(null, a);
            }
          }, ms - since);
        }
      }
    };
  }

  // ============================================================
  // Overlay read-only — renderizado absolutamente sobre o campo
  // ============================================================
  function ensureOverlay(el) {
    let wrap = el.parentNode;
    if (!wrap) return null;

    if (getComputedStyle(wrap).position === "static") {
      wrap.style.position = "relative";
    }

    let ov = wrap.querySelector(":scope > .cm-collab-overlay");
    if (!ov) {
      ov = document.createElement("div");
      ov.className = "cm-collab-overlay";
      ov.style.cssText = [
        "position:absolute",
        "inset:0",
        "display:flex",
        "align-items:flex-start",
        "justify-content:flex-end",
        "padding:6px 10px",
        "pointer-events:none",
        "z-index:5",
        "background:rgba(80,180,255,.06)",
        "border:1px dashed rgba(80,180,255,.45)",
        "border-radius:8px",
      ].join(";");

      const badge = document.createElement("span");
      badge.className = "cm-collab-badge";
      badge.style.cssText = [
        "background:rgba(80,180,255,.95)",
        "color:#0b1220",
        "font-weight:800",
        "font-size:11px",
        "padding:3px 8px",
        "border-radius:999px",
        "box-shadow:0 2px 8px rgba(0,0,0,.25)",
        "pointer-events:none",
        "white-space:nowrap",
      ].join(";");
      badge.textContent = "✏️ Editando…";
      ov.appendChild(badge);

      wrap.appendChild(ov);
    }
    return ov;
  }

  function showOverlay(el, holderLabel) {
    const ov = ensureOverlay(el);
    if (!ov) return;
    const badge = ov.querySelector(".cm-collab-badge");
    if (badge) badge.textContent = `✏️ ${holderLabel || "Alguém"} editando…`;
    ov.style.display = "flex";
  }

  function hideOverlay(el) {
    const wrap = el.parentNode;
    if (!wrap) return;
    const ov = wrap.querySelector(":scope > .cm-collab-overlay");
    if (ov) ov.style.display = "none";
  }

  function setReadOnly(el, readOnly) {
    if (!el) return;
    if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
      el.readOnly = !!readOnly;
    } else if (el.isContentEditable || el.getAttribute("contenteditable") !== null) {
      el.setAttribute("contenteditable", readOnly ? "false" : "true");
    }
    el.classList.toggle("cm-collab-readonly", !!readOnly);
  }

  // ============================================================
  // Helpers para localizar o elemento "visível" do campo
  //   title       -> <input name="title"> OU <input name="card_title">
  //   description -> .ql-editor (contenteditable do Quill)
  // ============================================================
  function findTitleInput(root) {
    // o título virou <textarea> (quebra em várias linhas); mantém compat com
    // <input> antigo. .value funciona nos dois.
    return (
      root.querySelector('[name="title"][data-cm-edit-field]') ||
      root.querySelector('[name="card_title"][data-cm-edit-field]') ||
      root.querySelector('input[name="title"], textarea[name="title"]') ||
      root.querySelector('input[name="card_title"], textarea[name="card_title"]')
    );
  }

  function findDescriptionEditor(root) {
    // Quill cria .ql-editor dentro do host .cm-quill/.ql-container
    return (
      root.querySelector(".cm-quill .ql-editor") ||
      root.querySelector("#quill-editor .ql-editor") ||
      root.querySelector(".ql-container .ql-editor")
    );
  }

  function getFieldValue(field, el) {
    if (!el) return "";
    if (field === "title") return String(el.value || "");
    if (field === "description") return String(el.innerHTML || "");
    return "";
  }

  function setFieldValue(field, el, value) {
    if (!el) return;
    if (field === "title") {
      el.value = String(value || "");
    } else if (field === "description") {
      el.innerHTML = String(value || "");
    }
  }

  // ============================================================
  // Controller por campo — bind de focus/input/blur
  // ============================================================
  function bindField(opts) {
    const { cardId, field, el } = opts;
    if (!el || !cardId || !field) return;
    if (el.dataset.collabBound === "1") return;
    el.dataset.collabBound = "1";

    const key = `${cardId}:${field}`;
    const ctrl = {
      cardId,
      field,
      el,
      ownedByMe: false,
      remoteHolder: null,
      heartbeatTimer: null,
    };
    controllers.set(key, ctrl);

    const urlLock = `/card/${cardId}/field/${field}/lock/`;
    const urlTyping = `/card/${cardId}/field/${field}/typing/`;
    const urlRelease = `/card/${cardId}/field/${field}/release/`;

    async function acquireLock() {
      if (ctrl.remoteHolder && ctrl.remoteHolder.user_id !== getMe()) {
        // já sabemos que outro tem — não tenta
        return false;
      }
      const value = getFieldValue(field, el);
      const res = await postForm(urlLock, { value });
      if (res.ok && res.data && res.data.ok) {
        ctrl.ownedByMe = true;
        startHeartbeat();
        return true;
      }
      if (res.status === 409 && res.data && res.data.holder) {
        ctrl.remoteHolder = res.data.holder;
        const name = res.data.holder.display_name || res.data.holder.username || "Alguém";
        showOverlay(el, name);
        setReadOnly(el, true);
        el.blur();
      }
      return false;
    }

    function startHeartbeat() {
      stopHeartbeat();
      ctrl.heartbeatTimer = setInterval(() => {
        if (!ctrl.ownedByMe) return;
        const value = getFieldValue(field, el);
        postForm(urlTyping, { value }).then((r) => {
          if (!r.ok && r.status === 409) {
            // perdi o lock
            ctrl.ownedByMe = false;
            stopHeartbeat();
          }
        });
      }, HEARTBEAT_MS);
    }

    function stopHeartbeat() {
      if (ctrl.heartbeatTimer) {
        clearInterval(ctrl.heartbeatTimer);
        ctrl.heartbeatTimer = null;
      }
    }

    const sendTyping = throttle(() => {
      if (!ctrl.ownedByMe) return;
      const value = getFieldValue(field, el);
      postForm(urlTyping, { value });
    }, THROTTLE_MS);

    async function releaseLock() {
      stopHeartbeat();
      if (!ctrl.ownedByMe) return;
      ctrl.ownedByMe = false;
      const value = getFieldValue(field, el);
      await postForm(urlRelease, { value });
    }

    // --- Listeners no elemento ---
    const onFocus = () => {
      if (ctrl.remoteHolder && ctrl.remoteHolder.user_id !== getMe()) {
        el.blur();
        return;
      }
      acquireLock();
    };

    const onInput = () => {
      if (!ctrl.ownedByMe) {
        // tenta adquirir na primeira batida (ex.: colar antes de focar)
        acquireLock().then((got) => {
          if (got) sendTyping();
        });
        return;
      }
      sendTyping();
    };

    const onBlur = () => {
      releaseLock();
    };

    if (field === "title") {
      el.addEventListener("focus", onFocus);
      el.addEventListener("input", onInput);
      el.addEventListener("blur", onBlur);
    } else if (field === "description") {
      // Quill .ql-editor é contenteditable. Eventos funcionam normalmente.
      el.addEventListener("focus", onFocus, true);
      el.addEventListener("input", onInput);
      el.addEventListener("blur", onBlur, true);
    }

    log("bound", field, "card", cardId);
  }

  // ============================================================
  // Recebe eventos WS e aplica preview nos campos remotos
  // ============================================================
  function findCtrl(cardId, field) {
    return controllers.get(`${cardId}:${field}`) || null;
  }

  function onLocked(e) {
    const p = e.detail || {};
    const ctrl = findCtrl(p.card_id, p.field);
    if (!ctrl) return;
    const myId = getMe();
    const holderId = Number((p.user && p.user.id) || 0);
    if (holderId === myId) return; // é meu, ignora

    ctrl.remoteHolder = p.user || null;
    ctrl.ownedByMe = false;
    const name = (p.user && (p.user.display_name || p.user.username)) || "Alguém";
    showOverlay(ctrl.el, name);
    setReadOnly(ctrl.el, true);
    if (p.value != null) setFieldValue(ctrl.field, ctrl.el, p.value);
  }

  function onTyping(e) {
    const p = e.detail || {};
    const ctrl = findCtrl(p.card_id, p.field);
    if (!ctrl) return;
    const myId = getMe();
    const holderId = Number((p.user && p.user.id) || 0);
    if (holderId === myId) return;
    if (p.value != null) setFieldValue(ctrl.field, ctrl.el, p.value);
  }

  function onReleased(e) {
    const p = e.detail || {};
    const ctrl = findCtrl(p.card_id, p.field);
    if (!ctrl) return;
    const myId = getMe();
    const holderId = Number((p.user && p.user.id) || 0);
    if (holderId === myId) return;
    ctrl.remoteHolder = null;
    hideOverlay(ctrl.el);
    setReadOnly(ctrl.el, false);
    if (p.value != null) setFieldValue(ctrl.field, ctrl.el, p.value);
  }

  window.addEventListener("board:card.field.locked", onLocked);
  window.addEventListener("board:card.field.typing", onTyping);
  window.addEventListener("board:card.field.released", onReleased);

  // ============================================================
  // Bind/unbind no ciclo do modal
  // ============================================================
  function clearControllers() {
    controllers.forEach((ctrl) => {
      try {
        if (ctrl.heartbeatTimer) clearInterval(ctrl.heartbeatTimer);
      } catch (_e) {}
    });
    controllers.clear();
  }

  function bindAll() {
    const modal = document.getElementById("modal-body") || document;
    const root = document.getElementById("cm-root") || modal;

    // Descobre card_id a partir do cm-root (usa o attr existente data-card-id).
    let cardId =
      Number(root.getAttribute("data-card-id") || 0) ||
      Number(root.dataset.cmCardId || 0) ||
      0;

    if (!cardId) {
      // fallback: extrai do URL /board/<id>/?card=<id>
      try {
        const params = new URLSearchParams(window.location.search);
        cardId = Number(params.get("card") || 0);
      } catch (_e) {}
    }

    if (!cardId) {
      log("sem cardId — não binda");
      return;
    }

    // Título
    const titleEl = findTitleInput(root);
    if (titleEl) bindField({ cardId, field: "title", el: titleEl });

    // Descrição (Quill). Pode ainda não estar montado — tenta agora
    // e repete após um rAF.
    const tryDesc = () => {
      const descEl = findDescriptionEditor(root);
      if (descEl) bindField({ cardId, field: "description", el: descEl });
    };
    tryDesc();
    requestAnimationFrame(tryDesc);
    setTimeout(tryDesc, 200);
    setTimeout(tryDesc, 600);
  }

  // Rebind a cada swap do modal
  document.body.addEventListener("htmx:afterSwap", function (e) {
    const target = e?.target;
    if (!target) return;
    if (target.id === "modal-body" || target.closest?.("#modal-body")) {
      clearControllers();
      bindAll();
    }
  });

  // Se o modal for fechado (custom event), limpa
  document.addEventListener("modal:closed", function () {
    // Libera meus locks antes de limpar (best-effort, não aguarda)
    controllers.forEach((ctrl) => {
      if (ctrl.ownedByMe) {
        try {
          const value = getFieldValue(ctrl.field, ctrl.el);
          postForm(`/card/${ctrl.cardId}/field/${ctrl.field}/release/`, { value });
        } catch (_e) {}
      }
    });
    clearControllers();
  });

  // Init inicial
  document.addEventListener("DOMContentLoaded", bindAll);
  setTimeout(bindAll, 0);
})();
