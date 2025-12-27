// Menu lateral (drawer) - padrão NossoTrello
document.addEventListener("DOMContentLoaded", () => {
  const drawer = document.getElementById("app-drawer");
  const overlay = document.getElementById("drawerOverlay");
  const toggleBtn = document.getElementById("menuToggle");
  const closeBtn = document.getElementById("drawerClose");
  const accordions = document.querySelectorAll(".nt-accordion");

  if (!drawer || !overlay || !toggleBtn || !closeBtn) return;

  function openDrawer() {
    drawer.hidden = false;
    overlay.hidden = false;
    drawer.setAttribute("data-open", "true");
    overlay.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closeDrawer() {
    drawer.setAttribute("data-open", "false");
    overlay.setAttribute("aria-hidden", "true");

    setTimeout(() => {
      drawer.hidden = true;
      overlay.hidden = true;
      document.body.style.overflow = "";
    }, 320);
  }

  toggleBtn.addEventListener("click", (e) => {
    e.preventDefault();
    if (drawer.getAttribute("data-open") === "true") closeDrawer();
    else openDrawer();
  });

  closeBtn.addEventListener("click", (e) => {
    e.preventDefault();
    closeDrawer();
  });

  overlay.addEventListener("click", () => closeDrawer());

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
  });

  // fecha ao clicar em links do menu (não fecha em botões/accordions)
  drawer.addEventListener("click", (e) => {
    const a = e.target.closest("a.nt-link, a.nt-sublink");
    if (a) closeDrawer();
  });

  accordions.forEach((btn) => {
    btn.addEventListener("click", () => {
      const expanded = btn.getAttribute("aria-expanded") === "true";
      const targetId = btn.getAttribute("aria-controls");
      const target = targetId ? document.getElementById(targetId) : null;
      if (!target) return;

      btn.setAttribute("aria-expanded", String(!expanded));
      target.classList.toggle("open", !expanded);
    });
  });
});
