// boards/static/boards/modal/board.poll.js
// ============================================================
// BOARD POLLING — sincroniza colunas/cards entre usuários (A1)
// ============================================================
(function () {
  if (window.__BOARD_POLL_INSTALLED__) return;
  window.__BOARD_POLL_INSTALLED__ = true;

  const POLL_MS = 10000;

  // boardId pode não existir no momento do parse (scripts defer / ordem),
  // então lemos sob demanda dentro do tick também.
  function getBoardId() {
    return window.BOARD_ID || document.body?.dataset?.boardId || null;
  }

  function getColumnsList() {
    return document.getElementById("columns-list");
  }

  function shouldPause() {
    if (document.hidden) return true;
    if (window.Modal?.state?.isOpen) return true;
    if (window.__isDraggingCard) return true;

    const ae = document.activeElement;
    if (ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA" || ae.isContentEditable)) {
      return true;
    }
    return false;
  }

  function rehydrateAfterSwap(scopeEl) {
    const scope = scopeEl || document;

    // Preferencial: pipeline único e determinístico
    if (window.BoardRuntime && typeof window.BoardRuntime.ensure === "function") {
      window.BoardRuntime.ensure(scope);
      return;
    }

    // Fallback: processa HTMX + reinicia Sortable + reaplica tags
    if (window.htmx && typeof window.htmx.process === "function") {
      window.htmx.process(scope);
    }
    if (window.initSortable) window.initSortable();
    if (window.initSortableColumns) window.initSortableColumns();
    if (window.applySavedTagColorsToBoard) window.applySavedTagColorsToBoard(document);
  }

  let inFlight = false;

  // Versão inicial do body (fonte de verdade do polling).
  // Mantém compat com seu base.html: data-board-version="..."
  let boardVersion = Number(document.body?.dataset?.boardVersion || window.BOARD_VERSION || 0);

  async function tick() {
    const list = getColumnsList();
    if (!list) return;
    if (shouldPause()) return;
    if (inFlight) return;

    const boardId = getBoardId();
    if (!boardId) return;

    inFlight = true;

    try {
      const res = await fetch(`/board/${boardId}/poll/?v=${boardVersion}`, {
        method: "GET",
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        cache: "no-store",
      });

      if (!res.ok) return;

      const data = await res.json();

      // respostas inválidas
      if (!data || !data.changed) return;
      if (!data.html || !String(data.html).trim()) return;

      // ✅ BLOQUEIO FINAL (race): se modal abriu durante o request, não faz swap
      if (window.Modal?.state?.isOpen) return;

      // swap
      list.outerHTML = data.html;

      // atualiza versões (mantém tudo consistente)
      boardVersion = Number(data.version || boardVersion);
      window.BOARD_VERSION = boardVersion;
      if (document.body?.dataset) document.body.dataset.boardVersion = String(boardVersion);

      // 🔑 o elemento antigo morreu. pega o novo.
      const newList = getColumnsList();

      // rehidrata handlers (resolve “só volta a funcionar depois de abrir/fechar modal”)
      rehydrateAfterSwap(newList || document);
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

  document.addEventListener("DOMContentLoaded", () => {
    loop();
  });

  // Opcional: ao fechar modal, roda uma rehidratação (garante retomada imediata)
  // Não força polling; só reata listeners caso algo tenha sido trocado antes.
  document.addEventListener("modal:closed", () => {
    const newList = getColumnsList();
    rehydrateAfterSwap(newList || document);
  });
})();
