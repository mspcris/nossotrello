// ============================================================
// BOARD POLLING — sincroniza colunas/cards entre usuários (A1)
// ============================================================
(function () {
  if (window.__BOARD_POLL_INSTALLED__) return;
  window.__BOARD_POLL_INSTALLED__ = true;

  const POLL_MS = 10000;
  const boardId = window.BOARD_ID;

  function getColumnsList() {
    return document.getElementById("columns-list");
  }

  function shouldPause() {
    if (document.hidden) return true;
    if (window.Modal?.state?.isOpen) return true;
    if (window.__isDraggingCard) return true;

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
  let boardVersion = Number(
    document.body.dataset.boardVersion || 0
  );

  async function tick() {
    const list = getColumnsList();
    if (!list) return;
    if (shouldPause()) return;
    if (inFlight) return;

    inFlight = true;

    try {
      const res = await fetch(
        `/board/${boardId}/poll/?v=${boardVersion}`,
        {
          method: "GET",
          credentials: "same-origin",
          headers: {
            "X-Requested-With": "XMLHttpRequest",
          },
          cache: "no-store",
        }
      );

      if (!res.ok) return;

      const data = await res.json();
      if (!data.changed) return;

      list.outerHTML = data.html;
      boardVersion = data.version;

      // reinit essenciais
      if (window.initSortable) initSortable();
      if (window.initSortableColumns) initSortableColumns();
      if (window.applySavedTagColorsToBoard)
        window.applySavedTagColorsToBoard(document);
    } catch (e) {
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
})();
//END board.poll.js