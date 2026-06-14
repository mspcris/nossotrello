/* autocontrast.js
   Utilitário de contraste automático: dada uma cor de fundo, devolve a cor de
   texto legível (preto ou branco) pela luminância (WCAG). Reutilizado pela
   coluna de totais, capa de card por cor, etc. */
(function () {
  "use strict";

  function _toRgb(hex) {
    var h = String(hex || "").trim().replace("#", "");
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    var n = parseInt(h, 16);
    if (isNaN(n)) return null;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  // Luminância relativa (WCAG). Retorna '#111827' (escuro) ou '#ffffff' (claro).
  window.cmTextColorFor = function (hexOrRgb) {
    var rgb = Array.isArray(hexOrRgb) ? hexOrRgb : _toRgb(hexOrRgb);
    if (!rgb) return "#111827";
    var lin = rgb.map(function (v) {
      v = v / 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    var L = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
    // limiar ~0.45: fundo claro -> texto escuro; fundo escuro -> texto branco
    return L > 0.45 ? "#111827" : "#ffffff";
  };

  // Aplica em qualquer elemento com data-auto-bg="<cor>": define a cor do texto.
  window.cmApplyAutoContrast = function (root) {
    (root || document).querySelectorAll("[data-auto-bg]").forEach(function (el) {
      var bg = el.getAttribute("data-auto-bg");
      if (bg) el.style.color = window.cmTextColorFor(bg);
    });
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { window.cmApplyAutoContrast(); });
  } else {
    window.cmApplyAutoContrast();
  }
})();
