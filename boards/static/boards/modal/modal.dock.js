// boards/static/modal/modal.dock.js
(function () {
  if (window.__cmDockBound === true) return;
  window.__cmDockBound = true;

  // =========================
  // DEBUG
  // =========================
  // window.__cmDockDebug = true;
  function debug(...args) {
    if (window.__cmDockDebug === true) console.log("[cm.dock]", ...args);
  }

  // =========================
  // HELPERS
  // =========================
  function qs(root, sel) {
    return root ? root.querySelector(sel) : null;
  }

  function getRoot(scope) {
    return scope?.querySelector?.("#cm-root") || document.getElementById("cm-root");
  }

  function getCardId(root) {
    return String(root?.getAttribute?.("data-card-id") || root?.dataset?.cardId || "").trim();
  }

  function getDataUrl(dock, sel, attr) {
    const el = qs(dock, sel);
    const v = el?.getAttribute?.(attr);
    return v ? String(v).trim() : "";
  }

  function ensureButtonType(btn) {
    if (!btn) return;
    if (!btn.getAttribute("type")) btn.setAttribute("type", "button");
  }

  function ensureHidden(el) {
    if (!el) return;
    if (el.classList.contains("hidden")) el.style.display = "none";
  }

  function show(el) {
    if (!el) return;
    el.classList.remove("hidden");
    el.style.display = "block";
  }

  function hide(el) {
    if (!el) return;
    el.classList.add("hidden");
    el.style.display = "none";
  }

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

  function closeCardModal() {
    // tenta função global (se existir)
    if (typeof window.closeModal === "function") {
      try {
        window.closeModal();
        return;
      } catch (_e) {}
    }

    // fallback: tenta clicar no X do modal
    const x = document.querySelector("#modal .modal-top-x, #modal .modal-topbar-x, #modal .modal-x, #modal button[aria-label='Close']");
    if (x) {
      try {
        x.click();
        return;
      } catch (_e) {}
    }

    // fallback final: evento
    try {
      document.dispatchEvent(new CustomEvent("modal:close"));
    } catch (_e) {}
  }

  // =========================
  // DOCK PORTAL (evita fixed quebrar dentro do modal)
  // =========================
  function findDock(root) {
    const inRoot = qs(root, "#cm-action-dock");
    const inBody = document.body.querySelector('#cm-action-dock[data-cm-portaled="1"]');

    if (inRoot) {
      if (inBody && inBody !== inRoot) inBody.remove();
      return inRoot;
    }
    if (inBody) return inBody;
    return null;
  }

  function portalToBody(dock) {
    if (!dock) return null;
    dock.dataset.cmPortaled = "1";

    if (dock.parentElement !== document.body) {
      document.body.appendChild(dock);
    }

    dock.style.position = "fixed";
    dock.style.right = "18px";
    dock.style.bottom = "18px";
    dock.style.zIndex = "2147483647";
    dock.style.pointerEvents = "auto";

    const toggle = qs(dock, "#cm-dock-toggle");
    const menu = qs(dock, "#cm-dock-menu");
    const panel = qs(dock, "#cm-action-dock-panel");

    if (toggle) {
      ensureButtonType(toggle);
      if (!String(toggle.textContent || "").trim()) toggle.textContent = "⋮";

      toggle.style.pointerEvents = "auto";
      toggle.style.zIndex = "2147483647";
      toggle.style.width = "54px";
      toggle.style.height = "54px";
      toggle.style.borderRadius = "999px";
      toggle.style.border = "1px solid rgba(15,23,42,0.12)";
      toggle.style.background = "rgba(255,255,255,0.95)";
      toggle.style.boxShadow = "0 10px 30px rgba(2,6,23,0.18)";
      toggle.style.display = "flex";
      toggle.style.alignItems = "center";
      toggle.style.justifyContent = "center";
      toggle.style.fontSize = "22px";
      toggle.style.lineHeight = "1";
      toggle.style.cursor = "pointer";
      toggle.style.color = "rgba(15,23,42,0.92)";
    }

    if (menu) {
      menu.style.pointerEvents = "auto";
      menu.style.position = "absolute";
      menu.style.right = "0";
      menu.style.bottom = "64px";
      menu.style.minWidth = "210px";
      menu.style.borderRadius = "14px";
      menu.style.border = "1px solid rgba(15,23,42,0.12)";
      menu.style.background = "rgba(255,255,255,0.98)";
      menu.style.boxShadow = "0 10px 30px rgba(2,6,23,0.18)";
      menu.style.padding = "8px";
      menu.style.zIndex = "2147483647";
      ensureHidden(menu);
    }

    if (panel) {
      panel.style.pointerEvents = "auto";
      panel.style.position = "absolute";
      panel.style.right = "0";
      panel.style.bottom = "64px";
      panel.style.minWidth = "320px";
      panel.style.maxWidth = "520px";
      panel.style.borderRadius = "14px";
      panel.style.border = "1px solid rgba(15,23,42,0.12)";
      panel.style.background = "rgba(255,255,255,0.98)";
      panel.style.boxShadow = "0 10px 30px rgba(2,6,23,0.22)";
      panel.style.padding = "10px";
      panel.style.zIndex = "2147483647";
      ensureHidden(panel);
    }

    ["#cm-dock-duplicate", "#cm-dock-move", "#cm-dock-copylink"].forEach((id) => {
      const b = qs(dock, id);
      if (b) {
        ensureButtonType(b);
        b.style.pointerEvents = "auto";
      }
    });

    return dock;
  }

  function closeMenu(dock) {
    const menu = qs(dock, "#cm-dock-menu");
    const btn = qs(dock, "#cm-dock-toggle");
    if (menu) hide(menu);
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function openMenu(dock) {
    const menu = qs(dock, "#cm-dock-menu");
    const btn = qs(dock, "#cm-dock-toggle");
    if (menu) show(menu);
    if (btn) btn.setAttribute("aria-expanded", "true");
  }

  function toggleMenu(dock) {
    const menu = qs(dock, "#cm-dock-menu");
    if (!menu) return;
    menu.classList.contains("hidden") ? openMenu(dock) : closeMenu(dock);
  }

  function openPanel(dock) {
    const panel = qs(dock, "#cm-action-dock-panel");
    if (!panel) return;
    show(panel);
  }

  function closePanel(dock) {
    const panel = qs(dock, "#cm-action-dock-panel");
    const body = qs(dock, "#cm-dock-panel-body");
    if (body) body.innerHTML = "";
    if (panel) hide(panel);
  }

  function setPanelHtml(dock, html) {
    const body = qs(dock, "#cm-dock-panel-body");
    if (!body) return;
    body.innerHTML = html;
  }

  // =========================
  // MOVE UI (JSON -> HTML) + POSIÇÃO
  // =========================
  function getColumnPositionsTotalPlusOne(payload, boardId, columnId) {
    const colsByBoard = payload?.columns_by_board || {};
    const cols = Array.isArray(colsByBoard?.[boardId]) ? colsByBoard[boardId] : [];
    const col = cols.find((c) => String(c.id) === String(columnId));
    const n = parseInt(String(col?.positions_total_plus_one ?? ""), 10);
    return Number.isFinite(n) && n > 0 ? n : 1;
  }

  function buildPositionOptions(maxPos, selectedPos) {
    const maxN = clampInt(maxPos, 1, 9999, 1);
    const sel = clampInt(selectedPos, 1, maxN, 1);
    let out = "";
    for (let i = 1; i <= maxN; i++) {
      out += `<option value="${i}"${i === sel ? " selected" : ""}>${i}</option>`;
    }
    return out;
  }

  function inferCurrentPositionDisplay(payload) {
    const current = payload?.current || {};
    const pd = parseInt(String(current?.position_display ?? ""), 10);
    if (Number.isFinite(pd) && pd > 0) return pd;

    const p = parseInt(String(current?.position ?? ""), 10);
    if (Number.isFinite(p) && p >= 0) return p + 1;

    return 1;
  }

  function renderMoveUI(payload) {
    const boards = Array.isArray(payload?.boards) ? payload.boards : [];
    const colsByBoard = payload?.columns_by_board || {};
    const current = payload?.current || {};

    const currentBoardId = String(current?.board_id ?? "");
    const currentColId = String(current?.column_id ?? "");
    const currentPosDisplay = inferCurrentPositionDisplay(payload);

    const currentLabel = [
      current?.board_name ? escapeHtml(current.board_name) : "",
      current?.column_name ? escapeHtml(current.column_name) : "",
      currentPosDisplay ? `#${escapeHtml(String(currentPosDisplay))}` : "",
    ]
      .filter(Boolean)
      .join(" • ");

    const boardOptions = boards
      .map((b) => {
        const id = String(b.id);
        const name = escapeHtml(b.name || ("Quadro " + id));
        const sel = id === currentBoardId ? " selected" : "";
        return `<option value="${id}"${sel}>${name}</option>`;
      })
      .join("");

    const cols = Array.isArray(colsByBoard?.[currentBoardId]) ? colsByBoard[currentBoardId] : [];
    const colOptions = cols
      .map((c) => {
        const id = String(c.id);
        const name = escapeHtml(c.name || ("Coluna " + id));
        const sel = id === currentColId ? " selected" : "";
        return `<option value="${id}"${sel}>${name}</option>`;
      })
      .join("");

    const posMax = getColumnPositionsTotalPlusOne(payload, currentBoardId, currentColId);
    const posOptions = buildPositionOptions(posMax, currentPosDisplay);

    return `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px;">
        <div style="font-weight:800;color:rgba(15,23,42,.92)">Mover card</div>
        <button type="button" data-cm-move-close="1"
          style="border:0;background:transparent;font-size:18px;cursor:pointer;color:rgba(15,23,42,.55)">✕</button>
      </div>

      <div style="font-size:12px;color:rgba(15,23,42,.62);margin-bottom:10px;">
        Local atual: <b>${currentLabel || "—"}</b>
      </div>

      <div style="display:flex;flex-direction:column;gap:10px;">
        <div>
          <div style="font-size:12px;font-weight:700;margin-bottom:6px;color:rgba(15,23,42,.72)">Quadro</div>
          <select data-cm-move-board
            style="width:100%;padding:10px 12px;border-radius:12px;border:1px solid rgba(15,23,42,.12);background:#fff;">
            ${boardOptions || `<option value="">(sem quadros)</option>`}
          </select>
        </div>

        <div>
          <div style="font-size:12px;font-weight:700;margin-bottom:6px;color:rgba(15,23,42,.72)">Coluna</div>
          <select data-cm-move-column
            style="width:100%;padding:10px 12px;border-radius:12px;border:1px solid rgba(15,23,42,.12);background:#fff;">
            ${colOptions || `<option value="">(sem colunas)</option>`}
          </select>
        </div>

        <div>
          <div style="font-size:12px;font-weight:700;margin-bottom:6px;color:rgba(15,23,42,.72)">Posição</div>
          <select data-cm-move-position
            style="width:100%;padding:10px 12px;border-radius:12px;border:1px solid rgba(15,23,42,.12);background:#fff;">
            ${posOptions || `<option value="1">1</option>`}
          </select>
          <div style="margin-top:6px;font-size:11px;color:rgba(15,23,42,.55)">
            1 = primeiro • ${escapeHtml(String(posMax))} = último (na coluna selecionada)
          </div>
        </div>

        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:4px;">
          <button type="button" data-cm-move-cancel="1"
            style="padding:10px 12px;border-radius:12px;border:1px solid rgba(15,23,42,.12);background:#fff;cursor:pointer;">
            Cancelar
          </button>
          <button type="button" data-cm-move-apply="1"
            style="padding:10px 12px;border-radius:12px;border:1px solid rgba(37,99,235,.25);background:rgba(37,99,235,.10);cursor:pointer;font-weight:800;">
            Aplicar
          </button>
        </div>

        <div data-cm-move-error
          style="display:none;padding:10px 12px;border-radius:12px;border:1px solid rgba(220,38,38,.25);background:rgba(220,38,38,.08);color:rgba(153,27,27,.95);font-size:12px;"></div>
      </div>
    `;
  }

  function updateColumnsSelect(panelBodyEl, payload, boardId) {
    const colsByBoard = payload?.columns_by_board || {};
    const cols = Array.isArray(colsByBoard?.[boardId]) ? colsByBoard[boardId] : [];
    const colSel = panelBodyEl.querySelector("[data-cm-move-column]");
    if (!colSel) return;

    colSel.innerHTML =
      cols
        .map((c) => {
          const id = String(c.id);
          const name = escapeHtml(c.name || ("Coluna " + id));
          return `<option value="${id}">${name}</option>`;
        })
        .join("") || `<option value="">(sem colunas)</option>`;
  }

  function updatePositionsSelect(panelBodyEl, payload, boardId, columnId, selectedPos) {
    const posSel = panelBodyEl.querySelector("[data-cm-move-position]");
    if (!posSel) return;

    const maxPos = getColumnPositionsTotalPlusOne(payload, boardId, columnId);
    posSel.innerHTML = buildPositionOptions(maxPos, selectedPos);

    const hint = posSel.parentElement?.querySelector?.("div[style*='font-size:11px']");
    if (hint) {
      hint.innerHTML = `1 = primeiro • ${escapeHtml(String(maxPos))} = último (na coluna selecionada)`;
    }
  }

  function showPanelError(dock, msg) {
    const body = qs(dock, "#cm-dock-panel-body");
    if (!body) return;

    const el = body.querySelector("[data-cm-move-error]");
    if (!el) return;

    el.style.display = "block";
    el.textContent = String(msg || "Erro desconhecido.");
  }

  // =========================
  // NETWORK
  // =========================
  async function fetchMoveOptions(url) {
    const res = await fetch(url, {
      method: "GET",
      headers: {
        Accept: "application/json, text/html;q=0.9, */*;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
        "HX-Request": "true",
      },
      credentials: "same-origin",
    });

    const ctype = String(res.headers.get("content-type") || "").toLowerCase();
    const text = await res.text();

    if (ctype.includes("application/json") || text.trim().startsWith("{") || text.trim().startsWith("[")) {
      try {
        return { kind: "json", payload: JSON.parse(text), raw: text, status: res.status };
      } catch (_e) {
        return { kind: "text", payload: text, raw: text, status: res.status, contentType: ctype };
      }
    }

    return { kind: "text", payload: text, raw: text, status: res.status, contentType: ctype };
  }

  async function postMoveApplyJson(url, data) {
    const csrftoken = getCookie("csrftoken");

    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json;charset=UTF-8",
        "X-CSRFToken": csrftoken,
        "X-Requested-With": "XMLHttpRequest",
        "HX-Request": "true",
        Accept: "application/json, text/html;q=0.9, */*;q=0.8",
      },
      body: JSON.stringify(data || {}),
      credentials: "same-origin",
    });

    const text = await res.text();
    return { ok: res.ok, status: res.status, text };
  }

  // =========================
  // BIND
  // =========================
  function bindDock(scope) {
    const root = getRoot(scope);
    if (!root) return;

    let dock = findDock(root);
    if (!dock) return;

    dock = portalToBody(dock);
    if (!dock) return;

    if (dock.dataset.cmDockBound === "1") return;
    dock.dataset.cmDockBound = "1";

    const toggleBtn = qs(dock, "#cm-dock-toggle");
    const menu = qs(dock, "#cm-dock-menu");
    if (!toggleBtn || !menu) return;

    closeMenu(dock);
    closePanel(dock);

    toggleBtn.addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      toggleMenu(dock);
    });

    document.addEventListener("click", function (e) {
      const inside = e.target && e.target.closest && e.target.closest("#cm-action-dock");
      if (!inside) {
        closeMenu(dock);
        closePanel(dock);
      }
    });

    dock.addEventListener("click", async function (e) {
      const btn = e.target && e.target.closest ? e.target.closest("button") : null;
      if (!btn) return;
      if (btn.id === "cm-dock-toggle") return;

      e.preventDefault();
      e.stopPropagation();

      const cardId = getCardId(root);
      if (!cardId) {
        debug("Sem cardId no #cm-root");
        closeMenu(dock);
        return;
      }

      if (btn.getAttribute("data-cm-move-close") === "1" || btn.getAttribute("data-cm-move-cancel") === "1") {
        closePanel(dock);
        return;
      }

      if (btn.id === "cm-dock-copylink") {
        const url = window.location.href;
        try {
          await navigator.clipboard.writeText(url);
        } catch (_e) {
          const tmp = document.createElement("input");
          tmp.value = url;
          document.body.appendChild(tmp);
          tmp.select();
          document.execCommand("copy");
          tmp.remove();
        }
        closeMenu(dock);
        return;
      }

      if (btn.id === "cm-dock-duplicate") {
        closeMenu(dock);

        const url = getDataUrl(dock, "#cm-dock-duplicate", "data-url-duplicate") || `/cards/${cardId}/duplicate/`;
        debug("Duplicate POST", url);

        if (!window.htmx) {
          root.dispatchEvent(new CustomEvent("cm:dock:duplicate", { bubbles: true }));
          return;
        }

        window.htmx.ajax("POST", url, { swap: "none" });

        if (typeof window.refreshCardSnippet === "function") {
          try {
            window.refreshCardSnippet(cardId);
          } catch (_e) {}
        }
        return;
      }

      if (btn.id === "cm-dock-move") {
        closeMenu(dock);

        const url = getDataUrl(dock, "#cm-dock-move", "data-url-move") || `/card/${cardId}/move/options/`;
        debug("Move OPTIONS GET", url);

        openPanel(dock);
        setPanelHtml(dock, `<div style="padding:8px;font-size:12px;color:rgba(15,23,42,.62)">Carregando opções…</div>`);

        try {
          const r = await fetchMoveOptions(url);

          if (r.kind === "text") {
            const txt = String(r.payload || "");
            if (txt.trim().startsWith("{")) {
              setPanelHtml(dock, `<pre style="white-space:pre-wrap;font-size:12px">${escapeHtml(txt)}</pre>`);
              showPanelError(dock, "Endpoint retornou JSON como texto/sem header. Ajuste Content-Type para application/json.");
              return;
            }
            setPanelHtml(dock, txt);
            return;
          }

          const payload = r.payload || {};
          setPanelHtml(dock, renderMoveUI(payload));

          const panelBody = qs(dock, "#cm-dock-panel-body");
          if (!panelBody) return;

          const boardSel = panelBody.querySelector("[data-cm-move-board]");
          const colSel = panelBody.querySelector("[data-cm-move-column]");
          const posSel = panelBody.querySelector("[data-cm-move-position]");

          const cur = payload?.current || {};
          const curBoardId = String(cur?.board_id ?? "");
          const curColId = String(cur?.column_id ?? "");
          const curPos = inferCurrentPositionDisplay(payload);

          if (boardSel && curBoardId) boardSel.value = curBoardId;
          if (colSel && curColId) colSel.value = curColId;

          if (boardSel && colSel && posSel) {
            updatePositionsSelect(panelBody, payload, String(boardSel.value || ""), String(colSel.value || ""), curPos);
          }

          if (boardSel) {
            boardSel.addEventListener("change", function () {
              const bId = String(boardSel.value || "");
              updateColumnsSelect(panelBody, payload, bId);

              const newColSel = panelBody.querySelector("[data-cm-move-column]");
              const firstCol = String(newColSel?.value || "");
              updatePositionsSelect(panelBody, payload, bId, firstCol, 1);
            });
          }

          if (colSel && boardSel) {
            colSel.addEventListener("change", function () {
              const bId = String(boardSel.value || "");
              const cId = String(colSel.value || "");
              updatePositionsSelect(panelBody, payload, bId, cId, 1);
            });
          }

          return;
        } catch (err) {
          setPanelHtml(dock, `<div style="padding:10px 12px;font-size:12px;color:rgba(153,27,27,.95)">Falha ao carregar opções de mover.</div>`);
          debug("Move options error", err);
          return;
        }
      }

      // APPLY MOVE (POST REAL: /move-card/)
      if (btn.getAttribute("data-cm-move-apply") === "1") {
        const panelBody = qs(dock, "#cm-dock-panel-body");
        const boardSel = panelBody?.querySelector?.("[data-cm-move-board]");
        const colSel = panelBody?.querySelector?.("[data-cm-move-column]");
        const posSel = panelBody?.querySelector?.("[data-cm-move-position]");

        const boardId = String(boardSel?.value || "").trim();
        const columnId = String(colSel?.value || "").trim();
        const positionUi = String(posSel?.value || "").trim(); // 1-based

        if (!boardId || !columnId || !positionUi) {
          showPanelError(dock, "Selecione um quadro, uma coluna e uma posição.");
          return;
        }

        const cardId2 = getCardId(getRoot(document));
        if (!cardId2) {
          showPanelError(dock, "CardId não encontrado no DOM.");
          return;
        }

        // BACKEND: move_card recebe 0-based
        const newPosition = clampInt(parseInt(positionUi, 10) - 1, 0, 999999, 0);

        // POST CERTO
        const moveUrl = "/move-card/";
        debug("Move APPLY POST", moveUrl, { card_id: cardId2, new_column_id: columnId, new_position: newPosition });

        setPanelHtml(dock, `<div style="padding:8px;font-size:12px;color:rgba(15,23,42,.62)">Movendo…</div>`);

        try {
          const res = await postMoveApplyJson(moveUrl, {
            card_id: parseInt(cardId2, 10),
            new_column_id: parseInt(columnId, 10),
            new_position: newPosition,
          });

          if (!res.ok) {
            setPanelHtml(
              dock,
              renderMoveUI({ boards: [], columns_by_board: {}, current: {} }) +
                `<div style="margin-top:10px;font-size:12px;color:rgba(153,27,27,.95)">
                   Backend recusou o POST (HTTP ${res.status}). Resposta:
                 </div>
                 <pre style="white-space:pre-wrap;font-size:12px;padding:10px 12px;border-radius:12px;border:1px solid rgba(220,38,38,.25);background:rgba(220,38,38,.06)">${escapeHtml(res.text)}</pre>`
            );
            return;
          }

          // refresh snippet e fecha modal
          if (typeof window.refreshCardSnippet === "function") {
            try {
              window.refreshCardSnippet(cardId2);
            } catch (_e) {}
          }

          closeMenu(dock);
          closePanel(dock);

          setTimeout(() => closeCardModal(), 0);
          return;
        } catch (err) {
          setPanelHtml(dock, renderMoveUI({ boards: [], columns_by_board: {}, current: {} }));
          showPanelError(dock, "Falha ao mover. Ative __cmDockDebug para diagnóstico.");
          debug("Move apply error", err);
          return;
        }
      }
    });

    debug("Dock bound OK");
  }

  // =========================
  // LIFECYCLE
  // =========================
  document.addEventListener("DOMContentLoaded", () => bindDock(document));

  document.body.addEventListener("htmx:afterSwap", (evt) => {
    const t = evt.detail?.target || evt.target;
    if (!t) return;
    if (t.id === "modal-body" || (t.closest && t.closest("#modal-body"))) {
      bindDock(document);
    }
  });

  document.body.addEventListener("htmx:afterSettle", (evt) => {
    const t = evt.detail?.target || evt.target;
    if (!t) return;
    if (t.id === "modal-body" || (t.closest && t.closest("#modal-body"))) {
      bindDock(document);
    }
  });

  document.addEventListener("modal:closed", () => {
    const dock = document.body.querySelector('#cm-action-dock[data-cm-portaled="1"]');
    if (dock) dock.remove();
  });
})();
