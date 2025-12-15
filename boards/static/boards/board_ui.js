// boards/static/boards/board_ui.js
// Atualiza contador de cards e estado "Nenhum card ainda" em tempo real
// sem depender do Sortable (usa MutationObserver).

(function () {
  function qs(sel, root = document) { return root.querySelector(sel); }
  function qsa(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

  function findColumns() {
    // tenta achar colunas por data-attr ou classes comuns
    const byData = qsa("[data-column-id]");
    if (byData.length) return byData;

    // fallback: heurística (ajuste se você tiver uma classe padrão)
    return qsa(".column, .board-column, .trello-column, .coluna");
  }

  function findCardList(columnEl) {
    // 1) listas mais prováveis
    let list = qs("[data-card-list]", columnEl) || qs(".card-list, .cards, ul, ol", columnEl);
    return list || null;
  }

  function countCards(listEl) {
    if (!listEl) return 0;
    // pega pelos padrões mais comuns no seu projeto
    const cards = qsa("li[id^='card-'], li[data-card-id], .card-item, .card", listEl);
    return cards.length;
  }

  function findCounterEl(columnEl) {
    // preferência: um alvo específico (se existir)
    let el = qs("[data-card-count]", columnEl) || qs(".col-card-count", columnEl);
    if (el) return el;

    // fallback: tenta achar um texto tipo "3 cards" em spans pequenos
    const candidates = qsa("span, p, small, div", columnEl).slice(0, 60);
    for (const c of candidates) {
      const t = (c.textContent || "").trim();
      if (/\d+\s+cards?\b/i.test(t)) return c;
      if (/\d+\s+card(s)?\b/i.test(t)) return c;
      if (/\d+\s+cards?\b/i.test(t)) return c;
      // português (se você estiver usando "3 cards" mesmo, já cobre acima)
    }
    return null;
  }

  function findEmptyEl(columnEl) {
    let el = qs("[data-col-empty]", columnEl) || qs(".col-empty, .column-empty", columnEl);
    if (el) return el;

    // fallback por texto (último recurso)
    const candidates = qsa("p, div, span, small", columnEl).slice(0, 80);
    for (const c of candidates) {
      const t = (c.textContent || "").trim().toLowerCase();
      if (t.includes("nenhum card")) return c;
    }
    return null;
  }

  function setEmptyVisible(emptyEl, visible) {
    if (!emptyEl) return;
    // suporta tailwind e css puro
    emptyEl.classList.toggle("hidden", !visible);
    emptyEl.style.display = visible ? "" : "none";
  }

  function refreshColumnUI(columnEl) {
    const list = findCardList(columnEl);
    const n = countCards(list);

    const counterEl = findCounterEl(columnEl);
    if (counterEl) {
      // mantém formato "X cards"
      counterEl.textContent = `${n} cards`;
    }

    const emptyEl = findEmptyEl(columnEl);
    setEmptyVisible(emptyEl, n === 0);
  }

  function bindObserverForColumn(columnEl) {
    const list = findCardList(columnEl);
    if (!list) return;

    if (list.dataset.cardObserverBound === "1") {
      // já está monitorando
      refreshColumnUI(columnEl);
      return;
    }
    list.dataset.cardObserverBound = "1";

    const obs = new MutationObserver(() => refreshColumnUI(columnEl));
    obs.observe(list, { childList: true, subtree: true });

    // primeira atualização imediata
    refreshColumnUI(columnEl);
  }

  function scanAndBind() {
    const cols = findColumns();
    cols.forEach(bindObserverForColumn);
  }

  // DOM inicial
  document.addEventListener("DOMContentLoaded", scanAndBind);

  // Se você usa HTMX em algum ponto do quadro, garante rebind
  document.body.addEventListener("htmx:afterSwap", scanAndBind);
  document.body.addEventListener("htmx:afterSettle", scanAndBind);

})();
