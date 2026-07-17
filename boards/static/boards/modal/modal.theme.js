// modal.theme.js
(() => {
  if (!window.Modal || window.Modal.theme) return;

  // A classe inicial vem server-side (base.html lê profile.card_modal_theme),
  // então aqui só tratamos a troca — nada de ler estado no boot.
  const MODES = ["glass", "dark"];

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
  }

  function persist(mode) {
    const url = window.CM_THEME_SAVE_URL;
    if (!url) return;

    const csrftoken = getCookie("csrftoken");
    const body = new FormData();
    body.append("card_modal_theme", mode);

    // Best-effort: a classe já foi aplicada; se o POST falhar o usuário só
    // perde a preferência no próximo reload, não a troca atual.
    fetch(url, {
      method: "POST",
      headers: csrftoken ? { "X-CSRFToken": csrftoken } : {},
      body,
      credentials: "same-origin",
    }).catch(() => {});
  }

  window.Modal.theme = {
    set(mode) {
      if (!MODES.includes(mode)) return;

      // resolve na hora: o root existe desde o boot, mas não custa reconsultar
      const root = document.getElementById("card-modal-root");
      if (!root) return;

      root.classList.remove("theme-dark", "theme-glass");
      root.classList.add(`theme-${mode}`);

      persist(mode);
    },
  };

  // alias de compatibilidade
  window.setModalTheme = (m) => window.Modal.theme.set(m);
})();
