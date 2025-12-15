// boards/static/boards/board_ui.js
// Contador + "Nenhum card ainda" em tempo real, sem loop infinito.
// Estratégia:
// 1) MutationObserver observa SÓ a lista de cards (evita reagir ao contador/título)
// 2) Só escreve no DOM quando o valor realmente muda
//
// + Popover "Cor da coluna":
// - Toggle ao clicar nas 3 bolinhas
// - Fecha ao clicar fora (capture=true para não depender de bubbling)
// - Sem depender de offsetParent (que falha em alguns layouts)

(function () {
  console.log("[board_ui] loaded", new Date().toISOString());

  function qs(sel, root = document) { return root.querySelector(sel); }
  function qsa(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

  // =========================
  // Popover "Cor da coluna"
  // =========================
  const BTN_SELECTOR =
    ".col-menu-btn, .column-menu-btn, .col-dots, [data-col-menu-btn], [data-col-menu]";

  const POPOVER_SELECTOR =
    ".col-color-popover, .column-color-popover, .color-popover, .color-picker-popover, .popover, [data-popover], [data-colors-popover], [data-col-color-popover]";

  function isVisible(el) {
    if (!el) return false;
    if (el.classList.contains("hidden")) return false;
    const cs = window.getComputedStyle(el);
    return cs.display !== "none" && cs.visibility !== "hidden";
  }

  function showPopover(el) {
    if (!el) return;
    el.classList.remove("hidden");
    el.style.display = "block";
    if (!el.style.position) el.style.position = "absolute";
    if (!el.style.zIndex) el.style.zIndex = "9999";
  }

  function hidePopover(el) {
    if (!el) return;
    el.classList.add("hidden");
    el.style.display = "none";
  }

  function hideAllPopovers(exceptEl = null) {
    qsa(POPOVER_SELECTOR).forEach((p) => {
      if (exceptEl && p === exceptEl) return;
      hidePopover(p);
    });
  }

  function findPopoverNearButton(btn) {
    const scope =
      btn.closest("[data-column-id]") ||
      btn.closest("[id^='column-'], [id^='col-']") ||
      btn.closest(".column, .board-column, .trello-column, .coluna") ||
      document;

    return scope.querySelector(POPOVER_SELECTOR);
  }

  // Clique global (capture): fecha ao clicar fora + toggle no botão
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(BTN_SELECTOR);
    const popClicked = e.target.closest(POPOVER_SELECTOR);

    // Clique no botão (3 bolinhas) -> toggle do popover mais próximo
    if (btn) {
      const target = findPopoverNearButton(btn);
      if (!target) {
        console.warn("[board_ui] popover NÃO encontrado perto do botão", btn);
        return;
      }

      const open = isVisible(target);
      // Fecha todos antes (evita múltiplos abertos)
      hideAllPopovers(target);

      if (open) hidePopover(target);
      else showPopover(target);

      return;
    }

    // Clique dentro do popover -> mantém aberto
    if (popClicked) return;

    // Clique fora -> fecha tudo
    hideAllPopovers();
  }, true);

  // =========================
  // Contador + Empty state
  // =========================
  function findColumns() {
    const byData = qsa("[data-column-id]");
    if (byData.length) return byData;

    const byId = qsa("[id^='column-'], [id^='col-']");
    if (byId.length) return byId;

    return qsa(".column, .board-column, .trello-column, .coluna");
  }

  function findCardList(columnEl) {
    return (
      qs("[data-card-list]", columnEl) ||
      qs(".card-list", columnEl) ||
      qs(".cards", columnEl) ||
      qs("ul", columnEl) ||
      qs("ol", columnEl) ||
      null
    );
  }

  function countCards(scopeEl) {
    if (!scopeEl) return 0;
    return qsa("li[id^='card-'], li[data-card-id], .card-item, .card", scopeEl).length;
  }

  function findCounterEl(columnEl) {
    const explicit = qs("[data-card-count]", columnEl) || qs(".col-card-count", columnEl);
    if (explicit) return explicit;

    const candidates = qsa("span, small, p, div", columnEl).slice(0, 80);
    for (const c of candidates) {
      const t = (c.textContent || "").trim();
      if (/^\d+\s+cards?$/i.test(t)) return c;
    }
    return null;
  }

  function findEmptyEls(columnEl) {
    const els = [];
    els.push(...qsa("[data-col-empty]", columnEl));
    els.push(...qsa(".col-empty, .column-empty", columnEl));

    const candidates = qsa("p, div, span, small", columnEl).slice(0, 120);
    for (const c of candidates) {
      const t = (c.textContent || "").trim().toLowerCase();
      if (t === "nenhum card ainda." || t === "nenhum card ainda") els.push(c);
    }
    return Array.from(new Set(els));
  }

  function setHidden(el, hidden) {
    if (!el) return;
    const alreadyHidden = el.classList.contains("hidden") || el.style.display === "none";
    if (hidden && alreadyHidden) return;
    if (!hidden && !alreadyHidden) return;

    el.classList.toggle("hidden", hidden);
    el.style.display = hidden ? "none" : "";
  }

  function refreshColumnUI(columnEl) {
    const list = findCardList(columnEl);
    const scope = list || columnEl;
    const n = countCards(scope);

    const counterEl = findCounterEl(columnEl);
    if (counterEl) {
      const next = `${n} cards`;
      if ((counterEl.textContent || "").trim() !== next) {
        counterEl.textContent = next;
      }
    }

    const showEmpty = (n === 0);
    const emptyEls = findEmptyEls(columnEl);
    emptyEls.forEach((el) => setHidden(el, !showEmpty));
  }

  function bindObserverForColumn(columnEl) {
    if (columnEl.dataset.colObserverBound === "1") {
      refreshColumnUI(columnEl);
      return;
    }
    columnEl.dataset.colObserverBound = "1";

    const list = findCardList(columnEl);
    const target = list || columnEl;

    let scheduled = false;
    const obs = new MutationObserver(() => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        refreshColumnUI(columnEl);
      });
    });

    obs.observe(target, { childList: true, subtree: true });
    refreshColumnUI(columnEl);
  }

  function scanAndBind() {
    findColumns().forEach(bindObserverForColumn);
  }

  document.addEventListener("DOMContentLoaded", scanAndBind);
  document.body.addEventListener("htmx:afterSwap", scanAndBind);
  document.body.addEventListener("htmx:afterSettle", scanAndBind);
})();
