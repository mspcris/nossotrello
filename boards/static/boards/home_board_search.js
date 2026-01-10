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

  function lower(s) {
    return (s || "").toString().toLowerCase();
  }

  function highlight(text, q) {
    const t = (text || "").toString();
    const qq = (q || "").toString().trim();
    if (!t || !qq) return esc(t);

    const tl = t.toLowerCase();
    const ql = qq.toLowerCase();
    const i = tl.indexOf(ql);
    if (i < 0) return esc(t);

    const a = esc(t.slice(0, i));
    const b = esc(t.slice(i, i + qq.length));
    const c = esc(t.slice(i + qq.length));

    return `${a}<mark class="px-1 rounded bg-emerald-200/70 text-emerald-950">${b}</mark>${c}`;
  }

  function ensureResultsBox(input) {
    let box = document.getElementById("home-search-results");
    if (box) return box;

    box = document.createElement("div");
    box.id = "home-search-results";
    box.className =
  [
    "mt-2 w-full max-w-[980px] mx-auto",
    "rounded-2xl border border-white/40 shadow-2xl",
    "bg-white/92 backdrop-blur-md",     // mais opaco (contraste)
    "ring-1 ring-black/10",
    "px-4 py-4 hidden",
    "relative z-[2200] pointer-events-auto"
  ].join(" ");


    const panel = input.closest(".cm-search-panel") || input.parentElement;
    if (panel && panel.parentElement) panel.parentElement.appendChild(box);
    else input.parentElement.appendChild(box);

    return box;
  }

  function hideHomeCardsAndGroups() {
    document.querySelectorAll(".board-card[data-board-id]").forEach(el => (el.style.display = "none"));
    document.querySelectorAll(".home-group-block, #home-favorites-block").forEach(b => (b.style.display = "none"));
  }

  function resetAll() {
    document.querySelectorAll(".board-card[data-board-id]").forEach(el => (el.style.display = ""));
    document.querySelectorAll(".home-group-block, #home-favorites-block").forEach(b => (b.style.display = ""));
    const box = document.getElementById("home-search-results");
    if (box) {
      box.innerHTML = "";
      box.classList.add("hidden");
    }
  }

  function badge(matchIn) {
    const m = lower(matchIn);
    const map = {
      "title": "título",
      "description": "descrição",
      "tags": "tags",
      "attachment": "anexo",
      "checklist": "checklist",
      "checklist_item": "item",
      "activity": "atividade",
      "card": "card",
    };
    const label = map[m] || m || "match";
    return `<span class="ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold bg-white/35 border border-white/30 text-slate-900">
      ${esc(label)}
    </span>`;
  }



function renderResults(box, data, q) {
  const cards = Array.isArray(data?.cards) ? data.cards : [];
  const boards = Array.isArray(data?.boards) ? data.boards : [];

  // Painel sempre legível (contraste alto) mesmo com wallpaper/blur
  // (mantém o "vidro", mas com opacidade suficiente)
  box.classList.add(
    "mt-3",
    "rounded-2xl",
    "border",
    "border-white/40",
    "shadow-2xl",
    "bg-white/95",
    "backdrop-blur-md",
    "ring-1",
    "ring-black/10",
    "px-6",
    "py-6"
  );

  // Fonte 2x maior do que o sugerido antes (padrão agora: base/xl)
  // Observação: como é JS, a gente garante que os textos internos são escuros (não branco)
  if (!cards.length && !boards.length) {
    box.innerHTML = `
      <div class="text-xl text-slate-800">
        Nenhum resultado para <b class="text-slate-950">${esc(q)}</b>.
      </div>`;
    box.classList.remove("hidden");
    hideHomeCardsAndGroups();
    return;
  }

  const cardsHtml = cards.length
    ? `
      <div class="mb-6">
        <div class="text-2xl font-extrabold text-slate-900 mb-4 tracking-wide">Cards</div>
        <div class="flex flex-col gap-3">
          ${cards
            .map(
              (c) => `
            <button
              type="button"
              class="text-left w-full rounded-2xl px-6 py-5
                     bg-white hover:bg-slate-50 transition
                     border border-slate-200 ring-1 ring-black/5
                     shadow-md hover:shadow-lg
                     active:scale-[0.99]"
              data-card-id="${esc(c.id)}"
              data-board-id="${esc(c.board_id)}"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="text-xl font-extrabold text-slate-950 leading-snug">
                  ${highlight(c.title, q)}
                  ${badge(c.match_in)}
                </div>
                <div class="text-lg font-semibold text-slate-600 whitespace-nowrap">
                  #${esc(c.id)}
                </div>
              </div>

              <div class="mt-3 text-lg text-slate-800">
                <span class="font-extrabold">Quadro:</span> ${highlight(
                  c.board_name || "#" + c.board_id,
                  q
                )}
                <span class="mx-2 text-slate-400">•</span>
                <span class="font-extrabold">Coluna:</span> ${highlight(
                  c.column_title || "#" + c.column_id,
                  q
                )}
              </div>

              ${
                c.excerpt
                  ? `
                <div class="mt-3 text-lg text-slate-700 leading-relaxed">
                  ${highlight(c.excerpt, q)}
                </div>
              `
                  : ""
              }
            </button>
          `
            )
            .join("")}
        </div>
      </div>
    `
    : "";

  const boardsHtml = boards.length
    ? `
      <div>
        <div class="text-2xl font-extrabold text-slate-900 mb-4 tracking-wide">Quadros</div>
        <div class="flex flex-col gap-3">
          ${boards
            .map(
              (b) => `
            <a
              href="/board/${encodeURIComponent(b.id)}/"
              class="block rounded-2xl px-6 py-5
                     bg-white hover:bg-slate-50 transition
                     border border-slate-200 shadow-md hover:shadow-lg
                     ring-1 ring-black/5
                     active:scale-[0.99]"
            >
              <div class="text-xl font-extrabold text-slate-950 leading-snug">
                ${highlight(b.name, q)}
              </div>
              <div class="mt-2 text-lg font-semibold text-slate-600">
                board #${esc(b.id)}
              </div>
            </a>
          `
            )
            .join("")}
        </div>
      </div>
    `
    : "";

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
        box.innerHTML = `<div class="text-sm text-white/90">Erro na busca (${resp.status}).</div>`;
        box.classList.remove("hidden");
        hideHomeCardsAndGroups();
        return;
      }

      const data = await resp.json();
      if (mySeq !== __seq) return;

      renderResults(box, data, q);
    } catch (_e) {
      const box = ensureResultsBox(inputEl);
      box.innerHTML = `<div class="text-sm text-white/90">Falha de rede na busca.</div>`;
      box.classList.remove("hidden");
      hideHomeCardsAndGroups();
    }
  }, 220);

  function init() {
    const input = document.getElementById("home-board-search");
    if (!input) return;

    input.addEventListener("input", () => run(input, input.value));

    // clique no card resultado -> abre no board
    document.addEventListener("click", (ev) => {
      const btn = ev.target.closest("#home-search-results button[data-card-id][data-board-id]");
      if (!btn) return;

      ev.preventDefault();
      ev.stopPropagation();

      const cardId = btn.getAttribute("data-card-id");
      const boardId = btn.getAttribute("data-board-id");
      if (!cardId || !boardId) return;

      // navega para o board e abre o modal via ?card
      window.location.href =
  `/board/${encodeURIComponent(boardId)}/?card=${encodeURIComponent(cardId)}`;

    }, true);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
