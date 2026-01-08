// boards/static/boards/home_board_search.js
(function () {
  function esc(s) {
    return (s || "").toString().replace(/[&<>"']/g, (m) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[m]));
  }

  function norm(s) {
    return (s || "").toString().trim();
  }

  function ensureResultsBox(input) {
    let box = document.getElementById("home-search-results");
    if (box) return box;

    box = document.createElement("div");
    box.id = "home-search-results";
    box.className =
      "mt-2 w-full max-w-[980px] mx-auto rounded-xl bg-white/70 backdrop-blur-md " +
      "border border-white/30 shadow px-3 py-2 hidden relative z-[120] pointer-events-auto";

    // encaixa logo após o painel de busca (mesmo bloco)
    const panel = input.closest(".cm-search-panel") || input.parentElement;
    if (panel && panel.parentElement) {
      panel.parentElement.appendChild(box);
    } else {
      input.parentElement.appendChild(box);
    }

    return box;
  }

  function hideHomeCardsAndGroups() {
    document.querySelectorAll(".board-card[data-board-id]").forEach(el => (el.style.display = "none"));
    document.querySelectorAll(".home-group-block, #home-favorites-block").forEach(b => (b.style.display = "none"));
  }

  function showHomeCardsAndGroups() {
    document.querySelectorAll(".board-card[data-board-id]").forEach(el => (el.style.display = ""));
    document.querySelectorAll(".home-group-block, #home-favorites-block").forEach(b => (b.style.display = ""));
  }

  function hideResultsBox() {
    const box = document.getElementById("home-search-results");
    if (!box) return;
    box.classList.add("hidden");
    box.innerHTML = "";
  }

  function resetAll() {
    showHomeCardsAndGroups();
    hideResultsBox();
  }

  function renderResults(box, data, q) {
    const cards = Array.isArray(data?.cards) ? data.cards : [];
    const boards = Array.isArray(data?.boards) ? data.boards : [];

    if (!cards.length && !boards.length) {
      box.innerHTML = `<div class="text-sm text-gray-700">Nenhum resultado para <b>${esc(q)}</b>.</div>`;
      box.classList.remove("hidden");
      hideHomeCardsAndGroups();
      return;
    }

    const cardsHtml = cards.length ? `
      <div class="mb-3">
        <div class="text-xs font-semibold text-gray-700 mb-2">Cards</div>
        <div class="flex flex-col gap-2">
          ${cards.map(c => `
            <button
              type="button"
              class="text-left block w-full rounded-lg bg-white/80 border border-gray-300 px-3 py-2 hover:bg-white transition"
              data-card-id="${esc(c.id)}"
            >
              <div class="text-sm font-semibold text-gray-900">${esc(c.title)}</div>
              <div class="text-xs text-gray-600">card #${esc(c.id)} · board #${esc(c.board_id)}</div>
            </button>
          `).join("")}
        </div>
      </div>
    ` : "";

    const boardsHtml = boards.length ? `
      <div>
        <div class="text-xs font-semibold text-gray-700 mb-2">Quadros</div>
        <div class="flex flex-col gap-2">
          ${boards.map(b => `
            <a
              href="/board/${encodeURIComponent(b.id)}/"
              class="block rounded-lg bg-white/70 border border-gray-300 px-3 py-2 hover:bg-white transition"
            >
              <div class="text-sm font-semibold text-gray-900">${esc(b.name)}</div>
              <div class="text-xs text-gray-600">board #${esc(b.id)}</div>
            </a>
          `).join("")}
        </div>
      </div>
    ` : "";

    box.innerHTML = cardsHtml + boardsHtml;
    box.classList.remove("hidden");
    hideHomeCardsAndGroups();
  }

  function debounce(fn, wait) {
    let t = null;
    function debounced(...args) {
      if (t) clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), wait);
    }
    debounced.cancel = function () {
      if (t) clearTimeout(t);
      t = null;
    };
    return debounced;
  }

  let __seq = 0;

  const run = debounce(async function (inputEl, raw) {
    const q = norm(raw);
    const mySeq = ++__seq;

    if (!q) {
      resetAll();
      return;
    }

    const box = ensureResultsBox(inputEl);

    try {
      const resp = await fetch(`/home/search/?q=${encodeURIComponent(q)}`, {
        method: "GET",
        credentials: "same-origin",
        headers: { "Accept": "application/json" }
      });

      if (mySeq !== __seq) return;

      if (!resp.ok) {
        box.innerHTML = `<div class="text-sm text-red-700">Erro na busca (${resp.status}).</div>`;
        box.classList.remove("hidden");
        hideHomeCardsAndGroups();
        return;
      }

      const data = await resp.json();
      if (mySeq !== __seq) return;

      renderResults(box, data, q);
    } catch (_e) {
      const box = ensureResultsBox(inputEl);
      box.innerHTML = `<div class="text-sm text-red-700">Falha de rede na busca.</div>`;
      box.classList.remove("hidden");
      hideHomeCardsAndGroups();
    }
  }, 250);

  function openCardFromHome(cardId, input) {
    const id = Number(cardId || 0);
    if (!id) return;

    // fecha resultados e tira foco do input
    if (input) input.blur();
    hideResultsBox();

    // hardening: garante que o modal volte a aceitar interação
    const modal = document.getElementById("modal");
    if (modal) {
      modal.classList.remove("pointer-events-none", "invisible");
      modal.style.pointerEvents = "auto";
    }

    if (window.Modal && typeof window.Modal.openCard === "function") {
      // não mexer na URL aqui: modal.url.js assume isso
      window.Modal.openCard(id, false, null);
    }
  }

  function init() {
    const input = document.getElementById("home-board-search");
    if (!input) return;

    input.addEventListener("input", () => run(input, input.value));

    // clique nos resultados (cards) — delegation
    document.addEventListener("click", (ev) => {
      const btn = ev.target.closest("#home-search-results button[data-card-id]");
      if (!btn) return;

      ev.preventDefault();
      ev.stopPropagation();

      openCardFromHome(btn.dataset.cardId, input);
    }, true);

    // click fora do box: fecha resultados (quando estiver aberto)
    document.addEventListener("click", (ev) => {
      const box = document.getElementById("home-search-results");
      if (!box || box.classList.contains("hidden")) return;

      const clickedInsideBox = !!ev.target.closest("#home-search-results");
      const clickedInput = (ev.target === input) || !!ev.target.closest("#home-board-search");
      if (clickedInsideBox || clickedInput) return;

      hideResultsBox();
      showHomeCardsAndGroups();
    }, true);

    // ESC: limpa busca e volta home
    document.addEventListener("keydown", (ev) => {
      if (ev.key !== "Escape") return;
      if (document.activeElement === input || !document.getElementById("home-search-results")?.classList.contains("hidden")) {
        input.value = "";
        resetAll();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
