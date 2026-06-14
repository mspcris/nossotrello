/* Aparência da página (🎨): cor do overlay, transparência e fosco.
   Compartilhado entre home e página de quadro. Persistido em localStorage
   (mesma chave nas duas páginas -> a escolha vale em ambas). */
(function () {
  "use strict";
  var KEY = "cm_home_appearance";
  var DEFAULTS = { color: "#0f172a", alpha: 32, blur: 14, headerTint: false, cards: "light" };

  function hexToRgb(hex) {
    var h = (hex || "").replace("#", "");
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    var n = parseInt(h, 16);
    if (isNaN(n)) return "15, 23, 42";
    return ((n >> 16) & 255) + ", " + ((n >> 8) & 255) + ", " + (n & 255);
  }

  function load() {
    try { return Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(KEY) || "{}")); }
    catch (e) { return Object.assign({}, DEFAULTS); }
  }
  function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }

  function apply(s) {
    var b = document.body;
    b.style.setProperty("--home-tint", hexToRgb(s.color));
    b.style.setProperty("--home-alpha", (s.alpha / 100).toFixed(2));
    b.style.setProperty("--home-blur", s.blur + "px");
    b.classList.toggle("home-header-tinted", !!s.headerTint);
    b.classList.toggle("cards-dark", s.cards === "dark");
  }

  function init() {
    // aplica as cores salvas mesmo sem o popover na página
    var state = load();
    apply(state);

    var toggle = document.getElementById("cm-appearance-toggle");
    var pop = document.getElementById("cm-appearance-pop");
    var color = document.getElementById("ap-color");
    var alpha = document.getElementById("ap-alpha");
    var blur = document.getElementById("ap-blur");
    var alphaVal = document.getElementById("ap-alpha-val");
    var blurVal = document.getElementById("ap-blur-val");
    var reset = document.getElementById("ap-reset");
    var header = document.getElementById("ap-header");
    var cards = document.getElementById("ap-cards");
    if (!toggle || !pop || !color || !alpha || !blur) return;

    function syncInputs() {
      color.value = state.color;
      alpha.value = state.alpha; if (alphaVal) alphaVal.textContent = state.alpha;
      blur.value = state.blur;   if (blurVal) blurVal.textContent = state.blur;
      if (header) header.checked = !!state.headerTint;
      if (cards) cards.value = state.cards || "light";
    }
    syncInputs();

    function onChange() {
      state.color = color.value;
      state.alpha = parseInt(alpha.value, 10);
      state.blur = parseInt(blur.value, 10);
      if (header) state.headerTint = header.checked;
      if (cards) state.cards = cards.value;
      if (alphaVal) alphaVal.textContent = state.alpha;
      if (blurVal) blurVal.textContent = state.blur;
      apply(state); save(state);
    }
    color.addEventListener("input", onChange);
    alpha.addEventListener("input", onChange);
    blur.addEventListener("input", onChange);
    if (header) header.addEventListener("change", onChange);
    if (cards) cards.addEventListener("change", onChange);
    if (reset) reset.addEventListener("click", function () {
      state = Object.assign({}, DEFAULTS); syncInputs(); apply(state); save(state);
    });

    toggle.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var open = pop.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("click", function (ev) {
      if (pop.classList.contains("open") && !pop.contains(ev.target) && ev.target !== toggle) {
        pop.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
