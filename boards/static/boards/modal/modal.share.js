// modal.share.js — card aberto: título na aba + assinatura (&s=) na URL.
// A assinatura vem do servidor (data-share-sig) e é o que libera o título do
// card na prévia do link (WhatsApp etc.) — ver boards/services/link_preview.py.
(() => {
  if (window.__ntModalShareBound) return;
  window.__ntModalShareBound = true;

  let baseTitle = null;

  function applyFromRoot() {
    const root = document.getElementById("cm-root");
    if (!root) return;
    const cardId = root.dataset.cardId;
    const title = (root.dataset.cardTitle || "").replace(/\s+/g, " ").trim();
    const board = (root.dataset.board || "").trim();
    const sig = root.dataset.shareSig || "";

    if (baseTitle === null) baseTitle = document.title;
    if (title) document.title = board ? `${title} · ${board}` : title;

    try {
      const u = new URL(window.location.href);
      if (sig && u.searchParams.get("card") === String(cardId) && u.searchParams.get("s") !== sig) {
        u.searchParams.set("s", sig);
        history.replaceState(history.state || {}, "", u);
      }
    } catch (_e) {}
  }

  document.body.addEventListener("htmx:afterSwap", (evt) => {
    if (evt.target && evt.target.id === "modal-body") applyFromRoot();
  });

  document.addEventListener("modal:closed", () => {
    if (baseTitle !== null) document.title = baseTitle;
    baseTitle = null;
    try {
      const u = new URL(window.location.href);
      if (!u.searchParams.has("card") && u.searchParams.has("s")) {
        u.searchParams.delete("s");
        history.replaceState(history.state || {}, "", u);
      }
    } catch (_e) {}
  });
})();
