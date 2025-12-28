// boards/static/boards/modal/board.poll.js
// ============================================================
// BOARD POLLING — sincroniza colunas/cards entre usuários (A1)
// - Não faz swap com modal aberto / drag / foco em input
// - Rehidrata JS (HTMX + Sortable + TagColors) após swap
// - Garante “bootstrap” no load (resolve o caso: só funciona após abrir/fechar modal)
// ============================================================
(function () {
  if (window.__BOARD_POLL_INSTALLED__) return;
  window.__BOARD_POLL_INSTALLED__ = true;

  // Ajuste fino: se quiser sobrescrever via console/localStorage futuramente
  const POLL_MS = Number(window.BOARD_POLL_MS || 1500);

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

    if (shouldPause()) return;
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

      if (!data.html || !String(data.html).trim()) return;

      // swap completo do bloco (o elemento antigo “morre”)
      list.outerHTML = data.html;

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
    setTimeout(async () => {
      await tick();
      loop();
    }, POLL_MS);
  }

  // ---- BOOTSTRAP / RESUME POINTS ----

  // 1) DOM pronto
  document.addEventListener("DOMContentLoaded", () => {
    // rehidrata imediatamente + após pequeno delay (pega casos de ordem de scripts)
    bootstrapHydrate();
    setTimeout(bootstrapHydrate, 50);
    setTimeout(bootstrapHydrate, 250);

    loop();
  });

  // 2) LOAD completo (Ctrl+F5 costuma evidenciar timing diferente)
  window.addEventListener("load", () => {
    bootstrapHydrate();
    setTimeout(bootstrapHydrate, 50);
  });

  // 3) Ao fechar o modal: destrava e “força” rehidratação + um tick rápido
  document.addEventListener("modal:closed", () => {
    bootstrapHydrate();
    setTimeout(() => { tick(); }, 30);
  });

  // 4) Quando a aba volta a ficar visível
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      bootstrapHydrate();
      setTimeout(() => { tick(); }, 30);
    }
  });
})();
