// boards/static/boards/modal/board.ws.js
//
// ======================================================================
// WebSocket realtime — board sync (Phase 1 pub/sub)
// ----------------------------------------------------------------------
// Substitui o antigo polling de 60s em board.poll.js. Escuta eventos
// push-based vindos do RabbitMQ via Django Channels:
//
//   - board.invalidated   -> versão mudou, re-renderiza colunas
//   - card.activity       -> novo log/comentário, atualiza badges
//   - access.request.*    -> painel do owner
//   - tracktime.changed   -> badges de track-time
//
// Fallback: se a conexão nunca entrar (ou cair por > 30s), reativa um
// polling LENTO de 300s como rede de segurança — nunca o modo normal.
//
// Como integra:
//   - board_detail.html expõe window.BOARD_ID e window.BOARD_VERSION
//   - base.html inclui este script após board.poll.js
//   - As funções `syncUnreadBadge`, `syncCardUnreadBadges`,
//     `syncAccessRequests`, `tickTrackTimeBadges` continuam existindo
//     no board.poll.js e são reusadas aqui — mas NÃO são mais chamadas
//     em setInterval. Só em resposta a eventos WS.
// ======================================================================

(function () {
  if (window.__BOARD_WS_INSTALLED__) return;
  window.__BOARD_WS_INSTALLED__ = true;

  // ============================================================
  // BOARD_WS_FALLBACK_MS
  // - POLL DE SEGURANÇA (só dispara se WS estiver morto)
  // - NUNCA roda quando WS está OK
  // ============================================================
  const BOARD_WS_FALLBACK_MS = 300000; // 5 minutos

  // backoff exponencial de reconexão: 1s, 2s, 4s, 8s, 16s, 30s (cap)
  const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 16000, 30000];
  // Limite de tentativas: se o WS não sobe (ex.: close 1006), para de tentar
  // p/ não inundar o console com erros nativos do navegador. O polling assume.
  const MAX_RECONNECT_ATTEMPTS = 3;
  // Só considera a conexão "boa" (e zera o contador) depois de ficar aberta
  // por este tempo. Sem isso, um WS que sobe (101) e cai logo — flapping do
  // proxy/Daphne — zeraria o contador a cada ciclo e reconectaria pra sempre.
  const STABLE_MS = 10000;

  // ============================================================
  // Estado
  // ============================================================
  let ws = null;
  let reconnectAttempt = 0;
  let fallbackTimer = null;
  let pingTimer = null;
  let stableTimer = null;
  let lastMessageAt = 0;
  let boardVersion = 0;
  let boardId = null;
  let closedByClient = false;

  function getBoardId() {
    if (window.BOARD_ID) return Number(window.BOARD_ID);
    const fromBody = document.body?.dataset?.boardId;
    if (fromBody) return Number(fromBody);
    return null;
  }

  function getColumnsList() {
    return document.getElementById("columns-list");
  }

  function log(...args) {
    if (window.DEBUG_BOARD_WS || window.__NT_DEBUG) console.log("[board.ws]", ...args);
  }

  // ============================================================
  // Fetch de colunas (mesma lógica do polling antigo, mas só
  // dispara quando o servidor MANDA via WebSocket)
  // ============================================================
  async function applyBoardInvalidation(newVersion) {
    if (!boardId) return;

    // Se já estou na versão recebida, nada a fazer (dedupe).
    if (Number(newVersion) > 0 && Number(newVersion) <= boardVersion) {
      log("skip: versão recebida <= atual", newVersion, boardVersion);
      return;
    }

    // Respeita as mesmas pausas do polling antigo (modal aberto, drag, input focado).
    if (window.Modal?.state?.isOpen) { log("pause: modal aberto"); return; }
    if (window.__isDraggingCard)    { log("pause: dragging");    return; }
    const ae = document.activeElement;
    if (ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA" || ae.isContentEditable)) {
      log("pause: input focado"); return;
    }
    // Cooldown pós-drag (evita snap-back)
    const sinceLastDrag = Date.now() - (window.__lastDragEndMs || 0);
    if (sinceLastDrag < 3000) { log("pause: drag cooldown"); return; }

    const list = getColumnsList();
    if (!list) return;

    try {
      const res = await fetch(`/board/${boardId}/poll/?v=${boardVersion}`, {
        method: "GET",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" },
        cache: "no-store",
      });
      if (!res.ok) return;

      const data = await res.json();
      if (!data || !data.changed) return;

      // Race final: modal abriu durante o request
      if (window.Modal?.state?.isOpen) return;

      if (data.html && String(data.html).trim()) {
        list.outerHTML = data.html;
      }
      boardVersion = Number(data.version || boardVersion);
      window.BOARD_VERSION = boardVersion;

      // rehidrata HTMX/Sortable/TagColors
      const newList = getColumnsList();
      if (window.BoardRuntime?.ensure) {
        window.BoardRuntime.ensure(newList || document);
      } else {
        try { window.htmx?.process?.(newList || document); } catch (_) {}
        try { window.initSortable?.(); } catch (_) {}
        try { window.initSortableColumns?.(); } catch (_) {}
        try { window.applySavedTagColorsToBoard?.(document); } catch (_) {}
      }
      log("applied board.invalidated ->", boardVersion);
    } catch (e) {
      log("fetch poll falhou", e);
    }
  }

  // ============================================================
  // Dispatcher dos eventos recebidos do servidor
  // ============================================================
  function handleEvent(evt) {
    lastMessageAt = Date.now();
    const t = (evt && evt.type) || "";
    log("event", t, evt);

    // Re-emite TODO evento como CustomEvent `board:<type>` no window.
    // Isso permite que módulos novos (ex: card_edit_collab.js) escutem
    // sem precisar hardcode aqui — e os casos específicos abaixo
    // continuam tratados.
    if (t && t !== "hello" && t !== "pong") {
      try {
        window.dispatchEvent(new CustomEvent(`board:${t}`, { detail: evt }));
      } catch (_e) {}
    }

    switch (t) {
      case "hello":
      case "pong":
        return;

      case "board.invalidated":
        // re-renderiza se for pro meu board
        if (Number(evt.board_id) !== boardId) return;
        applyBoardInvalidation(Number(evt.version || 0));
        return;

      case "card.activity":
        if (Number(evt.board_id) !== boardId) return;
        // Reusa as funções já existentes do board.poll.js.
        // Mas primeiro força o throttle zerado pra elas dispararem agora.
        try {
          if (typeof window.syncCardUnreadBadges === "function") {
            window.syncCardUnreadBadges(boardId);
          }
        } catch (_) {}
        try {
          if (typeof window.syncUnreadBadge === "function") {
            // reset do throttle interno e chama
            window.__lastUnreadFetchMs = 0;
            window.syncUnreadBadge(boardId);
          }
        } catch (_) {}
        return;

      case "access.request.changed":
        if (Number(evt.board_id) !== boardId) return;
        try {
          window.__lastAccessFetchMs = 0;
          if (typeof window.syncAccessRequests === "function") {
            window.syncAccessRequests(boardId);
          }
        } catch (_) {}
        return;

      case "tracktime.changed":
        if (Number(evt.board_id) !== boardId) return;
        try {
          window.__ttLastFetchMs = 0;
          if (typeof window.tickTrackTimeBadges === "function") {
            window.tickTrackTimeBadges(boardId);
          }
        } catch (_) {}
        return;

      default:
        log("unknown event type", t);
    }
  }

  // ============================================================
  // Conexão
  // ============================================================
  function wsUrl() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/ws/board/${boardId}/`;
  }

  function scheduleReconnect() {
    if (closedByClient) return;
    if (reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      log("reconnect: limite atingido — desisto do WS, fico no polling");
      startFallbackPolling();
      return;
    }
    const idx = Math.min(reconnectAttempt, RECONNECT_DELAYS_MS.length - 1);
    const delay = RECONNECT_DELAYS_MS[idx];
    reconnectAttempt++;
    log(`reconnect in ${delay}ms (attempt ${reconnectAttempt})`);
    setTimeout(connect, delay);
  }

  function connect() {
    if (!boardId) return;
    if (closedByClient) return;
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    try {
      ws = new WebSocket(wsUrl());
    } catch (e) {
      log("new WebSocket falhou", e);
      scheduleReconnect();
      return;
    }

    ws.addEventListener("open", () => {
      log("open");
      lastMessageAt = Date.now();
      stopFallbackPolling();
      startPing();
      // Zera o contador SÓ se a conexão se sustentar STABLE_MS. Se cair antes
      // (flapping), o contador NÃO zera e o cap engata após MAX_RECONNECT_ATTEMPTS.
      clearTimeout(stableTimer);
      stableTimer = setTimeout(() => {
        reconnectAttempt = 0;
        log("conexão estável — contador de reconexão zerado");
      }, STABLE_MS);
    });

    ws.addEventListener("message", (ev) => {
      try {
        const data = JSON.parse(ev.data);
        handleEvent(data);
      } catch (e) {
        log("parse message falhou", e);
      }
    });

    ws.addEventListener("close", (ev) => {
      log("close", ev.code, ev.reason);
      clearTimeout(stableTimer);
      stopPing();
      ws = null;
      // 4401/4403: auth/permission — não adianta reconectar
      if (ev.code === 4401 || ev.code === 4403 || ev.code === 4400) {
        startFallbackPolling();
        return;
      }
      startFallbackPolling();
      scheduleReconnect();
    });

    ws.addEventListener("error", (ev) => {
      log("error", ev);
      // deixa o handler de close tomar a decisão
    });
  }

  function disconnect() {
    closedByClient = true;
    clearTimeout(stableTimer);
    stopPing();
    stopFallbackPolling();
    try { ws && ws.close(); } catch (_) {}
    ws = null;
  }

  // ============================================================
  // Keepalive (ping)
  // - Alguns proxies matam conexões ociosas apesar do proxy_read_timeout.
  // - Envia {type:"ping"} a cada 25s; consumer responde com {type:"pong"}.
  // ============================================================
  function startPing() {
    stopPing();
    pingTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        try { ws.send(JSON.stringify({ type: "ping" })); } catch (_) {}
      }
    }, 25000);
  }
  function stopPing() {
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
  }

  // ============================================================
  // Fallback de polling (5 min) — só dispara com WS morto
  // ============================================================
  function fallbackTick() {
    // Se reconectou, para imediatamente.
    if (ws && ws.readyState === WebSocket.OPEN) {
      stopFallbackPolling();
      return;
    }
    log("fallback tick (WS down) — doing slow poll");
    applyBoardInvalidation(0);
    try {
      window.__lastUnreadFetchMs = 0;
      window.syncUnreadBadge?.(boardId);
      window.syncCardUnreadBadges?.(boardId);
      window.__lastAccessFetchMs = 0;
      window.syncAccessRequests?.(boardId);
      window.__ttLastFetchMs = 0;
      window.tickTrackTimeBadges?.(boardId);
    } catch (_) {}
  }

  function startFallbackPolling() {
    if (fallbackTimer) return;
    log(`fallback polling iniciado @ ${BOARD_WS_FALLBACK_MS}ms`);
    fallbackTimer = setInterval(fallbackTick, BOARD_WS_FALLBACK_MS);
  }
  function stopFallbackPolling() {
    if (fallbackTimer) {
      clearInterval(fallbackTimer);
      fallbackTimer = null;
      log("fallback polling parado");
    }
  }

  // ============================================================
  // Bootstrap
  // ============================================================
  function boot() {
    boardId = getBoardId();
    if (!boardId) {
      log("sem board_id — desabilitado nesta página");
      return;
    }
    boardVersion = Number(window.BOARD_VERSION || 0);
    connect();
  }

  document.addEventListener("DOMContentLoaded", boot);

  // Ao FECHAR o modal, o board pega o que mudou enquanto ele estava aberto.
  // applyBoardInvalidation ignora eventos com modal aberto (linha ~89), então
  // uma mudança feita dentro do modal (ex.: marcar impedimento) só aparecia no
  // F5. Aqui forçamos o catch-up assim que o modal sai. Pequeno atraso para o
  // Modal.state.isOpen já ter virado false.
  document.addEventListener("modal:closed", () => {
    setTimeout(() => applyBoardInvalidation(0), 60);
  });

  // Quando aba volta a ficar visível: se WS caiu, força reconnect imediato
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      log("visibility: reconnect");
      closedByClient = false;
      reconnectAttempt = 0;
      connect();
    }
  });

  // Expose pra debug
  window.__BoardWS = {
    connect,
    disconnect,
    get state() {
      return ws ? ["CONNECTING","OPEN","CLOSING","CLOSED"][ws.readyState] : "NULL";
    },
    get boardId() { return boardId; },
    get boardVersion() { return boardVersion; },
  };
})();
