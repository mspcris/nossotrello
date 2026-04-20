// boards/static/boards/modal/modal.ai_similar.js
// Detecção automática de cards semelhantes quando o modal do card abre.
// - Faz fetch em /card/<id>/similar/
// - Mostra botão "!" ao lado do X do modal se houver similaridade >= 50%
// - Cor/intensidade conforme threshold:
//     high   (>= 90%) — incisivo (vermelho)
//     medium (>= 70%) — ponderado (âmbar)
//     low    (>= 50%) — comunicativo (azul)
// - Popover com lista ao clicar; cada item abre o card via Modal.open().
(() => {
  if (window.__aiSimilarLoaded) return;
  window.__aiSimilarLoaded = true;

  const BTN_ID = "modal-ai-similar-btn";
  const POP_ID = "modal-ai-similar-popover";
  const MIN_SCORE = 0.5;

  const STATE = {
    currentCardId: null,
    lastResponse: null,
    inFlight: null,
  };

  function $btn() { return document.getElementById(BTN_ID); }
  function $pop() {
    let p = document.getElementById(POP_ID);
    if (!p) {
      // cria o popover direto no body (evita stacking context do modal)
      p = document.createElement("div");
      p.id = POP_ID;
      p.className = "modal-ai-similar-popover";
      p.setAttribute("role", "dialog");
      p.setAttribute("aria-label", "Cards semelhantes");
      p.hidden = true;
      document.body.appendChild(p);
    } else if (p.parentNode && p.parentNode !== document.body) {
      // move pra body caso tenha ficado dentro do modal
      document.body.appendChild(p);
    }
    return p;
  }

  function resetBtn() {
    const btn = $btn();
    if (!btn) return;
    btn.classList.add("is-hidden");
    btn.setAttribute("hidden", "");
    btn.dataset.threshold = "";
    btn.dataset.count = "";
    btn.removeAttribute("data-threshold");
  }

  function closePopover() {
    const p = $pop();
    if (!p) return;
    p.hidden = true;
    p.classList.remove("is-open");
    p.innerHTML = "";
  }

  function showBtnFor(data) {
    const btn = $btn();
    if (!btn) return;
    btn.classList.remove("is-hidden");
    btn.removeAttribute("hidden");
    btn.dataset.threshold = data.threshold || "low";
    btn.dataset.count = String(data.count || 0);
    const pct = data.max_score ? Math.round(data.max_score * 100) : null;
    btn.title = pct
      ? `${data.count} cards semelhantes (até ${pct}%)`
      : `${data.count} cards semelhantes`;
  }

  function statusBadge(status) {
    if (status === "archived") {
      return `<span class="ai-sim-badge ai-sim-badge-archived" title="Card arquivado">📦 Arquivado</span>`;
    }
    if (status === "deleted") {
      return `<span class="ai-sim-badge ai-sim-badge-deleted" title="Card na lixeira">🗑️ Excluído</span>`;
    }
    return "";
  }

  function thresholdHeadline(threshold, pct) {
    if (threshold === "high") {
      return `<div class="ai-sim-head ai-sim-head-high">
        ⚠️ <strong>Já tem outro bem parecido!</strong>
        <span class="ai-sim-sub">Maior similaridade: ${pct}%</span>
      </div>`;
    }
    if (threshold === "medium") {
      return `<div class="ai-sim-head ai-sim-head-med">
        🤔 <strong>Vale checar</strong> se já existe algo similar
        <span class="ai-sim-sub">Maior similaridade: ${pct}%</span>
      </div>`;
    }
    return `<div class="ai-sim-head ai-sim-head-low">
      💡 Encontrei cards relacionados
      <span class="ai-sim-sub">Maior similaridade: ${pct}%</span>
    </div>`;
  }

  function renderPopover(data) {
    const p = $pop();
    const btn = $btn();
    if (!p || !btn) return;

    const pct = data.max_score ? Math.round(data.max_score * 100) : 0;
    const itemsHtml = (data.results || []).map((it) => {
      const itemPct = it.percent;
      const statusCls = it.status && it.status !== "active"
        ? `ai-sim-item-${it.status}` : "";
      return `
        <li class="ai-sim-item ${statusCls}">
          <button type="button" class="ai-sim-item-btn"
                  data-modal-url="${it.modal_url}"
                  data-card-id="${it.id}">
            <div class="ai-sim-item-top">
              <span class="ai-sim-pct ai-sim-pct-${classifyPct(itemPct)}">${itemPct}%</span>
              <span class="ai-sim-title">${escapeHtml(it.title)}</span>
            </div>
            <div class="ai-sim-item-meta">
              <span class="ai-sim-board">${escapeHtml(it.board)}</span>
              <span class="ai-sim-sep">·</span>
              <span class="ai-sim-column">${escapeHtml(it.column)}</span>
              ${statusBadge(it.status)}
            </div>
          </button>
        </li>`;
    }).join("");

    p.innerHTML = `
      ${thresholdHeadline(data.threshold, pct)}
      <ul class="ai-sim-list">${itemsHtml || '<li class="ai-sim-empty">Nada encontrado.</li>'}</ul>
      <div class="ai-sim-foot">Busca por similaridade semântica em todos os quadros que você tem acesso.</div>
    `;

    // posiciona perto do botão
    const r = btn.getBoundingClientRect();
    p.style.top = `${Math.round(r.bottom + 8)}px`;
    p.style.right = `${Math.max(8, Math.round(window.innerWidth - r.right))}px`;
    p.hidden = false;
    p.classList.add("is-open");
  }

  function classifyPct(pct) {
    if (pct >= 90) return "high";
    if (pct >= 70) return "medium";
    return "low";
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  async function fetchSimilar(cardId) {
    if (!cardId) return null;
    try {
      const resp = await fetch(`/card/${cardId}/similar/?min_score=${MIN_SCORE}&top_k=5`, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!resp.ok) return null;
      const data = await resp.json();
      if (!data || !data.ok) return null;
      return data;
    } catch (e) {
      console.warn("[ai_similar] fetch falhou", e);
      return null;
    }
  }

  function getOpenCardId() {
    const root = document.getElementById("cm-root");
    if (!root) return null;
    const id = root.getAttribute("data-card-id");
    return id ? Number(id) : null;
  }

  async function onModalBodyReady() {
    closePopover();
    resetBtn();

    const cardId = getOpenCardId();
    if (!cardId || cardId === STATE.currentCardId) {
      // mesma aba/card, nada a fazer
    }
    STATE.currentCardId = cardId;
    if (!cardId) return;

    if (STATE.inFlight) STATE.inFlight = null;

    const reqId = Symbol("req");
    STATE.inFlight = reqId;

    const data = await fetchSimilar(cardId);
    if (STATE.inFlight !== reqId) return; // corrida: já houve outro pedido

    if (!data || !data.count) return;
    STATE.lastResponse = data;
    showBtnFor(data);
  }

  // Observa trocas de conteúdo no #modal-body (HTMX swap)
  function boot() {
    const body = document.getElementById("modal-body");
    if (!body) return;

    const mo = new MutationObserver(() => {
      if (document.getElementById("cm-root")) {
        onModalBodyReady();
      } else {
        closePopover();
        resetBtn();
        STATE.currentCardId = null;
      }
    });
    mo.observe(body, { childList: true, subtree: true });

    // também tenta no load inicial (caso já tenha conteúdo)
    if (document.getElementById("cm-root")) {
      onModalBodyReady();
    }

    // clique no botão abre/fecha popover
    const btn = document.getElementById(BTN_ID);
    if (btn) {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const pop = $pop();
        if (!pop) return;
        if (!pop.hidden) { closePopover(); return; }
        if (STATE.lastResponse) renderPopover(STATE.lastResponse);
      });
    }

    // clique fora do popover ou ESC → fecha
    document.addEventListener("click", (ev) => {
      const pop = $pop();
      if (!pop || pop.hidden) return;
      if (pop.contains(ev.target)) return;
      if (ev.target.closest?.(`#${BTN_ID}`)) return;
      closePopover();
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") closePopover();
    });

    // clique em um item abre o card correspondente no próprio modal
    document.addEventListener("click", (ev) => {
      const b = ev.target.closest?.(".ai-sim-item-btn");
      if (!b) return;
      const url = b.getAttribute("data-modal-url");
      const id = b.getAttribute("data-card-id");
      if (!url || !id) return;
      ev.preventDefault();
      ev.stopPropagation();
      closePopover();
      const nid = Number(id);
      if (window.Modal && typeof window.Modal.openCard === "function") {
        // API interna do projeto — carrega + abre + atualiza URL
        window.Modal.openCard(nid, /* replaceUrl */ false, null);
      } else if (window.htmx?.ajax) {
        // fallback: troca o conteúdo via HTMX (modal já está aberto)
        window.htmx.ajax("GET", url, { target: "#modal-body", swap: "innerHTML" });
      } else {
        // fallback final: navega
        window.location.href = url;
      }
    });

    // Quando o modal fecha, limpa estado
    document.addEventListener("modal:closed", () => {
      closePopover();
      resetBtn();
      STATE.currentCardId = null;
      STATE.lastResponse = null;
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
