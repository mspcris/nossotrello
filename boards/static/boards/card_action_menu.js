// boards/static/boards/card_action_menu.js
//
// FONTE ÚNICA do menu de ações do card. Um único menu (montado aqui em JS)
// é compartilhado por DOIS gatilhos:
//   1) o kebab ⋮ de cada card na board  (.card-kebab-btn)  -> popover ancorado no card
//   2) o FAB ⋮ do card modal            (#cm-dock-toggle)  -> popover ancorado no FAB
//
// Mexeu aqui, mudou nos dois lugares. Substitui o antigo modal.dock.js.
//
// Endpoints reusados (nenhuma view nova):
//   GET  /card/<id>/move/suggestions/   -> { suggestions: [...] }
//   POST /move-card/                    -> { column_id, snippet }
//   POST /card/<id>/duplicate/          -> { snippet, column_id }
//   GET  /card/<id>/move/options/       -> { boards, columns_by_board, current }
//   POST /card/<id>/archive/            -> 204 (HX-Redirect, ignorado)
//   POST /card/<id>/trash/              -> 204 (HX-Redirect, ignorado)
(function () {
  if (window.__cardActionMenuBound === true) return;
  window.__cardActionMenuBound = true;

  // ---------------------------------------------------------------- helpers
  function getCookie(name) {
    try {
      const v = document.cookie
        .split(";")
        .map((c) => c.trim())
        .find((c) => c.startsWith(name + "="));
      return v ? decodeURIComponent(v.split("=").slice(1).join("=")) : "";
    } catch (_e) {
      return "";
    }
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function clampInt(v, min, max, fallback) {
    const n = parseInt(String(v ?? ""), 10);
    if (!Number.isFinite(n)) return fallback;
    return Math.min(max, Math.max(min, n));
  }

  async function postJson(url, data) {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json;charset=UTF-8",
        "X-CSRFToken": getCookie("csrftoken"),
        "X-Requested-With": "XMLHttpRequest",
        Accept: "application/json, text/html;q=0.9, */*;q=0.8",
      },
      body: JSON.stringify(data || {}),
      credentials: "same-origin",
    });
    const text = await res.text();
    return { ok: res.ok, status: res.status, text };
  }

  // POST simples (arquivar/excluir). HX-Request faz a view responder 204 leve
  // (HX-Redirect) em vez de baixar a board inteira. Usamos fetch cru -> o
  // HX-Redirect é ignorado e atualizamos o DOM nós mesmos.
  async function postPlain(url) {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "X-CSRFToken": getCookie("csrftoken"),
        "X-Requested-With": "XMLHttpRequest",
        "HX-Request": "true",
      },
      credentials: "same-origin",
    });
    return res.ok;
  }

  function modalCardId() {
    const root = document.getElementById("cm-root");
    return root ? String(root.getAttribute("data-card-id") || root.dataset.cardId || "").trim() : "";
  }

  function closeModalIfOpen() {
    try {
      if (window.Modal && typeof window.Modal.close === "function") window.Modal.close();
    } catch (_e) {}
  }

  function bumpDestColumn(destList) {
    const destColEl = destList && destList.closest("[data-column-id]");
    if (!destColEl) return;
    destColEl.classList.remove("col-belly");
    void destColEl.offsetWidth;
    destColEl.classList.add("col-belly");
    setTimeout(() => destColEl.classList.remove("col-belly"), 400);
  }

  function afterDomMutation() {
    try { window.initSortable && window.initSortable(); } catch (_e) {}
    try { window.updateAggregatorCounts && window.updateAggregatorCounts(); } catch (_e) {}
    window.__skipBoardPollUntil = Date.now() + 500;
  }

  function replaceCardWithSnippet(cardId, snippet, destColId, { prepend } = {}) {
    const cardLi = document.querySelector(`li[data-card-id="${cardId}"]`);
    const destList = destColId ? document.getElementById(`cards-col-${destColId}`) : null;
    if (!cardLi || !snippet) return false;

    const tmp = document.createElement("div");
    tmp.innerHTML = String(snippet).trim();
    const newLi = tmp.firstElementChild;
    if (!newLi) return false;

    cardLi.replaceWith(newLi);
    if (destList) {
      if (prepend) destList.prepend(newLi);
      else destList.appendChild(newLi);
    }
    newLi.classList.add("card-new-pulse");
    setTimeout(() => newLi.classList.remove("card-new-pulse"), 700);
    requestAnimationFrame(() => newLi.scrollIntoView({ behavior: "smooth", block: "nearest" }));
    bumpDestColumn(destList || newLi.closest('[id^="cards-col-"]'));
    afterDomMutation();
    return true;
  }

  function removeCardFromDom(cardId) {
    const li = document.querySelector(`li[data-card-id="${cardId}"]`);
    if (li) li.remove();
    afterDomMutation();
  }

  // ---------------------------------------------------------------- menu DOM
  let menuEl = null;
  let currentCardId = null;
  let openedFromModal = false;
  let currentAnchor = null;

  function buildMenu() {
    const el = document.createElement("div");
    el.className = "bcm-menu";
    el.setAttribute("role", "menu");
    el.hidden = true;
    el.innerHTML = `
      <div class="bcm-suggestions" data-bcm-suggestions hidden></div>
      <button type="button" class="bcm-action" data-bcm="duplicate">
        <span>📄</span><span>Duplicar</span>
      </button>
      <button type="button" class="bcm-action" data-bcm="move">
        <span>↔️</span><span>Mover</span>
      </button>
      <button type="button" class="bcm-action" data-bcm="copylink">
        <span>🔗</span><span>Copiar link</span>
      </button>
      <div class="bcm-sep"></div>
      <button type="button" class="bcm-action" data-bcm="archive">
        <span>🗃️</span><span>Arquivar card</span>
      </button>
      <button type="button" class="bcm-action danger" data-bcm="trash">
        <span>🗑️</span><span>Excluir card</span>
      </button>
    `;
    document.body.appendChild(el);
    return el;
  }

  function ensureMenu() {
    if (!menuEl || !document.body.contains(menuEl)) menuEl = buildMenu();
    return menuEl;
  }

  function positionMenu(menu, anchorBtn) {
    if (!anchorBtn) return;
    menu.hidden = false; // precisa estar visível p/ medir
    const r = anchorBtn.getBoundingClientRect();
    const mw = menu.offsetWidth;
    const mh = menu.offsetHeight;
    const pad = 8;

    let left = r.right - mw; // alinha à direita do gatilho
    if (left < pad) left = pad;
    if (left + mw > window.innerWidth - pad) left = window.innerWidth - mw - pad;

    let top = r.bottom + 6; // abaixo do gatilho
    if (top + mh > window.innerHeight - pad) {
      top = r.top - mh - 6; // não cabe embaixo -> abre pra cima
      if (top < pad) top = pad;
    }
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
  }

  function closeMenu() {
    if (menuEl) menuEl.hidden = true;
    currentCardId = null;
    currentAnchor = null;
    openedFromModal = false;
    const fab = document.getElementById("cm-dock-toggle");
    if (fab) fab.setAttribute("aria-expanded", "false");
  }

  function renderDefaultMenu(menu) {
    const panel = menu.querySelector("[data-bcm-panel]");
    if (panel) panel.remove();
    menu.querySelectorAll("[data-bcm], .bcm-sep, .bcm-suggestions").forEach((n) => (n.style.display = ""));
  }

  async function openMenu(anchorBtn, cardId, fromModal) {
    const menu = ensureMenu();
    currentCardId = cardId;
    currentAnchor = anchorBtn;
    openedFromModal = !!fromModal;

    renderDefaultMenu(menu);
    positionMenu(menu, anchorBtn);

    const fab = document.getElementById("cm-dock-toggle");
    if (fab) fab.setAttribute("aria-expanded", fromModal ? "true" : "false");

    // sugestões de mover rápido (async)
    const sug = menu.querySelector("[data-bcm-suggestions]");
    sug.hidden = true;
    sug.innerHTML = "";
    try {
      const res = await fetch(`/card/${cardId}/move/suggestions/`, {
        headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (res.ok && currentCardId === cardId && !menu.hidden) {
        const data = await res.json();
        injectSuggestions(sug, data.suggestions || []);
        positionMenu(menu, anchorBtn); // altura mudou
      }
    } catch (_e) {}
  }

  function injectSuggestions(container, suggestions) {
    if (!suggestions.length) {
      container.innerHTML = `<div class="bcm-empty">Mova cards entre colunas para gerar atalhos aqui.</div>`;
      container.hidden = false;
      return;
    }
    const items = suggestions.map((s) => {
      const label = s.is_global
        ? `${escapeHtml(s.from_column_name)} → ${escapeHtml(s.to_column_name)}`
        : `→ ${escapeHtml(s.to_column_name)}`;
      const board = escapeHtml(s.to_board_name || "");
      const count = s.count > 1 ? `<span style="font-size:10px;color:rgba(15,23,42,.45);margin-left:auto;">${s.count}x</span>` : "";
      return `<button type="button" class="bcm-action" data-bcm="quickmove"
                data-to-col="${escapeHtml(String(s.to_column_id))}">
                <span>⚡</span>
                <span style="flex:1;display:flex;flex-direction:column;gap:1px;">
                  <span style="font-weight:600;">${label}</span>
                  ${board ? `<span style="font-size:10px;color:rgba(15,23,42,.5);">${board}</span>` : ""}
                </span>${count}
              </button>`;
    }).join("");
    container.innerHTML = `<div class="bcm-sug-title">Mover rápido</div>${items}`;
    container.hidden = false;
  }

  // ---------------------------------------------------------------- ações
  async function doQuickMove(cardId, toColId, fromModal) {
    closeMenu();
    if (!toColId) return;
    const res = await postJson("/move-card/", {
      card_id: parseInt(cardId, 10),
      new_column_id: parseInt(toColId, 10),
      new_position: 0,
    });
    if (!res.ok) return;
    try {
      const data = JSON.parse(res.text || "{}");
      if (!replaceCardWithSnippet(cardId, data.snippet, data.column_id, { prepend: true })) {
        removeCardFromDom(cardId);
      }
    } catch (_e) {}
    if (fromModal) closeModalIfOpen();
  }

  async function doDuplicate(cardId) {
    closeMenu();
    const res = await postJson(`/card/${cardId}/duplicate/`, {});
    if (!res.ok) return;
    try {
      const data = JSON.parse(res.text || "{}");
      const destList = document.getElementById(`cards-col-${data.column_id}`);
      const original = document.querySelector(`li[data-card-id="${cardId}"]`);
      if (data.snippet && destList) {
        const tmp = document.createElement("div");
        tmp.innerHTML = String(data.snippet).trim();
        const newLi = tmp.firstElementChild;
        if (newLi) {
          if (original && original.parentElement === destList) original.after(newLi);
          else destList.appendChild(newLi);
          newLi.classList.add("card-new-pulse");
          setTimeout(() => newLi.classList.remove("card-new-pulse"), 700);
          bumpDestColumn(destList);
          afterDomMutation();
        }
      }
    } catch (_e) {}
    // duplicar não mexe no card aberto -> mantém o modal como está
  }

  function doCopyLink(cardId) {
    closeMenu();
    const url = `${location.origin}${location.pathname}?card=${cardId}`;
    const fallback = () => {
      const tmp = document.createElement("input");
      tmp.value = url;
      document.body.appendChild(tmp);
      tmp.select();
      try { document.execCommand("copy"); } catch (_e) {}
      tmp.remove();
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).catch(fallback);
    } else {
      fallback();
    }
  }

  async function doArchive(cardId, fromModal) {
    closeMenu();
    if (!confirm("Arquivar este card? Ele vai sair do quadro e ir para Arquivados.")) return;
    const ok = await postPlain(`/card/${cardId}/archive/`);
    if (ok) removeCardFromDom(cardId);
    if (fromModal) closeModalIfOpen();
  }

  async function doTrash(cardId, fromModal) {
    closeMenu();
    if (!confirm("Enviar este card para a Lixeira?")) return;
    const ok = await postPlain(`/card/${cardId}/trash/`);
    if (ok) removeCardFromDom(cardId);
    if (fromModal) closeModalIfOpen();
  }

  // --------------------------------------------------- painel "Mover" (full)
  async function openMovePanel(menu, cardId, anchorBtn) {
    menu.querySelectorAll("[data-bcm], .bcm-sep, .bcm-suggestions").forEach((n) => (n.style.display = "none"));

    let panel = menu.querySelector("[data-bcm-panel]");
    if (!panel) {
      panel = document.createElement("div");
      panel.setAttribute("data-bcm-panel", "1");
      menu.appendChild(panel);
    }
    panel.style.display = "";
    panel.innerHTML = `<div class="bcm-empty">Carregando opções…</div>`;
    if (anchorBtn) positionMenu(menu, anchorBtn);

    let payload;
    try {
      const res = await fetch(`/card/${cardId}/move/options/`, {
        headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      payload = await res.json();
    } catch (_e) {
      panel.innerHTML = `<div class="bcm-err" style="display:block">Falha ao carregar opções de mover.</div>`;
      return;
    }

    panel.innerHTML = renderMovePanel(payload);
    if (anchorBtn) positionMenu(menu, anchorBtn);

    const boardSel = panel.querySelector("[data-bcm-board]");
    const colSel = panel.querySelector("[data-bcm-col]");
    const posSel = panel.querySelector("[data-bcm-pos]");

    function refreshPos(boardId, colId, sel) {
      const cols = (payload.columns_by_board || {})[boardId] || [];
      const col = cols.find((c) => String(c.id) === String(colId));
      const max = clampInt(col && col.positions_total_plus_one, 1, 9999, 1);
      const s = clampInt(sel, 1, max, 1);
      let out = "";
      for (let i = 1; i <= max; i++) out += `<option value="${i}"${i === s ? " selected" : ""}>${i}</option>`;
      posSel.innerHTML = out;
    }
    function refreshCols(boardId, keepSel) {
      const cols = (payload.columns_by_board || {})[boardId] || [];
      colSel.innerHTML =
        cols.map((c) => `<option value="${c.id}">${escapeHtml(c.name || "Coluna " + c.id)}</option>`).join("") ||
        `<option value="">(sem colunas)</option>`;
      if (keepSel) colSel.value = keepSel;
      refreshPos(boardId, String(colSel.value || ""), 1);
    }

    const cur = payload.current || {};
    if (boardSel && String(cur.board_id ?? "")) boardSel.value = String(cur.board_id);
    if (colSel && String(cur.column_id ?? "")) colSel.value = String(cur.column_id);
    if (boardSel && colSel && posSel) {
      const curPos = parseInt(cur.position_display ?? (parseInt(cur.position ?? 0, 10) + 1), 10) || 1;
      refreshPos(String(boardSel.value || ""), String(colSel.value || ""), curPos);
    }

    boardSel && boardSel.addEventListener("change", () => refreshCols(String(boardSel.value || "")));
    colSel && colSel.addEventListener("change", () =>
      refreshPos(String(boardSel.value || ""), String(colSel.value || ""), 1)
    );
  }

  function renderMovePanel(payload) {
    const boards = Array.isArray(payload.boards) ? payload.boards : [];
    const cur = payload.current || {};
    const curBoard = String(cur.board_id ?? "");
    const boardOpts = boards
      .map((b) => `<option value="${b.id}"${String(b.id) === curBoard ? " selected" : ""}>${escapeHtml(b.name || "Quadro " + b.id)}</option>`)
      .join("");
    const cols = (payload.columns_by_board || {})[curBoard] || [];
    const colOpts = cols
      .map((c) => `<option value="${c.id}"${String(c.id) === String(cur.column_id ?? "") ? " selected" : ""}>${escapeHtml(c.name || "Coluna " + c.id)}</option>`)
      .join("");
    return `
      <div class="bcm-label">Quadro</div>
      <select class="bcm-select" data-bcm-board>${boardOpts || `<option value="">(sem quadros)</option>`}</select>
      <div class="bcm-label">Coluna</div>
      <select class="bcm-select" data-bcm-col>${colOpts || `<option value="">(sem colunas)</option>`}</select>
      <div class="bcm-label">Posição</div>
      <select class="bcm-select" data-bcm-pos><option value="1">1</option></select>
      <div class="bcm-err" data-bcm-move-err></div>
      <div class="bcm-btns">
        <button type="button" class="bcm-btn" data-bcm="move-cancel">Cancelar</button>
        <button type="button" class="bcm-btn primary" data-bcm="move-apply">Aplicar</button>
      </div>`;
  }

  async function applyMove(menu, cardId, fromModal) {
    const panel = menu.querySelector("[data-bcm-panel]");
    const colId = panel?.querySelector("[data-bcm-col]")?.value;
    const posUi = panel?.querySelector("[data-bcm-pos]")?.value;
    const errEl = panel?.querySelector("[data-bcm-move-err]");
    if (!colId || !posUi) {
      if (errEl) { errEl.style.display = "block"; errEl.textContent = "Selecione coluna e posição."; }
      return;
    }
    const newPos = clampInt(parseInt(posUi, 10) - 1, 0, 999999, 0);
    const res = await postJson("/move-card/", {
      card_id: parseInt(cardId, 10),
      new_column_id: parseInt(colId, 10),
      new_position: newPos,
    });
    if (!res.ok) {
      if (errEl) { errEl.style.display = "block"; errEl.textContent = `Falha ao mover (HTTP ${res.status}).`; }
      return;
    }
    closeMenu();
    try {
      const data = JSON.parse(res.text || "{}");
      if (!replaceCardWithSnippet(cardId, data.snippet, data.column_id, { prepend: false })) {
        removeCardFromDom(cardId); // foi pra outro board -> some da view atual
      }
    } catch (_e) {
      removeCardFromDom(cardId);
    }
    if (fromModal) closeModalIfOpen();
  }

  // ---------------------------------------------------------------- eventos
  document.addEventListener("click", function (e) {
    // gatilho 1: kebab do card na board
    const kebab = e.target.closest && e.target.closest(".card-kebab-btn");
    if (kebab) {
      e.preventDefault();
      e.stopPropagation();
      const li = kebab.closest("li[data-card-id]");
      const cardId = li && li.getAttribute("data-card-id");
      if (!cardId) return;
      if (menuEl && !menuEl.hidden && currentCardId === cardId && !openedFromModal) {
        closeMenu();
        return;
      }
      openMenu(kebab, cardId, false);
      return;
    }

    // (gatilho 2: FAB ⋮ do modal é tratado em CAPTURE, mais abaixo — o
    //  #card-modal-root tem onclick="stopPropagation()" e mataria o clique
    //  antes de chegar a este listener de bubble.)

    // clique num item do menu
    const action = e.target.closest && e.target.closest(".bcm-menu [data-bcm]");
    if (action) {
      e.preventDefault();
      e.stopPropagation();
      const menu = ensureMenu();
      const cardId = currentCardId;
      const fromModal = openedFromModal;
      const anchor = currentAnchor;
      if (!cardId) { closeMenu(); return; }
      const kind = action.getAttribute("data-bcm");

      switch (kind) {
        case "quickmove": doQuickMove(cardId, action.getAttribute("data-to-col"), fromModal); break;
        case "duplicate": doDuplicate(cardId); break;
        case "copylink": doCopyLink(cardId); break;
        case "archive": doArchive(cardId, fromModal); break;
        case "trash": doTrash(cardId, fromModal); break;
        case "move": openMovePanel(menu, cardId, anchor); break;
        case "move-cancel": renderDefaultMenu(menu); openMenu(anchor, cardId, fromModal); break;
        case "move-apply": applyMove(menu, cardId, fromModal); break;
      }
      return;
    }

    // clique fora -> fecha (mas não se for no FAB, já tratado acima)
    if (menuEl && !menuEl.hidden && !(e.target.closest && e.target.closest(".bcm-menu"))) {
      closeMenu();
    }
  });

  // gatilho 2: FAB ⋮ do card modal — em CAPTURE porque o #card-modal-root
  // tem onclick="event.stopPropagation()" (não fechar no backdrop), o que
  // impediria o clique de borbulhar até o listener acima.
  document.addEventListener("click", function (e) {
    const fab = e.target.closest && e.target.closest("#cm-dock-toggle");
    if (!fab) return;
    e.preventDefault();
    e.stopPropagation();
    const cardId = modalCardId();
    if (!cardId) return;
    if (menuEl && !menuEl.hidden && openedFromModal) {
      closeMenu();
      return;
    }
    openMenu(fab, cardId, true);
  }, true);

  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  window.addEventListener("resize", closeMenu);
  document.addEventListener("scroll", closeMenu, true);

  // ------------------------------------------------ ciclo de vida do FAB/modal
  function showFab() {
    const dock = document.getElementById("cm-action-dock");
    if (dock) dock.hidden = false;
  }
  function hideFab() {
    const dock = document.getElementById("cm-action-dock");
    if (dock) dock.hidden = true;
    closeMenu();
  }

  document.body.addEventListener("htmx:afterSwap", (evt) => {
    const t = evt.detail?.target || evt.target;
    if (t && (t.id === "modal-body" || (t.closest && t.closest("#modal-body")))) {
      if (document.getElementById("cm-root")) showFab();
    }
  });
  document.addEventListener("modal:closed", hideFab);
  document.addEventListener("modal:close", hideFab);
})();
