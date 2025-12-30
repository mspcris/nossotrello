// boards/static/boards/modal/modal.tags.js
(() => {
  if (!window.Modal || window.Modal.tags) return;

  function getCSRFToken() {
    return (
      document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || ""
    );
  }

  function safeJsonParse(s, fallback) {
    try {
      return JSON.parse(s);
    } catch (_e) {
      return fallback;
    }
  }

  function setBtnColor(btn, color) {
    if (!btn || !color) return;
    btn.style.backgroundColor = `${color}20`;
    btn.style.color = color;
    btn.style.borderColor = color;
    btn.dataset.fallbackColor = color;
  }

  function positionPopover(popover, root, anchorEl) {
    if (!popover || !root || !anchorEl) return;

    // popover é absolute; root já está no DOM do modal
    const a = anchorEl.getBoundingClientRect();
    const r = root.getBoundingClientRect();

    const left = Math.max(12, a.left - r.left);
    const top = Math.max(12, a.bottom - r.top + 8);

    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  }

  window.Modal.tags = {
    init() {
      const root = document.getElementById("cm-root");
      if (!root) return;

      const tagsWrap = document.getElementById("cm-tags-wrap");
      const popover = document.getElementById("cm-tag-color-popover");
      const picker = document.getElementById("cm-tag-color-picker");
      const btnCancel = document.getElementById("cm-tag-color-cancel");
      const btnSave = document.getElementById("cm-tag-color-save");

      const form = document.getElementById("cm-tag-color-form");
      const inputTag = document.getElementById("cm-tag-color-tag");
      const inputColor = document.getElementById("cm-tag-color-value");

      if (!popover || !picker || !btnCancel || !btnSave || !form || !inputTag || !inputColor) {
        // modal pode estar em estado antigo (sem picker); nesse caso, não faz nada
        return;
      }

      // evita bind duplicado a cada swap/reopen
      if (root.dataset.cmTagsBound === "1") return;
      root.dataset.cmTagsBound = "1";

      let currentBtn = null;

      function openPopoverFor(btn) {
        currentBtn = btn;

        const tag = (btn?.dataset?.tag || "").trim();
        if (!tag) return;

        // cor atual: tenta data-tag-colors do root; fallback no data-fallback-color do botão
        const raw = root.getAttribute("data-tag-colors") || "{}";
        const colors = safeJsonParse(raw, {});
        const currentColor =
          (colors && colors[tag]) ||
          (btn.dataset.fallbackColor || "").trim() ||
          "#999999";

        inputTag.value = tag;
        picker.value = currentColor;
        inputColor.value = currentColor;

        positionPopover(popover, root, btn);
        popover.classList.remove("hidden");
      }

      function closePopover() {
        popover.classList.add("hidden");
        currentBtn = null;
      }

      // atualiza hidden enquanto escolhe no color input
      picker.addEventListener("input", function () {
        inputColor.value = (picker.value || "").trim();
      });

      btnCancel.addEventListener("click", function (e) {
        e.preventDefault();
        closePopover();
      });

      // fecha popover clicando fora
      document.addEventListener(
        "click",
        function (e) {
          if (popover.classList.contains("hidden")) return;
          if (e.target && (e.target.closest("#cm-tag-color-popover") || e.target.closest(".cm-tag-btn"))) return;
          closePopover();
        },
        true
      );

      // binds: tags do topo (.cm-tag-btn)
      root.querySelectorAll(".cm-tag-btn[data-tag]").forEach((btn) => {
        if (btn.dataset.cmBound === "1") return;
        btn.dataset.cmBound = "1";

        btn.addEventListener("click", function (e) {
          e.preventDefault();
          e.stopPropagation();
          openPopoverFor(btn);
        });
      });

      // mantém comportamento “legado” (toggle) só para outros [data-tag] que NÃO sejam do topo
      root.querySelectorAll("[data-tag]:not(.cm-tag-btn)").forEach((el) => {
        if (el.dataset.cmLegacyBound === "1") return;
        el.dataset.cmLegacyBound = "1";

        el.addEventListener("click", function () {
          el.classList.toggle("active");
        });
      });

      btnSave.addEventListener("click", async function (e) {
        e.preventDefault();

        const tag = (inputTag.value || "").trim();
        const color = (inputColor.value || "").trim();
        if (!tag || !color) return;

        try {
          const csrf = getCSRFToken();
          const endpoint = form.getAttribute("action") || "";
          if (!endpoint) return;

          const body = new URLSearchParams();
          body.set("tag", tag);
          body.set("color", color);

          const res = await fetch(endpoint, {
            method: "POST",
            headers: {
              "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
              "X-CSRFToken": csrf,
              "X-Requested-With": "XMLHttpRequest",
            },
            body: body.toString(),
            credentials: "same-origin",
          });

          // VIEWER: backend retorna 403 com JSON “Somente leitura.”
          if (res.status === 403) {
            const data403 = await res.json().catch(() => ({}));
            closePopover();
            // sem inventar UI nova: feedback mínimo
            alert(data403?.error || "Somente leitura.");
            return;
          }

          if (!res.ok) {
            const txt = await res.text().catch(() => "");
            throw new Error(txt || "Falha ao salvar cor.");
          }

          const data = await res.json().catch(() => ({}));
          if (!data || data.ok !== true) throw new Error("Resposta inválida.");

          // 1) atualiza barra (sem mexer no resto do modal)
          if (tagsWrap && typeof data.tags_bar === "string") {
            tagsWrap.innerHTML = data.tags_bar;

            // rebind nos novos botões
            root.dataset.cmTagsBound = "0";
            window.Modal.tags.init();
          }

          // 2) atualiza data-tag-colors local (pra abrir popover com cor certa)
          const raw = root.getAttribute("data-tag-colors") || "{}";
          const colors = safeJsonParse(raw, {});
          colors[tag] = color;
          root.setAttribute("data-tag-colors", JSON.stringify(colors));

          // 3) se o botão ainda existe, aplica cor imediatamente (melhor UX)
          if (currentBtn) setBtnColor(currentBtn, color);

          closePopover();
        } catch (err) {
          alert(err?.message || "Erro ao salvar cor.");
        }
      });
    },
  };
})();
// END boards/static/boards/modal/modal.tags.js
