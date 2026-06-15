// boards/static/boards/modal/user.ws.js
//
// ======================================================================
// WebSocket pessoal do usuário — realtime sem polling (Phase 3 pub/sub)
// ----------------------------------------------------------------------
// Conecta em /ws/me/ e recebe eventos que são específicos do usuário
// logado, não de um board:
//
//   - chat.message.created       -> nova mensagem no chat direto
//   - chat.message.seen          -> outro lado leu mensagem
//   - chat.unread.changed        -> badge global do chat mudou
//   - notification.created       -> nova notificação (header bell)
//   - tracktime.me.changed       -> meu próprio timer começou/parou
//   - social.pill.changed        -> pill de visitors/posts/curtidas
//
// Estratégia: o consumer recebe o evento e re-emite como CustomEvent
// no `window`, para que cada tela escute o que lhe interessa sem
// precisar conhecer o protocolo do WebSocket.
//
// Exemplo de uso em outro script:
//     window.addEventListener("user:chat.message.created", (e) => {
//       const payload = e.detail;
//       // ... atualizar UI ...
//     });
//
// Fallback: mesmo esquema do board.ws.js — reconnect exponencial +
// mode degradado (nenhum polling agressivo; os pollings existentes
// continuam como fallback lento no código legado).
// ======================================================================

(function () {
  if (window.__USER_WS_INSTALLED__) return;
  window.__USER_WS_INSTALLED__ = true;

  const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 16000, 30000];
  // Limite de tentativas: se o WS não sobe, para de tentar (não inunda o console).
  const MAX_RECONNECT_ATTEMPTS = 3;
  // Só zera o contador depois da conexão se sustentar por este tempo — senão
  // um WS que sobe (101) e cai logo (flapping) reconectaria pra sempre.
  const STABLE_MS = 10000;

  let ws = null;
  let reconnectAttempt = 0;
  let pingTimer = null;
  let stableTimer = null;
  let closedByClient = false;

  function log(...args) {
    if (window.DEBUG_USER_WS || window.__NT_DEBUG) console.log("[user.ws]", ...args);
  }

  function wsUrl() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/ws/me/`;
  }

  function handleEvent(evt) {
    const t = (evt && evt.type) || "";
    log("event", t, evt);

    // eventos internos do consumer
    if (t === "hello" || t === "pong") return;

    // Re-emite como CustomEvent no window para que os templates escutem
    try {
      window.dispatchEvent(
        new CustomEvent(`user:${t}`, { detail: evt })
      );
    } catch (e) {
      log("dispatch falhou", e);
    }
  }

  function scheduleReconnect() {
    if (closedByClient) return;
    if (reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      log("reconnect: limite atingido — desisto do WS");
      return;
    }
    const idx = Math.min(reconnectAttempt, RECONNECT_DELAYS_MS.length - 1);
    const delay = RECONNECT_DELAYS_MS[idx];
    reconnectAttempt++;
    log(`reconnect in ${delay}ms (attempt ${reconnectAttempt})`);
    setTimeout(connect, delay);
  }

  function connect() {
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
      startPing();
      // Zera o contador SÓ após STABLE_MS de conexão estável (anti-flapping).
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
      if (ev.code === 4401 || ev.code === 4403 || ev.code === 4400) return;
      scheduleReconnect();
    });

    ws.addEventListener("error", (ev) => {
      log("error", ev);
    });
  }

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

  document.addEventListener("DOMContentLoaded", () => {
    // Só conecta se o usuário estiver autenticado.
    // A página injeta window.USER_ID no base.html. Se não existe, pula.
    if (!window.USER_ID) {
      log("sem USER_ID — desabilitado");
      return;
    }
    connect();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      closedByClient = false;
      reconnectAttempt = 0;
      connect();
    }
  });

  window.__UserWS = {
    connect,
    get state() {
      return ws ? ["CONNECTING","OPEN","CLOSING","CLOSED"][ws.readyState] : "NULL";
    },
  };
})();
