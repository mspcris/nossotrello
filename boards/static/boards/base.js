// Global client-side hooks used across pages.
// Keep it dependency-light; HTMX events are optional.

(() => {
  if (window.__baseJsInit === true) return;
  window.__baseJsInit = true;

  function setHeaderAvatar(url) {
    const img = document.getElementById("user-avatar");
    const fallback = document.getElementById("user-avatar-fallback");

    if (url && img) {
      img.src = url;
      img.classList.remove("hidden");
      if (fallback) fallback.classList.add("hidden");
      return;
    }

    if (img) img.classList.add("hidden");
    if (fallback) fallback.classList.remove("hidden");
  }

  // HTMX: server can reply with HX-Trigger: {"userAvatarUpdated": {"url": "..."}}
  document.body.addEventListener("userAvatarUpdated", (e) => {
    const url = e?.detail?.url || "";
    setHeaderAvatar(url);
  });
})();
