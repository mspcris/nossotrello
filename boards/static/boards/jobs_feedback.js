// boards/static/boards/jobs_feedback.js
// ------------------------------------------------------------
// Retorno ao usuário de operações que rodam na FILA (em segundo plano).
//
// Mover card agora responde na hora e grava depois, com 3 tentativas
// (boards.tasks.apply_card_move). Se nenhuma der certo, o servidor manda
// `card.move.failed` só para o autor (user.ws.js re-emite como evento
// `user:card.move.failed`). Aqui: mostra a mensagem e ressincroniza o quadro,
// devolvendo o card ao lugar onde ele realmente está.
// ------------------------------------------------------------
(function () {
  if (window.__NT_JOBS_FEEDBACK__) return;
  window.__NT_JOBS_FEEDBACK__ = true;

  function ensureHost() {
    var host = document.getElementById("nt-job-toasts");
    if (host) return host;
    host = document.createElement("div");
    host.id = "nt-job-toasts";
    host.setAttribute("role", "status");
    host.setAttribute("aria-live", "polite");
    host.style.cssText =
      "position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:2147483000;" +
      "display:flex;flex-direction:column;gap:8px;align-items:center;pointer-events:none;" +
      "width:min(92vw,520px)";
    document.body.appendChild(host);
    return host;
  }

  // kind: "error" | "info"
  window.ntJobToast = function (message, kind) {
    try {
      var host = ensureHost();
      var el = document.createElement("div");
      var isErr = kind === "error";
      el.textContent = String(message || "");
      el.style.cssText =
        "pointer-events:auto;cursor:pointer;box-sizing:border-box;width:100%;" +
        "padding:12px 16px;border-radius:12px;font:500 14px/1.35 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;" +
        "color:#f8fafc;box-shadow:0 10px 30px rgba(0,0,0,.35);" +
        "background:" + (isErr ? "#7f1d1d" : "#1e293b") + ";" +
        "border:1px solid " + (isErr ? "rgba(254,202,202,.35)" : "rgba(148,163,184,.35)") + ";" +
        "opacity:0;transform:translateY(8px);transition:opacity .18s ease,transform .18s ease";
      el.title = "Toque para fechar";
      host.appendChild(el);
      requestAnimationFrame(function () {
        el.style.opacity = "1";
        el.style.transform = "translateY(0)";
      });
      var close = function () {
        el.style.opacity = "0";
        el.style.transform = "translateY(8px)";
        setTimeout(function () { el.remove(); }, 220);
      };
      el.addEventListener("click", close);
      setTimeout(close, isErr ? 12000 : 5000);
    } catch (_e) {}
  };

  // ------------------------------------------------------------
  // Movimentos A CAMINHO: a tela já mostrou, o worker ainda não gravou.
  // Qualquer redesenho do quadro nesse intervalo (evento de outra mudança,
  // fechar o modal, polling) traz o HTML do servidor com o card no lugar
  // ANTIGO. Visto em 28/09: comentário subiu a versão do quadro 4 s antes do
  // mover, o worker levou 11 s, e o card voltou pra coluna de origem.
  // Por isso quem troca o HTML das colunas chama reapply() logo depois.
  // Sai do registro quando o servidor já mostra o card no destino, quando o
  // mover falha (card.move.failed) ou depois de PENDING_TTL_MS.
  // ------------------------------------------------------------
  var PENDING_TTL_MS = 60000;
  var pending = {};

  function cardsOf(list) {
    return Array.prototype.filter.call(list.children, function (c) {
      return c.matches && c.matches("li[data-card-id]");
    });
  }

  function bumpTotal(list, delta) {
    var col = list && list.closest && list.closest(".column-item[data-column-id]");
    var counter = col && col.querySelector("[data-column-counter]");
    if (!counter) return;
    var total = Number(counter.dataset.totalCount || 0);
    if (total > 0) counter.dataset.totalCount = String(Math.max(0, total + delta));
  }

  window.ntPendingMoves = {
    add: function (cardId, destColId, position, fromColId) {
      if (!cardId || !destColId) return;
      pending[String(cardId)] = {
        col: String(destColId),
        from: String(fromColId || ""),
        pos: Number(position) || 0,
        until: Date.now() + PENDING_TTL_MS,
      };
    },
    clear: function (cardId) {
      delete pending[String(cardId)];
    },
    reapply: function () {
      var changed = false;
      Object.keys(pending).forEach(function (cardId) {
        var mv = pending[cardId];
        if (Date.now() > mv.until) { delete pending[cardId]; return; }
        var li = document.querySelector('li[data-card-id="' + cardId + '"]');
        var dest = document.getElementById("cards-col-" + mv.col);
        if (!dest) {
          // destino em outro quadro: enquanto o servidor ainda mostra o card aqui, ele some
          if (li) { bumpTotal(li.parentElement, -1); li.remove(); changed = true; }
          else delete pending[cardId];
          return;
        }
        if (!li) return;
        var from = li.parentElement;
        if (from !== dest) {
          var sibs = cardsOf(dest);
          var idx = Math.max(0, Math.min(mv.pos, sibs.length));
          if (idx >= sibs.length) dest.appendChild(li);
          else dest.insertBefore(li, sibs[idx]);
          if (window.ntContadorNoTopo) window.ntContadorNoTopo(dest, li);
          bumpTotal(from, -1);
          bumpTotal(dest, +1);
          changed = true;
          return;
        }
        // servidor já mostra o card na coluna de destino de um movimento entre colunas: gravou
        if (mv.from && mv.from !== mv.col) { delete pending[cardId]; return; }
        // reordenação na mesma coluna: se recolocar não muda nada, o servidor já concorda
        var before = cardsOf(dest).indexOf(li);
        var others = cardsOf(dest).filter(function (c) { return c !== li; });
        var j = Math.max(0, Math.min(mv.pos, others.length));
        if (j >= others.length) dest.appendChild(li);
        else dest.insertBefore(li, others[j]);
        if (window.ntContadorNoTopo) window.ntContadorNoTopo(dest, li);
        if (cardsOf(dest).indexOf(li) === before) delete pending[cardId];
        else changed = true;
      });
      if (changed) {
        try { window.ntRefreshColumnCounters && window.ntRefreshColumnCounters(); } catch (_e) {}
        try { window.updateAggregatorCounts && window.updateAggregatorCounts(); } catch (_e) {}
      }
      return changed;
    },
  };

  window.addEventListener("user:card.move.failed", function (ev) {
    var d = (ev && ev.detail) || {};
    if (d.card_id) window.ntPendingMoves.clear(d.card_id);
    window.ntJobToast(d.message || "Não foi possível mover o card. Ele voltou ao lugar original.", "error");
    // só ressincroniza se o quadro aberto é o do card
    var here = Number(window.BOARD_ID || 0);
    if (!d.src_board_id || !here || Number(d.src_board_id) === here) {
      try { window.__ntForceBoardRefresh && window.__ntForceBoardRefresh(); } catch (_e) {}
    }
  });
})();
