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

  window.addEventListener("user:card.move.failed", function (ev) {
    var d = (ev && ev.detail) || {};
    window.ntJobToast(d.message || "Não foi possível mover o card. Ele voltou ao lugar original.", "error");
    // só ressincroniza se o quadro aberto é o do card
    var here = Number(window.BOARD_ID || 0);
    if (!d.src_board_id || !here || Number(d.src_board_id) === here) {
      try { window.__ntForceBoardRefresh && window.__ntForceBoardRefresh(); } catch (_e) {}
    }
  });
})();
