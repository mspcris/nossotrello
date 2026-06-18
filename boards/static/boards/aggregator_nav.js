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

  // acha o ancestral que REALMENTE rola na horizontal (não assume #columns-wrapper)
  function horizontalScroller(el) {
    var n = el && el.parentElement;
    while (n && n !== document.documentElement) {
      if (n.scrollWidth > n.clientWidth + 4) {
        var ov = getComputedStyle(n).overflowX;
        if (ov === "auto" || ov === "scroll") return n;
      }
      n = n.parentElement;
    }
    return document.getElementById("columns-wrapper") ||
      document.scrollingElement || document.documentElement;
  }

  function goToColumn(colId) {
    if (colId == null) return;
    var col = document.querySelector('#columns-wrapper .column-item[data-column-id="' + colId + '"]') ||
      document.querySelector('.column-item[data-column-id="' + colId + '"]');
    if (!col) return;

    var s = horizontalScroller(col);
    // posição do col relativa ao scroller, via coordenadas reais (robusto a
    // offsetParent / mudanças de layout).
    var cr = col.getBoundingClientRect();
    var sr = s.getBoundingClientRect ? s.getBoundingClientRect() : { left: 0, width: window.innerWidth };
    var target = s.scrollLeft + (cr.left - sr.left) - Math.max(0, (s.clientWidth - cr.width) / 2);
    target = Math.max(0, target);
    // scroll INSTANTÂNEO (foi o que funcionou no teste manual; smooth era suspeito)
    s.scrollLeft = target;
    // tenta suavizar também (se o browser respeitar, melhora; se não, já rolou)
    try { s.scrollTo({ left: target, behavior: "smooth" }); } catch (_e) {}
    setTimeout(function () { flash(col); }, 60);
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

  // captura no WINDOW (fase capture) = roda ANTES de qualquer listener que
  // pare a propagação do clique. Cobre tanto o clique do mouse quanto o
  // disparado por código, mesmo que algo no caminho chame stopPropagation.
  if (!window.__aggNavDelegated) {
    window.__aggNavDelegated = true;
    var handler = function (e) {
      var t = e.target;
      var pill = t && t.closest && t.closest(".aggregator-card[data-column-id]");
      if (pill) window.__aggNavGo(pill);
    };
    window.addEventListener("click", handler, true);
    window.addEventListener("pointerup", handler, true); // reforço (toque/caso click engolido)
  }
})();
