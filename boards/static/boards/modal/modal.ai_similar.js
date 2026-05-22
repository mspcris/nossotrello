// boards/static/boards/modal/modal.ai_similar.js
// Verificação ON-DEMAND de cards semelhantes.
// - Ao abrir o modal, mostra o botão em estado "idle" (cinza, neutro).
// - Clique no botão idle abre um popover de confirmação ("Verificar?")
//   pra evitar embedding desnecessário em todo modal aberto.
// - Confirmado, faz fetch em /card/<id>/similar/ e mostra resultados.
// - Estados pós-busca:
//     alert  (count > 0) — bolinha colorida com "!" + popover de resultados
//     genuine (count = 0) — verde com ✓
//     error — cinza com ↻ (clique tenta de novo, sem confirmação)
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
      p = document.createElement("div");
      p.id = POP_ID;
      p.className = "modal-ai-similar-popover";
      p.setAttribute("role", "dialog");
      p.setAttribute("aria-label", "Cards semelhantes");
      p.hidden = true;
      document.body.appendChild(p);
    } else if (p.parentNode && p.parentNode !== document.body) {
      document.body.appendChild(p);
    }
    return p;
  }

  function hideBtn() {
    const btn = $btn();
    if (!btn) return;
    btn.classList.add("is-hidden");
    btn.setAttribute("hidden", "");
    btn.dataset.state = "";
    btn.dataset.threshold = "";
    btn.dataset.count = "";
    btn.textContent = "";
  }

  function setIdle() {
    const btn = $btn();
    if (!btn) return;
    btn.classList.remove("is-hidden");
    btn.removeAttribute("hidden");
    btn.dataset.state = "idle";
    btn.dataset.threshold = "";
    btn.dataset.count = "";
    btn.textContent = "?";
    btn.title = "Verificar cards parecidos";
    btn.setAttribute("aria-label", "Verificar cards parecidos");
  }

  function setLoading() {
    const btn = $btn();
    if (!btn) return;
    btn.classList.remove("is-hidden");
    btn.removeAttribute("hidden");
    btn.dataset.state = "loading";
    btn.dataset.threshold = "";
    btn.dataset.count = "";
    btn.textContent = "";
    btn.title = "Verificando similaridade…";
    btn.setAttribute("aria-label", "Verificando similaridade");
  }

  function setGenuine() {
    const btn = $btn();
    if (!btn) return;
    btn.classList.remove("is-hidden");
    btn.removeAttribute("hidden");
    btn.dataset.state = "genuine";
    btn.dataset.threshold = "";
    btn.dataset.count = "0";
    btn.textContent = "✓";
    btn.title = "Card genuíno — nada parecido encontrado";
    btn.setAttribute("aria-label", "Card genuíno");
  }

  function setError() {
    const btn = $btn();
    if (!btn) return;
    btn.classList.remove("is-hidden");
    btn.removeAttribute("hidden");
    btn.dataset.state = "error";
    btn.dataset.threshold = "";
    btn.dataset.count = "";
    btn.textContent = "!";
    btn.title = "Falha ao verificar — clique para tentar novamente";
    btn.setAttribute("aria-label", "Falha ao verificar — clique para tentar novamente");
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
    btn.dataset.state = "alert";
    btn.dataset.threshold = data.threshold || "low";
    btn.dataset.count = String(data.count || 0);
    btn.textContent = "!";
    const pct = data.max_score ? Math.round(data.max_score * 100) : null;
    btn.title = pct
      ? `${data.count} cards semelhantes (até ${pct}%)`
      : `${data.count} cards semelhantes`;
    btn.setAttribute("aria-label", "Cards semelhantes");
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

  function positionPop() {
    const p = $pop();
    const btn = $btn();
    if (!p || !btn) return;
    const r = btn.getBoundingClientRect();
    p.style.top = `${Math.round(r.bottom + 8)}px`;
    p.style.right = `${Math.max(8, Math.round(window.innerWidth - r.right))}px`;
  }

  function renderConfirmPopover() {
    const p = $pop();
    if (!p) return;
    p.innerHTML = `
      <div class="ai-sim-head ai-sim-head-low">
        💡 <strong>Verificar cards parecidos?</strong>
        <span class="ai-sim-sub">Compara este card com os demais que você tem acesso.</span>
      </div>
      <div class="ai-sim-confirm-actions">
        <button type="button" class="ai-sim-confirm-yes">Verificar</button>
        <button type="button" class="ai-sim-confirm-no">Cancelar</button>
      </div>
      <div class="ai-sim-foot">Pode levar 1-2 segundos.</div>
    `;
    positionPop();
    p.hidden = false;
    p.classList.add("is-open");
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
    positionPop();
    p.hidden = false;
    p.classList.add("is-open");
  }

  function renderGenuinePopover() {
    const p = $pop();
    if (!p) return;
    p.innerHTML = `
      <div class="ai-sim-head ai-sim-head-genuine">
        ✅ <strong>Card genuíno</strong>
        <span class="ai-sim-sub">Nada parecido nos quadros que você acessa.</span>
      </div>
      <div class="ai-sim-foot">Busca por similaridade semântica em todos os quadros que você tem acesso.</div>
    `;
    positionPop();
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

  async function runSimilarityCheck(cardId) {
    if (!cardId) return;
    setLoading();
    STATE.lastResponse = null;

    const reqId = Symbol("req");
    STATE.inFlight = reqId;

    const data = await fetchSimilar(cardId);
    if (STATE.inFlight !== reqId) return;

    if (data === null) {
      STATE.lastResponse = null;
      setError();
      return;
    }
    if (data && data.count) {
      STATE.lastResponse = data;
      showBtnFor(data);
      renderPopover(data);
    } else {
      STATE.lastResponse = { genuine: true };
      setGenuine();
      renderGenuinePopover();
    }
  }

  function onModalBodyReady() {
    closePopover();

    const cardId = getOpenCardId();
    STATE.currentCardId = cardId;
    STATE.lastResponse = null;
    STATE.inFlight = null;
    if (!cardId) { hideBtn(); return; }

    // ON-DEMAND: não dispara mais a busca automaticamente.
    // O botão aparece em estado idle e só consulta quando o usuário clica.
    setIdle();
  }

  function boot() {
    const body = document.getElementById("modal-body");
    if (!body) return;

    const mo = new MutationObserver(() => {
      if (document.getElementById("cm-root")) {
        onModalBodyReady();
      } else {
        closePopover();
        hideBtn();
        STATE.currentCardId = null;
      }
    });
    mo.observe(body, { childList: true, subtree: true });

    if (document.getElementById("cm-root")) {
      onModalBodyReady();
    }

    // Clique no botão: comportamento depende do estado.
    const btn = document.getElementById(BTN_ID);
    if (btn) {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const pop = $pop();
        if (!pop) return;
        const state = btn.dataset.state || "";
        if (state === "loading") return;

        // Popover já aberto → fecha (toggle)
        if (!pop.hidden) { closePopover(); return; }

        const cid = STATE.currentCardId || getOpenCardId();

        if (state === "idle") {
          // Primeira interação: pede confirmação antes de gastar embedding.
          renderConfirmPopover();
          return;
        }
        if (state === "error") {
          // Erro: tenta de novo direto, sem nova confirmação.
          if (cid) runSimilarityCheck(cid);
          return;
        }
        if (state === "genuine") {
          renderGenuinePopover();
          return;
        }
        // alert (resultados cached)
        if (STATE.lastResponse && STATE.lastResponse.results) {
          renderPopover(STATE.lastResponse);
        }
      });
    }

    // Clique nos botões DENTRO do popover de confirmação
    document.addEventListener("click", (ev) => {
      if (ev.target.closest?.(".ai-sim-confirm-yes")) {
        ev.preventDefault();
        ev.stopPropagation();
        closePopover();
        const cid = STATE.currentCardId || getOpenCardId();
        if (cid) runSimilarityCheck(cid);
        return;
      }
      if (ev.target.closest?.(".ai-sim-confirm-no")) {
        ev.preventDefault();
        ev.stopPropagation();
        closePopover();
        return;
      }
    });

    // Clique fora do popover ou ESC → fecha
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

    // Clique em um item abre o card correspondente no próprio modal
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
        window.Modal.openCard(nid, /* replaceUrl */ false, null);
      } else if (window.htmx?.ajax) {
        window.htmx.ajax("GET", url, { target: "#modal-body", swap: "innerHTML" });
      } else {
        window.location.href = url;
      }
    });

    document.addEventListener("modal:closed", () => {
      closePopover();
      hideBtn();
      STATE.currentCardId = null;
      STATE.lastResponse = null;
      STATE.inFlight = null;
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
