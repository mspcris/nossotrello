// Global client-side hooks used across pages.
// Keep it dependency-light; HTMX events are optional.

(() => {
  if (window.__baseJsInit === true) return;
  window.__baseJsInit = true;

  function setHeaderAvatar(url) {
    // base.html uses header-user-avatar-img / header-user-avatar-fallback.
    const img = document.getElementById("header-user-avatar-img") || document.getElementById("user-avatar");
    const fallback = document.getElementById("header-user-avatar-fallback") || document.getElementById("user-avatar-fallback");

    if (url && img) {
      img.src = url;
      img.classList.remove("hidden");
      if (fallback) fallback.classList.add("hidden");
      return;
    }

    if (img) img.classList.add("hidden");
    if (fallback) fallback.classList.remove("hidden");
  }

  function setBoardMemberAvatar(url) {
    // Updates the current user's avatar bubbles inside the board members bar, without reload.
    const me = Number(window.CURRENT_USER_ID || 0);
    if (!me || !url) return;

    document.querySelectorAll(`[data-user-id="${me}"]`).forEach((btn) => {
      // Swap existing img if present, otherwise replace fallback span with an img.
      const img = btn.querySelector("img");
      const fallback = btn.querySelector(".avatar-fallback");

      if (img) {
        img.src = url;
      } else {
        if (fallback) fallback.remove();
        const nimg = document.createElement("img");
        nimg.src = url;
        nimg.alt = btn.getAttribute("aria-label") || "Avatar";
        nimg.loading = "lazy";
        btn.appendChild(nimg);
      }

      // keep dataset for readonly modal
      btn.dataset.avatarUrl = url;
    });
  }

  // HTMX: server can reply with HX-Trigger: {"userAvatarUpdated": {"url": "..."}}
  document.body.addEventListener("userAvatarUpdated", (e) => {
    const url = e?.detail?.url || "";
    setHeaderAvatar(url);
    setBoardMemberAvatar(url);
  });
})();
