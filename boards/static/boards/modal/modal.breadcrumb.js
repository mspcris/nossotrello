// modal.breadcrumb.js
(() => {
  if (!window.Modal || window.Modal.breadcrumb) return;

  function qs(sel) {
    return document.querySelector(sel);
  }

  window.Modal.breadcrumb = {
    render() {
      const host = qs("#modal-breadcrumb");
      if (!host) return;

      const root     = qs("#cm-root");
      const board    = root?.dataset.board        || "";
      const column   = root?.dataset.column       || "";
      const position = root?.dataset.cardPosition || "";
      const title    = (root?.dataset.cardTitle   || "").trim();

      const path = [
        board,
        column,
        position ? `#${position}` : "",
      ].filter(Boolean);
      const full = [...path, title].filter(Boolean).join("  ›  ");

      // Duas partes: sem espaço, o caminho (quadro › coluna › #n) some em "…"
      // antes do título do card. O caminho inteiro fica na dica.
      host.textContent = "";
      host.title = full;
      if (path.length && title) {
        const pathEl = document.createElement("span");
        pathEl.className = "cm-crumb-path";
        pathEl.textContent = path.join("  ›  ") + "  ›";
        const titleEl = document.createElement("span");
        titleEl.className = "cm-crumb-title";
        titleEl.textContent = title;
        host.append(pathEl, titleEl);
      } else {
        host.textContent = full;
      }

      window.ntFitShellTabs?.();
    },

    bind() {
      // dados vêm dos data-attributes do #cm-root, não precisam de listener
    },
  };
})();
