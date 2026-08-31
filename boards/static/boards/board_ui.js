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
  
  
  
  
  
  
  
  const boardRoot = document.getElementById("board-root");
  const canEdit = boardRoot && boardRoot.dataset.canEdit === "1";


function boardCanEditNow() {
  const root = document.getElementById("board-root");
  return !!(root && root.dataset.canEdit === "1");
}

// estado global (útil pra outros scripts)
window.__boardCanEdit = boardCanEditNow();

// aplica “readonly UI” quando o DOM estiver pronto (e reavalia em swaps)
function applyReadonlyUI() {
  window.__boardCanEdit = boardCanEditNow();

  if (!window.__boardCanEdit) {
    // marque cards como readonly (ajuste o seletor se necessário)
    document.querySelectorAll("li[data-card-id], .card-item").forEach((el) => {
      el.setAttribute("draggable", "false");
      el.classList.add("is-readonly");
    });
  } else {
    // se for editor/owner, remove marcas readonly
    document.querySelectorAll("li[data-card-id].is-readonly, .card-item.is-readonly").forEach((el) => {
      el.removeAttribute("draggable");
      el.classList.remove("is-readonly");
    });
  }
}

// hard-stop: só bloqueia se NA HORA for readonly
if (!window.__dragstartGuardInstalled) {
  window.__dragstartGuardInstalled = true;

  document.addEventListener("dragstart", (e) => {
    if (boardCanEditNow()) return; // editor/owner: deixa passar
    if (e.target.closest("li[data-card-id], .card-item")) e.preventDefault();
  }, true);
}

document.addEventListener("DOMContentLoaded", applyReadonlyUI);
document.body.addEventListener("htmx:afterSwap", applyReadonlyUI);
document.body.addEventListener("htmx:afterSettle", applyReadonlyUI);


// ============================================================
// TERM COLORS (prazos) — computed client-side
// ============================================================
// ============================================================
// TERM COLORS (prazos) — computed client-side
// - Board: <li data-card-id ...>
// - Calendar: <button class="cm-cal-card" data-card-id ...>
// - Pinta:
//   - Board: aplica tint + badge
//   - Calendar: pinta .cm-cal-dot e/ou .cm-cal-bar dentro do card
// ============================================================
window.applySavedTermColorsToBoard = function (scope) {
  const root = scope || document;

  const colors = (window.BOARD_TERM_COLORS && typeof window.BOARD_TERM_COLORS === "object")
    ? window.BOARD_TERM_COLORS
    : {};

  const cOk   = colors.ok || "#16a34a";
  const cWarn = colors.warn || "#f59e0b";
  const cOver = colors.overdue || "#dc2626";

  function parseYMD(s) {
    if (!s) return null;
    const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return null;
    const y = Number(m[1]), mo = Number(m[2]) - 1, d = Number(m[3]);
    const dt = new Date(Date.UTC(y, mo, d, 0, 0, 0));
    return isNaN(dt.getTime()) ? null : dt;
  }

  function todayUTC() {
    const now = new Date();
    return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 0, 0, 0));
  }

  function hexToRgbStr(hex) {
    const h = String(hex || "").trim();
    const m = h.match(/^#?([0-9a-fA-F]{6})$/);
    if (!m) return "0,0,0";
    const n = parseInt(m[1], 16);
    const r = (n >> 16) & 255;
    const g = (n >> 8) & 255;
    const b = n & 255;
    return `${r},${g},${b}`;
  }

  function clearTint(cardEl) {
    if (!cardEl) return;
    cardEl.style.setProperty("--term-opacity", "0");
    cardEl.style.removeProperty("--term-rgb");
  }

  function setTint(cardEl, hexColor) {
    if (!cardEl || !hexColor) return;
    cardEl.style.setProperty("--term-rgb", hexToRgbStr(hexColor));
    cardEl.style.setProperty("--term-opacity", "0.18");
  }

  function setBadge(badge, text, color) {
    if (!badge) return;
    badge.textContent = text;
    badge.style.backgroundColor = color + "20";
    badge.style.color = color;
    badge.style.border = "1px solid " + color;
    badge.classList.remove("hidden");
  }

  function paintCalendarChip(cardEl, color) {
    // calendário: pinta dot e/ou barra dentro do card
    const dot = cardEl.querySelector(".cm-cal-dot");
    if (dot) {
      dot.style.backgroundColor = color;
      dot.style.borderColor = color;
    }
    const bar = cardEl.querySelector(".cm-cal-bar");
    if (bar) {
      bar.style.backgroundColor = color;
      bar.style.borderColor = color;
    }
  }

  // 🔑 agora pega board + calendário
  const cardEls = root.querySelectorAll('li[data-card-id], .cm-cal-card[data-card-id]');

  const t = todayUTC();

  cardEls.forEach((cardEl) => {
    const isCalendar = cardEl.classList && cardEl.classList.contains("cm-cal-card");

    const notify = (cardEl.getAttribute("data-term-notify") || "1") === "1";

    const due  = parseYMD(cardEl.getAttribute("data-term-due") || "");
    const warn = parseYMD(cardEl.getAttribute("data-term-warn") || "");

    // Board badge (se existir)
    const badge = !isCalendar ? cardEl.querySelector(".term-badge") : null;

    // sem prazo ou sem notify => neutro
    if (!notify || !due) {
      if (!isCalendar) {
        clearTint(cardEl);
        if (badge) badge.classList.add("hidden");
      } else {
        // calendário: não força nada
      }
      return;
    }

    // status: overdue / warn / ok
    if (due.getTime() < t.getTime()) {
      if (!isCalendar) {
        setTint(cardEl, cOver);
        if (badge) setBadge(badge, "Vencido", cOver);
      } else {
        paintCalendarChip(cardEl, cOver);
      }
      return;
    }

    if (warn && t.getTime() >= warn.getTime()) {
      if (!isCalendar) {
        setTint(cardEl, cWarn);
        if (badge) setBadge(badge, "A vencer", cWarn);
      } else {
        paintCalendarChip(cardEl, cWarn);
      }
      return;
    }

    if (!isCalendar) {
      setTint(cardEl, cOk);
      if (badge) setBadge(badge, "Em dia", cOk);
    } else {
      paintCalendarChip(cardEl, cOk);
    }
  });
};







// =========================
// FOLLOW CARD — verde IMEDIATO (optimistic) + HTMX source-of-truth
// =========================
(function () {
  if (window.__cmFollowCardInstalled) return;
  window.__cmFollowCardInstalled = true;

  function getBtnFromEventTarget(t){
    return t.closest?.(".card-follow-btn[hx-post]") || null;
  }

  // 1) Clique: pinta NA HORA (capture roda antes do onclick inline)
  document.addEventListener("click", function (e) {
    const btn = getBtnFromEventTarget(e.target);
    if (!btn) return;

    if (btn.dataset.followBusy === "1") return;
    btn.dataset.followBusy = "1";

    btn.classList.toggle("is-following");
    btn.classList.add("is-following-pending");
  }, true);

  // 2) Sucesso: alinha com resposta JSON se existir
  document.body.addEventListener("htmx:afterRequest", function (e) {
    const elt = e.detail?.elt;
    const btn = elt?.closest?.(".card-follow-btn[hx-post]") || null;
    if (!btn) return;

    btn.classList.remove("is-following-pending");
    btn.dataset.followBusy = "0";

    try {
      const xhr = e.detail?.xhr;
      const ct = xhr?.getResponseHeader?.("content-type") || "";
      if (ct.includes("application/json")) {
        const data = JSON.parse(xhr.responseText || "{}");
        if (typeof data.following === "boolean") {
          btn.classList.toggle("is-following", data.following);
        }
      }
    } catch (_err) {}
  });

  // 3) Erro: rollback do optimista
  document.body.addEventListener("htmx:responseError", function (e) {
    const elt = e.detail?.elt;
    const btn = elt?.closest?.(".card-follow-btn[hx-post]") || null;
    if (!btn) return;

    btn.classList.remove("is-following-pending");
    btn.dataset.followBusy = "0";

    btn.classList.toggle("is-following");
  });
})();










// ============================================================
// VIEWER LIVE REFRESH (sem websocket): atualiza columns-list sem F5
// ============================================================

function startViewerPolling() {
  if (window.__boardPollInstalled) return;
  window.__boardPollInstalled = true;

  const getColumnsList = () => document.getElementById("columns-list");
  let lastHtml = (getColumnsList()?.innerHTML || "");

  function hasOpenInlineForms(rootEl) {
    // evita “apagar” o form do +Card / criar condição de corrida
    return !!rootEl.querySelector(
      "[id^='form-col-'] form, [id^='form-top-col-'] form"
    );
  }

  function hasHtmxRequestInFlight(rootEl) {
    // HTMX marca elementos envolvidos com .htmx-request
    return !!rootEl.querySelector(".htmx-request");
  }

  async function tick() {
    // se agora virou editor/owner, não precisa mais
    if (boardCanEditNow()) return;

    // evita briga visual se o editor estiver arrastando
    if (window.__isDraggingCard) return;

    const columnsList = getColumnsList();
    if (!columnsList) return;

    // não “atropela” interação do usuário
    if (hasHtmxRequestInFlight(columnsList)) return;
    if (hasOpenInlineForms(columnsList)) return;

    try {
      const res = await fetch(window.location.pathname, {
        method: "GET",
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-Board-Poll": "1",
        },
      });

      if (!res.ok) return;

      const html = await res.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const fresh = doc.getElementById("columns-list");
      if (!fresh) return;

      const nextHtml = fresh.innerHTML;
      if (nextHtml === lastHtml) return;

      // troca só o miolo das colunas/cards
      columnsList.innerHTML = nextHtml;
      lastHtml = nextHtml;

      // >>> PONTO-CHAVE: reprocessa HTMX nos nós inseridos via innerHTML
      if (window.htmx && typeof window.htmx.process === "function") {
        window.htmx.process(columnsList);
      }

      // re-aplica comportamentos que dependem do DOM novo
      applyReadonlyUI();
      scanAndBind();

      if (typeof window.applySavedTermColorsToBoard === "function") {
        window.applySavedTermColorsToBoard(columnsList);
      }


      if (window.applySavedTagColorsToBoard) {
        window.applySavedTagColorsToBoard(columnsList);
      }


      // se existirem no global, reinit de sortable (p/ owner em outra sessão)
      if (typeof window.initSortable === "function") window.initSortable();
      if (typeof window.initSortableColumns === "function") window.initSortableColumns();
    } catch (_e) {
      // silencioso
    }
  }

  tick();

  // Polling agora é FALLBACK só. WS push (board.ws.js) entrega mudanças
  // em tempo real — pollar 10s além disso era duplicação que multiplicava
  // por (viewers × boards × 6 req/min) e detonava dockerd. Intervalo grande
  // (5min) só cobre o caso do WS estar morto silenciosamente.
  setInterval(() => {
    if (window.__BOARD_WS_INSTALLED__) return;  // WS instalado → ele cuida
    tick();
  }, 300000);

  // se algum swap acontecer localmente, atualiza o baseline
  document.body.addEventListener("htmx:afterSwap", () => {
    lastHtml = (getColumnsList()?.innerHTML || lastHtml);
  });
  document.body.addEventListener("htmx:afterSettle", () => {
    lastHtml = (getColumnsList()?.innerHTML || lastHtml);
  });
}



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

  const cards = qsa("li[id^='card-'], li[data-card-id], .card-item, .card", scopeEl);

  // conta apenas os visíveis (compatível com filtro via display:none e/ou .hidden)
  let n = 0;
  const seen = new Set();
  for (const el of cards) {
    if (!el) continue;
    if (seen.has(el)) continue;   // o seletor tem 4 alternativas: evita contar 2x
    seen.add(el);

    // card contador é widget, não tarefa: fora da contagem
    if (el.dataset && el.dataset.counter === "1") continue;
    if (el.querySelector && el.querySelector(".cc-counter")) continue;

    if (el.classList && el.classList.contains("hidden")) continue;

    const cs = window.getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") continue;

    n += 1;
  }
  return n;
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

    // Mira o MESMO contador canônico do refreshCounters() do board (o span com
    // data-total-count). O findCounterEl por regex era um fallback frágil que
    // podia pegar OUTRO elemento sem data-total-count e fazer os dois sistemas
    // de contagem divergirem. Prioriza o canônico; regex só se ele não existir.
    const counterEl = columnEl.querySelector("[data-column-counter]") || findCounterEl(columnEl);

    const filterEl = document.getElementById("board-filter");
    const filtering = !!(filterEl && (filterEl.value || "").trim());
    const total = Number((counterEl && counterEl.dataset ? counterEl.dataset.totalCount : 0) || 0);
    const domCount = countCards(scope);

    // Enquanto houver cards por carregar, sem filtro ativo, confia no total do
    // servidor — contar só os <li> do DOM subestima. Duas pistas de "ainda
    // falta carregar", pra não travar no tamanho do 1o lote:
    //  - sentinel presente (lazy-load pendente); OU
    //  - DOM tem menos cards que o total (a sentinela some por um instante no
    //    swap do lazy-load / num carregamento frio pós-restart — essa 2a pista
    //    cobre a corrida e evita o contador ficar preso em 19).
    const pendingLazyLoad =
      !filtering &&
      total > 0 &&
      (columnEl.querySelector(".cm-more-sentinel") || domCount < total);

    const n = pendingLazyLoad ? total : domCount;

    if (counterEl) {
      const next = `${n} card${n !== 1 ? "s" : ""}`;
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

  document.addEventListener("DOMContentLoaded", () => {
  const columnsList = document.getElementById("columns-list");
  if (columnsList && typeof window.applySavedTermColorsToBoard === "function") {
    window.applySavedTermColorsToBoard(columnsList);
  }
});

document.body.addEventListener("htmx:afterSwap", (e) => {
  const columnsList = document.getElementById("columns-list");
  if (columnsList && typeof window.applySavedTermColorsToBoard === "function") {
    window.applySavedTermColorsToBoard(columnsList);
  }
});


  document.addEventListener("DOMContentLoaded", scanAndBind);
  document.body.addEventListener("htmx:afterSwap", scanAndBind);
  document.body.addEventListener("htmx:afterSettle", scanAndBind);
})();

//ALTERAR NOME DA COLUNA

(function () {
  function getCsrfToken() {
    const el = document.querySelector("meta[name='csrf-token']");
    return el ? el.content : "";
  }

  async function persistColumnName(columnId, name) {
    const csrf = getCsrfToken();
    const resp = await fetch(`/column/${columnId}/rename/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-CSRFToken": csrf,
      },
      body: new URLSearchParams({ name }),
      credentials: "same-origin",
    });

    if (!resp.ok) {
      // para debugar rápido no console
      const text = await resp.text().catch(() => "");
      console.error("rename_column failed", resp.status, text);
      throw new Error(`rename_column failed: ${resp.status}`);
    }
  }

  // Event delegation: funciona mesmo com HTMX swaps
  document.addEventListener("keydown", function (e) {
    const el = e.target;
    if (!el || !el.matches?.("[data-column-title]")) return;

    if (e.key === "Enter") {
      e.preventDefault();
      el.blur(); // dispara o fluxo de salvar no blur
    }
  }, true);

  document.addEventListener("blur", async function (e) {
    const el = e.target;
    if (!el || !el.matches?.("[data-column-title]")) return;

    const columnId = el.getAttribute("data-column-id");
    const name = (el.innerText || "")
    .replace(/\u00A0/g, " ")
    .replace(/\s+/g, " ")
    .trim();


    if (!columnId) return;

    // Regras mínimas de qualidade
    if (!name) {
      // se ficar vazio, volta pro title antigo sem salvar
      el.innerText = el.getAttribute("title") || "";
      return;
    }

    // Evita POST inútil se nada mudou
    const prev = (el.getAttribute("title") || "").trim();
    if (name === prev) return;

    try {
      await persistColumnName(columnId, name);
      // atualiza o "source of truth" local para F5 não depender do DOM
      el.setAttribute("title", name);
    } catch (err) {
      // rollback visual
      el.innerText = el.getAttribute("title") || "";
    }
  }, true);
})();


// Impede colar HTML dentro do título (cola só texto)
document.addEventListener("paste", function (e) {
  const el = e.target;
  if (!el || !el.matches?.("[data-column-title]")) return;

  e.preventDefault();
  const text = (e.clipboardData || window.clipboardData).getData("text/plain");
  // insere texto puro no cursor
  document.execCommand("insertText", false, text);
}, true);

// Mantém o título SEMPRE como texto puro (remove tags caso entrem)
document.addEventListener("input", function (e) {
  const el = e.target;
  if (!el || !el.matches?.("[data-column-title]")) return;

  // se por algum motivo ensure que não fica HTML
  const plain = (el.innerText || "").replace(/\u00A0/g, " "); // NBSP -> espaço normal
  if (el.innerHTML !== plain) {
    const sel = window.getSelection();
    const range = sel && sel.rangeCount ? sel.getRangeAt(0) : null;

    el.textContent = plain;

    // tenta preservar cursor no fim (simples e suficiente)
    if (sel) {
      sel.removeAllRanges();
      const r = document.createRange();
      r.selectNodeContents(el);
      r.collapse(false);
      sel.addRange(r);
    }
  }
}, true);














// Column menu (3 dots) — global, 1x
window.toggleMenu = function (colId) {
  const el = document.getElementById("col-menu-" + colId);
  if (!el) return;

  const btn = el.closest("[data-color-popover-scope]")?.querySelector("[data-color-popover-trigger]");
  const isHidden = el.classList.contains("hidden");

  // fecha todos
  document.querySelectorAll("[data-color-popover]").forEach((p) => p.classList.add("hidden"));

  if (isHidden) {
    el.classList.remove("hidden");
    btn?.setAttribute("aria-expanded", "true");
  } else {
    el.classList.add("hidden");
    btn?.setAttribute("aria-expanded", "false");
  }
};

// fecha popover ao clicar fora + ESC — global, 1x
if (!window.__colorPopoverOutsideInstalled) {
  window.__colorPopoverOutsideInstalled = true;

  document.addEventListener("click", function (e) {
    document.querySelectorAll("[data-color-popover-scope]").forEach((scope) => {
      const pop = scope.querySelector("[data-color-popover]");
      if (!pop || pop.classList.contains("hidden")) return;

      const btn = scope.querySelector("[data-color-popover-trigger]");
      const clickedInside = pop.contains(e.target) || (btn && btn.contains(e.target));
      if (!clickedInside) {
        pop.classList.add("hidden");
        if (btn) btn.setAttribute("aria-expanded", "false");
      }
    });
  }, true);

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    document.querySelectorAll("[data-color-popover]").forEach((p) => p.classList.add("hidden"));
    document.querySelectorAll("[data-color-popover-trigger]").forEach((b) => b.setAttribute("aria-expanded", "false"));
  });
}

// Fim alterar nome da coluna








// =========================
// ADD CARD UX (top/bottom) — ENTER + SCROLL + CLOSE FORM (SOURCE OF TRUTH)
// =========================
(function () {
  if (window.__cmAddCardUXInstalled) return;
  window.__cmAddCardUXInstalled = true;

  function qsa(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

  function isAddCardForm(el) {
    return !!(el && el.matches && el.matches("form[data-add-card-form]"));
  }

  function getWhereFromForm(formEl) {
    return String(formEl?.getAttribute("data-where") || "bottom").toLowerCase();
  }

  function getColIdFromForm(formEl) {
    const v = formEl?.getAttribute("data-column-id");
    return v ? String(v) : "";
  }

  function getColumnElById(colId) {
    if (!colId) return null;
    return document.querySelector(`.column-item[data-column-id="${colId}"], [data-column-id="${colId}"]`);
  }

  function closeFormsInColumn(colId) {
    if (!colId) return;
    const top = document.getElementById(`form-top-col-${colId}`);
    const bottom = document.getElementById(`form-col-${colId}`);
    if (top) top.innerHTML = "";
    if (bottom) bottom.innerHTML = "";
  }

  function closeOppositeContainer(colId, where) {
    if (!colId) return;
    if (where === "top") {
      const bottom = document.getElementById(`form-col-${colId}`);
      if (bottom) bottom.innerHTML = "";
    } else {
      const top = document.getElementById(`form-top-col-${colId}`);
      if (top) top.innerHTML = "";
    }
  }

  function findCardsScrollerByColId(colId) {
    const col = getColumnElById(colId);
    if (!col) return null;
    return (
      col.querySelector("#cards-col-" + colId) ||
      col.querySelector("[id^='cards-col-']") ||
      col.querySelector("[data-card-list]") ||
      col.querySelector("ul") ||
      col.querySelector("ol") ||
      null
    );
  }

  function boing(colEl, where) {
    if (!colEl) return;
    colEl.classList.remove("boing-top", "boing-bottom");
    if (where === "top") colEl.classList.add("boing-top");
    else colEl.classList.add("boing-bottom");
    window.setTimeout(() => colEl.classList.remove("boing-top", "boing-bottom"), 260);
  }

  function focusTitleInput(formEl) {
    if (!formEl) return;

    const inp =
      formEl.querySelector("input[name='title'], textarea[name='title']") ||
      formEl.querySelector("input[type='text'], input:not([type]), textarea");

    if (!inp) return;

    requestAnimationFrame(() => {
      try {
        // evita "puxar" a coluna
        inp.focus({ preventScroll: true });
      } catch (_e) {
        // fallback (browser antigo)
        inp.focus();
      }
      inp.select?.();
    });
  }

  // -------------------------
  // Scroll lock (vence reset tardio)
  // -------------------------
  const scrollLocks = new Map(); // colId -> token

  function setScroll(colId, where) {
    const scroller = findCardsScrollerByColId(colId);
    if (!scroller) return;

    if (where === "top") scroller.scrollTop = 0;
    else scroller.scrollTop = scroller.scrollHeight;
  }

  function lockScroll(colId, where, ms = 700) {
    if (!colId) return;

    // token pra cancelar locks antigos
    const token = (scrollLocks.get(colId) || 0) + 1;
    scrollLocks.set(colId, token);

    const start = Date.now();

    function tick() {
      // cancelado por lock novo
      if (scrollLocks.get(colId) !== token) return;

      // aplica no frame (garante pós-layout)
      setScroll(colId, where);

      if (Date.now() - start < ms) {
        requestAnimationFrame(tick);
      } else {
        // fim do lock
        if (scrollLocks.get(colId) === token) scrollLocks.delete(colId);
      }
    }

    // 2 rAF pra pegar altura final antes de começar o lock
    requestAnimationFrame(() => requestAnimationFrame(tick));
  }

  // -------------------------
  // ENTER SUBMIT (bind no FORM)
  // -------------------------
  function bindEnterOnForm(formEl) {
    if (!formEl) return;
    if (formEl.dataset.enterBound === "1") return;
    formEl.dataset.enterBound = "1";

    formEl.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      if (e.isComposing) return;
      if (e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return;

      const t = e.target;
      if (!t || !(t.matches?.("input, textarea"))) return;

      const field =
        formEl.querySelector("input[name='title'], textarea[name='title']") ||
        formEl.querySelector("input[type='text'], input:not([type]), textarea");

      const title = (field?.value || "").trim();
      if (!title) return;

      e.preventDefault();
      e.stopPropagation();

      if (typeof formEl.requestSubmit === "function") formEl.requestSubmit();
      else formEl.submit();
    }, true);
  }

  // fallback global (só 1x)
  if (!window.__cmAddCardEnterGlobalInstalled) {
    window.__cmAddCardEnterGlobalInstalled = true;

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      if (e.isComposing) return;
      if (e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return;

      const el = e.target;
      if (!el || !(el.matches?.("input, textarea"))) return;

      const form = el.closest?.("form[data-add-card-form]");
      if (!form) return;

      const title = (el.value || "").trim();
      if (!title) return;

      e.preventDefault();
      e.stopPropagation();

      if (typeof form.requestSubmit === "function") form.requestSubmit();
      else form.submit();
    }, true);
  }

  // -------------------------
  // intenção (não depende do form existir depois)
  // -------------------------
  const pending = { byCol: new Map() };

  function rememberIntent(colId, where) {
    if (!colId) return;
    pending.byCol.set(colId, { where: (where || "bottom"), stamp: Date.now() });
  }

  function touchedBoardFromTarget(target) {
    return (
      !!target?.closest?.("#columns-list") ||
      target?.id === "columns-list" ||
      !!target?.closest?.(".column-item[data-column-id]") ||
      !!target?.matches?.("[id^='cards-col-'], .column-item[data-column-id]")
    );
  }

  // -------------------------
  // HTMX: form inserido (GET do +Card)
  // -------------------------
  document.body.addEventListener("htmx:afterSwap", (e) => {
    const target = e.detail?.target || e.target || null;

    const form =
      target?.querySelector?.("form[data-add-card-form]") ||
      (target?.matches?.("form[data-add-card-form]") ? target : null);

    if (!form) return;

    const colId = getColIdFromForm(form);
    const where = getWhereFromForm(form);

    closeOppositeContainer(colId, where);

    const colEl = getColumnElById(colId) || form.closest("[data-column-id]");
    boing(colEl, where);

    bindEnterOnForm(form);

    // ordem correta: scroll primeiro, foco depois (evita o "puxa e volta")
    lockScroll(colId, where, 500);
    focusTitleInput(form);
  });

  // -------------------------
  // HTMX: antes do POST
  // -------------------------
  document.body.addEventListener("htmx:beforeRequest", (e) => {
    const elt = e.detail?.elt;
    if (!isAddCardForm(elt)) return;

    const colId = getColIdFromForm(elt);
    const where = getWhereFromForm(elt);

    rememberIntent(colId, where);
  });

  // -------------------------
  // HTMX: swap do board (fecha + trava scroll)
  // -------------------------
  document.body.addEventListener("htmx:afterSwap", (e) => {
    const target = e.detail?.target || e.target || null;
    if (!touchedBoardFromTarget(target)) return;

    for (const [colId, info] of pending.byCol.entries()) {
      if (Date.now() - (info.stamp || 0) > 8000) {
        pending.byCol.delete(colId);
        continue;
      }

      closeFormsInColumn(colId);

      // trava forte: resolve o "desce e depois sobe"
      lockScroll(colId, info.where, 900);

      const colEl = getColumnElById(colId);
      boing(colEl, info.where);

      // Pulso + scroll no card recém-criado.
      // info.where é a fonte da verdade (o form já foi removido acima).
      const list = document.getElementById(`cards-col-${colId}`);
      if (list) {
        const newCard = info.where === "top"
          ? list.firstElementChild
          : list.lastElementChild;
        if (newCard && newCard.matches?.("li[data-card-id]")) {
          requestAnimationFrame(() => {
            newCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
            newCard.classList.add("card-new-pulse");
            setTimeout(() => newCard.classList.remove("card-new-pulse"), 700);
          });

          // abre o card recém-criado pra continuar preenchendo (mesma UX do paste-create)
          const newCardId = newCard.getAttribute("data-card-id");
          if (newCardId && window.Modal && typeof window.Modal.openCard === "function") {
            window.Modal.openCard(newCardId, false, newCard);
          }
        }
      }

      pending.byCol.delete(colId);
    }
  });

  // -------------------------
  // HTMX: depois do request (limpa input se ainda existir)
  // -------------------------
  document.body.addEventListener("htmx:afterRequest", (e) => {
    const elt = e.detail?.elt;
    if (!isAddCardForm(elt)) return;

    const field =
      elt.querySelector("input[name='title'], textarea[name='title']") ||
      elt.querySelector("input[type='text'], input:not([type]), textarea");

    if (field) field.value = "";
  });

  // -------------------------
  // Cancelamento: clique fora / ESC
  // -------------------------
  document.addEventListener("click", (e) => {
    const insideForm = e.target.closest?.("form[data-add-card-form]");
    if (insideForm) return;

    const btn = e.target.closest?.("button");
    const txt = (btn?.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
    const isAddBtn = !!btn && (txt.includes("+ card") || txt.includes("+card"));
    if (isAddBtn) return;

    qsa("[id^='form-top-col-'], [id^='form-col-']").forEach((c) => {
      if (c && c.innerHTML.trim()) c.innerHTML = "";
    });
  }, true);

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    qsa("[id^='form-top-col-'], [id^='form-col-']").forEach((c) => {
      if (c && c.innerHTML.trim()) c.innerHTML = "";
    });
  }, true);
})();


(function () {
  if (window.__cmColumnBellyInstalled) return;
  window.__cmColumnBellyInstalled = true;

  function triggerBelly(colEl) {
    if (!colEl) return;

    colEl.classList.remove("col-belly");
    // força reflow para retrigger
    void colEl.offsetWidth;
    colEl.classList.add("col-belly");

    window.setTimeout(() => colEl.classList.remove("col-belly"), 300);
  }

  // Caso 1: HTMX swap quando move card (server render)
  document.body.addEventListener("htmx:afterSwap", (e) => {
    const target = e.detail?.target || e.target;
    const colEl = target?.closest?.("[data-column-id]");
    if (!colEl) return;
    // heurística: só anima se swap tocou uma lista de cards
    if (target?.matches?.("[id^='cards-col-']") || target?.closest?.("[id^='cards-col-']")) {
      triggerBelly(colEl);
    }
  });

  // Caso 2: sortable/drag client-side (se existir evento de drop)
  document.addEventListener("card:dropped", (e) => {
    // você dispara esse evento no seu drag/drop quando soltar o card
    triggerBelly(e.detail?.columnEl);
  });
})();


/* ============================================================
   VISUALIZADOR DE IMAGEM COM ZOOM (lightbox estilo HESK)
   Abre a imagem de um anexo em tela cheia com barra de comandos
   no topo (diminuir, aumentar, ajustar, %, baixar, fechar).
   Dispara no clique da miniatura de IMAGEM (.cm-attach-thumb[data-zoom-src]);
   vídeo e PDF seguem seu próprio caminho.
   Montado uma vez em <body>: sobrevive às trocas de tela do htmx.
   ============================================================ */
(function () {
  var overlay, imgEl, stageEl, titleEl, pctEl, dlEl;
  var natW = 1, natH = 1;           // tamanho natural da imagem carregada
  var fitScale = 1;                 // escala em que a imagem cabe na tela
  var scale = 1, tx = 0, ty = 0;    // estado atual (escala + deslocamento em px)
  var MIN = 0.05, MAX = 8, STEP = 1.2;
  var dragging = false, dragMoved = false, sx = 0, sy = 0, stx = 0, sty = 0;

  function svg(inner) {
    return '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" ' +
           'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
           'stroke-linejoin="round" aria-hidden="true">' + inner + '</svg>';
  }
  var ICONS = {
    out:  svg('<circle cx="10.5" cy="10.5" r="6.5"/><line x1="15.5" y1="15.5" x2="21" y2="21"/><line x1="7.5" y1="10.5" x2="13.5" y2="10.5"/>'),
    zin:  svg('<circle cx="10.5" cy="10.5" r="6.5"/><line x1="15.5" y1="15.5" x2="21" y2="21"/><line x1="7.5" y1="10.5" x2="13.5" y2="10.5"/><line x1="10.5" y1="7.5" x2="10.5" y2="13.5"/>'),
    fit:  svg('<path d="M4 9V5a1 1 0 0 1 1-1h4"/><path d="M20 9V5a1 1 0 0 0-1-1h-4"/><path d="M4 15v4a1 1 0 0 0 1 1h4"/><path d="M20 15v4a1 1 0 0 1-1 1h-4"/>'),
    dl:   svg('<path d="M12 3v12"/><path d="M7 12l5 5 5-5"/><path d="M5 21h14"/>'),
    x:    svg('<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>')
  };

  function build() {
    if (overlay) return;
    overlay = document.createElement("div");
    overlay.className = "cm-lightbox";
    overlay.id = "cm-lightbox";
    overlay.setAttribute("aria-hidden", "true");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-label", "Imagem");
    overlay.innerHTML =
      '<div class="cm-lb-bar">' +
        '<span class="cm-lb-title" id="cm-lb-title">Imagem</span>' +
        '<div class="cm-lb-tools">' +
          '<button type="button" class="cm-lb-btn" data-act="out" title="Diminuir (−)" aria-label="Diminuir zoom">' + ICONS.out + '</button>' +
          '<button type="button" class="cm-lb-btn" data-act="in" title="Aumentar (+)" aria-label="Aumentar zoom">' + ICONS.zin + '</button>' +
          '<button type="button" class="cm-lb-btn" data-act="fit" title="Ajustar à tela (0)" aria-label="Ajustar à tela">' + ICONS.fit + '</button>' +
          '<span class="cm-lb-pct" id="cm-lb-pct">100%</span>' +
          '<a class="cm-lb-btn" id="cm-lb-dl" download title="Baixar" aria-label="Baixar imagem">' + ICONS.dl + '</a>' +
          '<button type="button" class="cm-lb-btn cm-lb-close" data-act="close" title="Fechar (Esc)" aria-label="Fechar">' + ICONS.x + '</button>' +
        '</div>' +
      '</div>' +
      '<div class="cm-lb-stage" id="cm-lb-stage">' +
        '<img id="cm-lb-img" alt="" draggable="false">' +
      '</div>';
    document.body.appendChild(overlay);

    stageEl = overlay.querySelector("#cm-lb-stage");
    imgEl   = overlay.querySelector("#cm-lb-img");
    titleEl = overlay.querySelector("#cm-lb-title");
    pctEl   = overlay.querySelector("#cm-lb-pct");
    dlEl    = overlay.querySelector("#cm-lb-dl");

    overlay.querySelector(".cm-lb-tools").addEventListener("click", function (e) {
      var b = e.target.closest("[data-act]");
      if (!b) return;
      var act = b.getAttribute("data-act");
      if (act === "close") close();
      else if (act === "fit") resetFit();
      else if (act === "in")  zoomBy(STEP, 0, 0);
      else if (act === "out") zoomBy(1 / STEP, 0, 0);
    });

    // Clique no fundo (fora da imagem) fecha — mas não logo após um arraste
    stageEl.addEventListener("click", function (e) {
      if (dragMoved) { dragMoved = false; return; }
      if (e.target === stageEl) close();
    });

    // Roda do mouse = zoom centrado no ponteiro
    stageEl.addEventListener("wheel", function (e) {
      e.preventDefault();
      var r = stageEl.getBoundingClientRect();
      zoomBy(e.deltaY < 0 ? STEP : 1 / STEP,
             e.clientX - (r.left + r.width / 2),
             e.clientY - (r.top + r.height / 2));
    }, { passive: false });

    // Arrastar para mover (mouse e toque, via pointer events)
    stageEl.addEventListener("pointerdown", function (e) {
      dragging = true; dragMoved = false;
      sx = e.clientX; sy = e.clientY; stx = tx; sty = ty;
      try { stageEl.setPointerCapture(e.pointerId); } catch (_e) {}
    });
    stageEl.addEventListener("pointermove", function (e) {
      if (!dragging) return;
      var dx = e.clientX - sx, dy = e.clientY - sy;
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragMoved = true;
      tx = stx + dx; ty = sty + dy;
      clampPan(); apply();
    });
    function endDrag(e) {
      if (!dragging) return;
      dragging = false;
      try { stageEl.releasePointerCapture(e.pointerId); } catch (_e) {}
    }
    stageEl.addEventListener("pointerup", endDrag);
    stageEl.addEventListener("pointercancel", endDrag);

    // Duplo clique alterna entre ajustar e ~200%
    stageEl.addEventListener("dblclick", function (e) {
      var r = stageEl.getBoundingClientRect();
      var px = e.clientX - (r.left + r.width / 2);
      var py = e.clientY - (r.top + r.height / 2);
      if (scale > fitScale * 1.02) resetFit();
      else zoomTo(Math.max(fitScale * 2, 2), px, py);
    });

    imgEl.addEventListener("load", function () {
      natW = imgEl.naturalWidth || 1;
      natH = imgEl.naturalHeight || 1;
      resetFit();
    });
  }

  function apply() {
    imgEl.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + scale + ")";
    if (pctEl) pctEl.textContent = Math.round(scale * 100) + "%";
  }

  // Não deixa a imagem sair de vista: só permite deslocar até revelar as bordas.
  function clampPan() {
    var r = stageEl.getBoundingClientRect();
    var maxX = Math.max(0, (natW * scale - r.width) / 2);
    var maxY = Math.max(0, (natH * scale - r.height) / 2);
    if (tx > maxX) tx = maxX; if (tx < -maxX) tx = -maxX;
    if (ty > maxY) ty = maxY; if (ty < -maxY) ty = -maxY;
  }

  // Zoom mantendo fixo o ponto (px,py), medido a partir do centro do palco.
  function zoomTo(next, px, py) {
    next = Math.min(MAX, Math.max(MIN, next));
    var ix = (px - tx) / scale;
    var iy = (py - ty) / scale;
    scale = next;
    tx = px - ix * scale;
    ty = py - iy * scale;
    clampPan(); apply();
  }
  function zoomBy(factor, px, py) { zoomTo(scale * factor, px, py); }

  function resetFit() {
    var r = stageEl.getBoundingClientRect();
    fitScale = Math.min(r.width / natW, r.height / natH, 1) || 1;
    scale = fitScale; tx = 0; ty = 0;
    apply();
  }

  function open(src, name) {
    build();
    titleEl.textContent = name || "Imagem";
    dlEl.href = src;
    dlEl.setAttribute("download", name || "");
    natW = natH = 1; scale = 1; tx = ty = 0;
    imgEl.src = src;
    overlay.classList.add("is-on");
    overlay.setAttribute("aria-hidden", "false");
    document.documentElement.classList.add("cm-lb-lock");
    // imagem em cache pode não disparar "load" — trata na hora
    if (imgEl.complete && imgEl.naturalWidth) {
      natW = imgEl.naturalWidth; natH = imgEl.naturalHeight; resetFit();
    }
  }

  function close() {
    if (!overlay) return;
    overlay.classList.remove("is-on");
    overlay.setAttribute("aria-hidden", "true");
    document.documentElement.classList.remove("cm-lb-lock");
    imgEl.src = "";
  }

  // Abre no clique de qualquer [data-zoom-src] (miniatura do feed, link da aba
  // Anexos) — captura para vencer o target=_blank.
  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest("[data-zoom-src]") : null;
    if (!a) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return; // deixa abrir em nova aba
    var src = a.getAttribute("data-zoom-src");
    if (!src) return;
    e.preventDefault();
    // se o visualizador falhar por qualquer motivo, cai no antigo: abre a imagem crua
    try { open(src, a.getAttribute("data-zoom-name") || "Imagem"); }
    catch (_e) { window.open(src, "_blank", "noopener"); }
  }, true);

  // Imagem dentro da DESCRIÇÃO (editor Quill) também abre no visualizador.
  // Antes só as miniaturas do feed abriam; a imagem do relato de um chamado
  // ficava presa no tamanho do editor, sem zoom, e quem queria ver abria a
  // URL crua numa aba — sem comandos e sem o X pra voltar ao card.
  // Não cancela o evento: o Quill continua selecionando a imagem por baixo
  // (apagar/mover seguem funcionando quando o visualizador fecha).
  document.addEventListener("click", function (e) {
    var img = e.target && e.target.tagName === "IMG" ? e.target : null;
    if (!img || !img.closest || !img.closest(".ql-editor")) return;
    if (img.closest("[data-zoom-src]")) return;                 // já tratado acima
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
    var src = img.currentSrc || img.src;
    if (!src || (/^data:/i.test(src) && src.length > 4e6)) return; // colagem gigante ainda não salva
    var name = img.getAttribute("alt") || (src.split("/").filter(Boolean).pop() || "Imagem");
    try { open(src, name); } catch (_e) {}
  }, true);

  document.addEventListener("keydown", function (e) {
    if (!overlay || !overlay.classList.contains("is-on")) return;
    if (e.key === "Escape") close();
    else if (e.key === "+" || e.key === "=") zoomBy(STEP, 0, 0);
    else if (e.key === "-" || e.key === "_") zoomBy(1 / STEP, 0, 0);
    else if (e.key === "0") resetFit();
  });

  window.addEventListener("resize", function () {
    if (overlay && overlay.classList.contains("is-on")) { clampPan(); apply(); }
  });
})();


