// boards/static/boards/aggregator_nav.js
//
// Clicar numa pílula da coluna agregadora -> rola a board horizontalmente até
// a coluna correspondente e dá um flash forte nela.
//
// A função é exposta como window.__aggNavGo e chamada por um onclick INLINE na
// própria pílula (dispara no alvo, antes de qualquer handler/Sortable engolir o
// clique no caminho). Também há uma delegação no document como reforço.
(function () {
  function flash(col) {
    try {
      col.style.transition = "box-shadow .12s ease, background-color .12s ease";
      col.style.boxShadow = "inset 0 0 0 4px #60a5fa, inset 0 0 30px rgba(96,165,250,.5)";
      col.style.backgroundColor = "rgba(96,165,250,.16)";
      setTimeout(function () {
        col.style.boxShadow = "";
        col.style.backgroundColor = "";
      }, 1100);
    } catch (_e) {}
  }

  function goToColumn(colId) {
    if (colId == null) return;
    var wrap = document.getElementById("columns-wrapper");
    var col = (wrap || document).querySelector('.column-item[data-column-id="' + colId + '"]');
    if (!col || !wrap) return;
    var left = col.offsetLeft - Math.max(0, (wrap.clientWidth - col.offsetWidth) / 2);
    try { wrap.scrollTo({ left: Math.max(0, left), behavior: "smooth" }); }
    catch (_e) { wrap.scrollLeft = Math.max(0, left); }
    setTimeout(function () { flash(col); }, 320);
  }

  // chamada pelo onclick inline da pílula (ex.: onclick="window.__aggNavGo(this)")
  window.__aggNavGo = function (pillOrId) {
    try {
      if (pillOrId && pillOrId.getAttribute) {
        goToColumn(pillOrId.getAttribute("data-column-id"));
      } else {
        goToColumn(pillOrId);
      }
    } catch (_e) {}
  };

  // reforço: delegação no document (caso o inline não exista por algum motivo)
  if (!window.__aggNavDelegated) {
    window.__aggNavDelegated = true;
    document.addEventListener("click", function (e) {
      var pill = e.target && e.target.closest && e.target.closest(".aggregator-card[data-column-id]");
      if (pill) window.__aggNavGo(pill);
    });
  }
})();
