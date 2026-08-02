/* Pull-to-refresh do quadro, no celular.

   Por que precisa existir: ninguém desligou o gesto nativo do Chrome. O quadro é
   uma tela de altura fixa — cada coluna é capada em calc(100vh-180px) e todo
   scroll vertical acontece DENTRO de um container aninhado (#columns-wrapper e as
   listas [id^="cards-col-"]). O documento nunca cresce, então o dedo nunca chega
   a rolar a página: o gesto fica preso no scroller interno ("scroll latching") e
   o pull-to-refresh nativo não dispara. Este arquivo devolve o gesto. */
(function () {
  if (window.__ntPullRefreshInstalled) return;
  window.__ntPullRefreshInstalled = true;

  var wrap = document.getElementById("columns-wrapper");
  if (!wrap) return;

  // Só onde o gesto faz sentido: dedo + tela de celular. No desktop existe F5.
  if (!window.matchMedia) return;
  if (!window.matchMedia("(pointer: coarse)").matches) return;
  if (!window.matchMedia("(max-width: 767px)").matches) return;

  var TRIGGER = 60;   // quanto o indicador precisa descer pra armar
  var CEIL = 96;      // teto do quanto ele desce
  var DAMP = 0.55;    // resistência: o dedo anda ~110px pra chegar no TRIGGER
  var SLOP = 8;       // antes disso não decidimos a direção do gesto

  var startY = 0;
  var startX = 0;
  var tracking = false;
  var armed = false;
  var firing = false;
  var dist = 0;

  var ind = document.createElement("div");
  ind.className = "nt-ptr";
  ind.innerHTML = '<div class="nt-ptr-circle"><span class="nt-ptr-arrow">↓</span></div>';
  document.body.appendChild(ind);

  function setPull(px, ready) {
    ind.style.transform = "translate(-50%, " + px + "px)";
    ind.style.opacity = px > 6 ? "1" : "0";
    ind.classList.toggle("is-ready", !!ready);
  }

  function reset() {
    tracking = false;
    armed = false;
    dist = 0;
    ind.style.transition = "transform .18s ease, opacity .18s ease";
    setPull(0, false);
    setTimeout(function () { ind.style.transition = ""; }, 200);
  }

  /* O gesto só é nosso se TODO scroller entre o dedo e o topo estiver no começo.
     Senão ele pertence à lista de cards, que tem que rolar primeiro — puxar no
     meio de uma coluna com 19 cards não pode recarregar a página. */
  function scrollersAtTop(el) {
    while (el && el !== document.body && el !== document.documentElement) {
      if (el.scrollHeight - el.clientHeight > 1) {
        var oy = getComputedStyle(el).overflowY;
        if ((oy === "auto" || oy === "scroll") && el.scrollTop > 0) return false;
      }
      el = el.parentElement;
    }
    return true;
  }

  function blocked() {
    if (firing) return true;
    if (window.__isDraggingCard) return true;
    var m = document.getElementById("modal");
    if (m && m.classList.contains("modal-open")) return true;
    return false;
  }

  wrap.addEventListener("touchstart", function (e) {
    if (blocked()) return;
    if (e.touches.length !== 1) return;
    if (!scrollersAtTop(e.target)) return;

    startY = e.touches[0].clientY;
    startX = e.touches[0].clientX;
    tracking = true;
    armed = false;
    dist = 0;
  }, { passive: true });

  wrap.addEventListener("touchmove", function (e) {
    if (!tracking || blocked()) return;
    if (e.touches.length !== 1) { reset(); return; }

    var dy = e.touches[0].clientY - startY;
    var dx = e.touches[0].clientX - startX;

    if (!armed) {
      // Pan horizontal entre colunas continua sendo dele, não nosso.
      if (Math.abs(dx) > Math.abs(dy)) { tracking = false; return; }
      if (dy < SLOP) return;
      armed = true;
    }

    if (dy <= 0) { reset(); return; }

    dist = Math.min(CEIL, dy * DAMP);
    setPull(dist, dist >= TRIGGER);

    e.preventDefault();
  }, { passive: false });

  wrap.addEventListener("touchend", function () {
    if (!tracking) return;

    if (armed && dist >= TRIGGER && !blocked()) {
      firing = true;
      ind.classList.add("nt-ptr-anim");
      setPull(TRIGGER, true);
      if (typeof window.ntBusy === "function") window.ntBusy(true, "Atualizando o quadro…");
      location.reload();
      return;
    }

    reset();
  }, { passive: true });

  wrap.addEventListener("touchcancel", function () { reset(); }, { passive: true });
})();
