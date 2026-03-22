// boards/static/boards/modal/board.poll.js

// poll solicitação de acesso a board. 
function syncAccessRequests(boardId) {
  const root = document.getElementById("cm-accessreq-root");
  if (!root) return;

  fetch(window.ACCESS_REQUESTS_POLL_URL, {
    credentials: "same-origin",
    cache: "no-store",
    headers: { "X-Requested-With": "XMLHttpRequest" }
  })


    .then(r => r.text())
    .then(html => {
      root.innerHTML = (html && html.trim()) ? html : "";
    })

    .catch(() => {});
}


// ============================================================
// BOARD POLLING — sincroniza colunas/cards entre usuários (A1)
// - Não faz swap com modal aberto / drag / foco em input
// - Rehidrata JS (HTMX + Sortable + TagColors) após swap
// - Garante “bootstrap” no load (resolve o caso: só funciona após abrir/fechar modal)
// ============================================================

let __lastUnreadCount = null;
let __lastUnreadFetchMs = 0;
// ============================================================
// UNREAD BOARD BADGE THROTTLE (UNREAD_FETCH_EVERY_MS)
// - POLLING (#TEMPO) / THROTTLE DO BADGE DE NÃO-LIDOS DO HISTÓRICO
// - Limita chamadas do syncUnreadBadge (mesmo sendo chamado em vários gatilhos)
// - Faz GET /board/<id>/history/unread-count/
// ============================================================
const UNREAD_FETCH_EVERY_MS = 60000;// 60s é mais que suficiente para     atualiazar o indicador de atividade


(function () {
  if (window.__BOARD_POLL_INSTALLED__) return;
  window.__BOARD_POLL_INSTALLED__ = true;

  // Ajuste fino: se quiser sobrescrever via console/localStorage futuramente
  // ============================================================
  // BOARD POLL (POLL_MS)
  // - POLLING (#TEMPO) DE SINCRONIZAÇÃO DA BOARD (COLUNAS/CARDS)
  // - Faz GET /board/<id>/poll/?v=<versao> e aplica swap do columns-list
  // - Pausa em: modal aberto, drag, foco em input, aba escondida
  // ============================================================
  
  
  // intervalo único do polling central
  //const POLL_MS = Number(window.BOARD_POLL_MS || 60000); // 60s
  const POLL_ENABLED = false;
  const POLL_MS = 60000;

  function getBoardId() {
    // prioridade: window.BOARD_ID (setado no board_detail)
    if (window.BOARD_ID) return Number(window.BOARD_ID);

    // fallback: body attrs (se existir)
    const fromBody = document.body?.dataset?.boardId;
    if (fromBody) return Number(fromBody);

    return null;
  }

  function getColumnsList() {
    return document.getElementById("columns-list");
  }

  function hydrate(scopeEl) {
    const scope = scopeEl || document;

    // ordem: processa HTMX no scope -> sortables -> estilos
    if (window.BoardRuntime && typeof window.BoardRuntime.ensure === "function") {
      window.BoardRuntime.ensure(scope);
      return;
    }

    if (window.htmx && typeof window.htmx.process === "function") {
      try { window.htmx.process(scope); } catch (_) {}
    }

    try { if (window.initSortable) window.initSortable(); } catch (_) {}
    try { if (window.initSortableColumns) window.initSortableColumns(); } catch (_) {}
    try {
      if (window.applySavedTagColorsToBoard) window.applySavedTagColorsToBoard(document);
    } catch (_) {}
  }

  function shouldPause() {
    if (document.hidden) return true;

    // pausa com modal aberto
    if (window.Modal?.state?.isOpen) return true;

    // pausa durante drag
    if (window.__isDraggingCard) return true;

    // pausa durante edição / foco em input/textarea/contenteditable
    const ae = document.activeElement;
    if (
      ae &&
      (ae.tagName === "INPUT" ||
        ae.tagName === "TEXTAREA" ||
        ae.isContentEditable)
    ) {
      return true;
    }

    return false;
  }

  let inFlight = false;

  // version local (fallback: body attr)
  let boardVersion = Number(document.body?.dataset?.boardVersion || window.BOARD_VERSION || 0);

  // “kick” de bootstrap: garante rehidratação no load/hard reload (Ctrl+F5)
  function bootstrapHydrate() {
    const list = getColumnsList();
    hydrate(list || document);
  }

  async function tick() {
    const boardId = getBoardId();
    if (!boardId) return;

    const list = getColumnsList();
    if (!list) return;

    // evita request quando aba não está visível
    if (document.hidden) return;

    if (shouldPause()) return;

    // badges de atividade
    syncUnreadBadge(boardId);
    syncCardUnreadBadges(boardId);

    // track-time
    tickTrackTimeBadges(boardId);

    // access requests
    const nowAccess = Date.now();
    if (nowAccess - __lastAccessFetchMs > ACCESS_FETCH_EVERY_MS) {
      __lastAccessFetchMs = nowAccess;
      syncAccessRequests(boardId);
    }

    if (inFlight) return;

    inFlight = true;

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

      // ✅ BLOQUEIO FINAL (race): se modal abriu DURANTE o request, não faz swap
      if (window.Modal?.state?.isOpen) return;

      if (data.changed && data.html && String(data.html).trim()) {
        list.outerHTML = data.html;
      }

      // atualiza versão local
      boardVersion = Number(data.version || boardVersion);
      window.BOARD_VERSION = boardVersion;

      // pega o novo nó e rehidrata
      const newList = getColumnsList();
      hydrate(newList || document);
    } catch (_e) {
      // silencioso
    } finally {
      inFlight = false;
    }
  }

  function loop() {
    if (!POLL_ENABLED) return;

    setTimeout(async () => {
      await tick();
      loop();
    }, POLL_MS);
  }


// ============================================================
// ACCESS REQUESTS POLL (ACCESS_POLL_MS)
// - POLLING (#TEMPO) DA SOLICITAÇÃO DE ACESSO AO QUADRO (PAINEL DO OWNER)
// - Não troca colunas/cards, só atualiza o bloco #cm-accessreq-root
// - Faz GET em window.ACCESS_REQUESTS_POLL_URL
// ============================================================
// - POLLING DA SOLICITAÇÃO DE ACESSO AO QUADRO
// ============================================================

// ACCESS REQUESTS passam a rodar dentro do polling central
let __lastAccessFetchMs = 0;
const ACCESS_FETCH_EVERY_MS = 60000;



  // ---- BOOTSTRAP / RESUME POINTS ----

  // 1) DOM pronto
document.addEventListener("DOMContentLoaded", () => {
  const boardId = getBoardId();


  // BOOTSTRAP HYDRATE (50ms/250ms)
  // - Rehidratação pós-load para garantir bindings (HTMX/Sortable/etc.)
  bootstrapHydrate();
  setTimeout(bootstrapHydrate, 50);
  setTimeout(bootstrapHydrate, 250);

  // 🔑 CHAMADA IMEDIATA (SEM ESPERAR POLL)
  syncUnreadBadge(boardId);
  syncCardUnreadBadges(boardId);

  // ✅ SOLICITAÇÕES DE ACESSO (sem F5)
  syncAccessRequests(boardId);

  // depois entra no loop normal
  loop();
});



  // 2) LOAD completo (Ctrl+F5 costuma evidenciar timing diferente)
  window.addEventListener("load", () => {
    bootstrapHydrate();
    setTimeout(bootstrapHydrate, 50);
  });

  // 3) Ao fechar o modal: destrava e “força” rehidratação + um tick rápido
document.addEventListener("modal:closed", () => {
  const boardId = getBoardId();
  bootstrapHydrate();
  syncUnreadBadge(boardId);
  syncAccessRequests(boardId);
  setTimeout(() => { tick(); }, 30);
});


  

  // 4) Quando a aba volta a ficar visível
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    const boardId = getBoardId();
    bootstrapHydrate();
    syncUnreadBadge(boardId);
    syncAccessRequests(boardId);
    setTimeout(() => { tick(); }, 30);
  }
});




    // ============================================================
  // Track-time badges (MVP) — throttle 5s
  // ============================================================
  let __ttLastFetchMs = 0;
  const TT_FETCH_EVERY_MS = 60000;

  function formatMMSS(seconds) {
    const s = Math.max(0, Number(seconds || 0));
    const mm = Math.floor(s / 60);
    const ss = Math.floor(s % 60);
    return `${mm}:${String(ss).padStart(2, "0")}`;
  }

  function clearTrackBadges(scope) {
    const root = scope || document;
    root.querySelectorAll(".tt-board-badge").forEach((el) => el.remove());
  }

  function applyTrackBadges(payload) {
    const cards = payload?.cards || {};
    // remove tudo e redesenha (MVP simples)
    clearTrackBadges(document);

    Object.entries(cards).forEach(([cardId, arr]) => {
      const li = document.querySelector(`li[data-card-id="${cardId}"]`);
      if (!li) return;

      const meta =
        li.querySelector(".term-badge")?.closest(".card-item")?.querySelector(".mt-2") ||
        li.querySelector(".term-badge")?.parentElement ||
        li;

      const badge = document.createElement("span");
      badge.className = "tt-board-badge";
      badge.title = (arr || []).map(x => `${x.user} — ${formatMMSS(x.elapsed_seconds)}`).join("\n");

      const dot = document.createElement("span");
      dot.className = "tt-board-badge-dot";

      // texto curto: “2 em track · 12:34”
      const first = (arr && arr[0]) ? ` · ${formatMMSS(arr[0].elapsed_seconds)}` : "";
      badge.appendChild(dot);
      badge.appendChild(document.createTextNode(`${arr.length} em track${first}`));

      // coloca no meta (ao lado do prazo)
      if (meta && meta !== li) {
        meta.appendChild(badge);
      } else {
        li.appendChild(badge);
      }
    });
  }

  async function tickTrackTimeBadges(boardId) {
    const nowMs = Date.now();
    if (nowMs - __ttLastFetchMs < TT_FETCH_EVERY_MS) return;
    __ttLastFetchMs = nowMs;

    try {
      const res = await fetch(`/track-time/boards/${boardId}/running/`, {
        method: "GET",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" },
        cache: "no-store",
      });
      if (!res.ok) return;
      const data = await res.json();
      applyTrackBadges(data);
    } catch (_) {
      // silencioso
    }
  }
  // integra ao loop principal


  async function syncUnreadBadge(boardId) {
  const now = Date.now();
  if (now - __lastUnreadFetchMs < UNREAD_FETCH_EVERY_MS) return;
  __lastUnreadFetchMs = now;

  try {
    const res = await fetch(`/board/${boardId}/history/unread-count/`, {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
      cache: "no-store",
    });
    if (!res.ok) return;

    const data = await res.json();
    const unread = Number(data.unread || 0);

    if (unread === __lastUnreadCount) return;
    __lastUnreadCount = unread;

    const badge = document.getElementById("drawer-unread-badge");
    if (!badge) return;

    badge.textContent = unread > 0 ? unread : "";
    badge.classList.toggle("hidden", unread === 0);
  } catch (_) {}
}


async function syncCardUnreadBadges(boardId) {
  if (!boardId) return;

  // ✅ Respeita preferência do usuário
  // Se desmarcado: zera e esconde todos os badges do card
  if (window.USER_ACTIVITY_COUNTS === false) {
    document.querySelectorAll("[data-card-unread-badge]").forEach((badge) => {
      badge.textContent = "";
      badge.classList.add("hidden");
    });

    // limpeza de legado (se existir badge antigo criado por JS)
    document.querySelectorAll(".card-unread-badge").forEach((el) => {
      if (!el.hasAttribute("data-card-unread-badge")) el.remove();
    });

    return;
  }

  // limpeza de legado (evita duplicar badges antigos)
  document.querySelectorAll(".card-unread-badge").forEach((el) => {
    if (!el.hasAttribute("data-card-unread-badge")) el.remove();
  });

  try {
    const res = await fetch(`/board/${boardId}/cards/unread-activity/`, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Accept": "application/json" }
    });

    if (!res.ok) return;

    const data = await res.json();
    const map = data.cards || {};

    document.querySelectorAll('li[data-card-id]').forEach((cardEl) => {
      const badge = cardEl.querySelector("[data-card-unread-badge]");
      if (!badge) return;

      const cardId = cardEl.getAttribute("data-card-id");
      const n = Number(map[cardId] || 0);

      if (n > 0) {
        badge.textContent = String(n);
        badge.classList.remove("hidden");
      } else {
        badge.textContent = "";
        badge.classList.add("hidden");
      }
    });
  } catch (e) {
    console.warn("syncCardUnreadBadges failed", e);
  }
}

})();


