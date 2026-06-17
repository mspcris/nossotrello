// boards/static/boards/aggregator_nav.js
//
// Clicar numa pílula da coluna agregadora ("Controle de Colunas") -> rola a
// board horizontalmente até a coluna correspondente e dá um flash forte nela.
//
// Robusto de propósito:
//  - delegação no document (funciona mesmo que a agregadora venha por htmx);
//  - o flash é aplicado por estilo INLINE (não depende do CSS em cache);
//  - as pílulas recebem pointer-events/cursor inline no template (server-fresh).
(function () {
  if (window.__aggNavBound === true) return;
  window.__aggNavBound = true;

  function flashColumn(col) {
    try {
      var ring = "inset 0 0 0 4px rgba(96,165,250,.98), inset 0 0 34px rgba(96,165,250,.6)";
      col.style.transition = "box-shadow .12s ease, background-color .12s ease";
      // pulso 1
      col.style.boxShadow = ring;
      col.style.backgroundColor = "rgba(96,165,250,.18)";
      setTimeout(function () { col.style.boxShadow = ""; col.style.backgroundColor = ""; }, 220);
      // pulso 2
      setTimeout(function () { col.style.boxShadow = ring; col.style.backgroundColor = "rgba(96,165,250,.18)"; }, 380);
      setTimeout(function () {
        col.style.boxShadow = "";
        col.style.backgroundColor = "";
        col.style.transition = "";
      }, 1000);
    } catch (_e) {}
  }

  document.addEventListener("click", function (e) {
    var pill = e.target && e.target.closest &&
      e.target.closest(".aggregator-column .aggregator-card[data-column-id]");
    if (!pill) return;

    var colId = pill.getAttribute("data-column-id");
    var wrap = document.getElementById("columns-wrapper");
    // escopa no wrapper visível (evita pegar .column-item de fora) — foi o que
    // funcionou no console.
    var col = (wrap || document).querySelector('.column-item[data-column-id="' + colId + '"]');
    if (!col) return;

    e.preventDefault();
    e.stopPropagation();

    // rola o wrapper horizontalmente até a coluna (scrollTo por offsetLeft
    // funcionou no teste; scrollIntoView nem sempre rolava o wrapper).
    if (wrap) {
      var left = col.offsetLeft - Math.max(0, (wrap.clientWidth - col.offsetWidth) / 2);
      try { wrap.scrollTo({ left: Math.max(0, left), behavior: "smooth" }); }
      catch (_e) { wrap.scrollLeft = Math.max(0, left); }
    } else {
      try { col.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" }); } catch (_e) {}
    }

    var done = false;
    function fire() {
      if (done) return;
      done = true;
      if (wrap) wrap.removeEventListener("scrollend", fire);
      flashColumn(col);
    }
    if (wrap) wrap.addEventListener("scrollend", fire, { once: true });
    setTimeout(fire, 600);
  }, true);
})();
