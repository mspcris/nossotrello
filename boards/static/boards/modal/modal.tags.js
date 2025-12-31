// boards/static/boards/modal/modal.tags.js
(() => {
  if (!window.Modal || window.Modal.tags) return;

  function getCSRFToken() {
    return document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
  }

  function safeJsonParse(s, fallback) {
    try {
      return JSON.parse(s);
    } catch (_e) {
      return fallback;
    }
  }

  function positionPopover(popover, root, anchorEl) {
    if (!popover || !root || !anchorEl) return;

    const a = anchorEl.getBoundingClientRect();
    const r = root.getBoundingClientRect();

    const left = Math.max(12, a.left - r.left);
    const top = Math.max(12, a.bottom - r.top + 8);

    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  }

  function getModalRoot() {
    // prioridade: cm-root dentro do modal
    const modalBody = document.getElementById("modal-body");
    if (modalBody) {
      const inModal = modalBody.querySelector("#cm-root");
      if (inModal) return inModal;
    }

    // fallback (não ideal): último cm-root do documento
    const all = document.querySelectorAll("#cm-root");
    if (all && all.length) return all[all.length - 1];

    return null;
  }

  window.Modal.tags = {
    init() {
      const root = getModalRoot();
      if (!root) return;

      const tagsWrap = root.querySelector("#cm-tags-wrap");
      const popover = root.querySelector("#cm-tag-color-popover");
      const picker = root.querySelector("#cm-tag-color-picker");
      const btnCancel = root.querySelector("#cm-tag-color-cancel");
      const btnSave = root.querySelector("#cm-tag-color-save");

      const form = root.querySelector("#cm-tag-color-form");
      const inputTag = root.querySelector("#cm-tag-color-tag");
      const inputColor = root.querySelector("#cm-tag-color-value");

      if (!popover || !picker || !btnCancel || !btnSave || !form || !inputTag || !inputColor) {
        return;
      }

      // evita bind duplicado (por root do modal)
      if (root.dataset.cmTagsBound === "1") return;
      root.dataset.cmTagsBound = "1";

      let currentBtn = null;

      function openPopoverFor(btn) {
        currentBtn = btn;

        const tag = (btn?.dataset?.tag || "").trim();
        if (!tag) return;

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

      picker.addEventListener("input", function () {
        inputColor.value = (picker.value || "").trim();
      });

      btnCancel.addEventListener("click", function (e) {
        e.preventDefault();
        closePopover();
      });

      // listener global só 1 vez (não acumula)
      if (!window.__cmTagsOutsideClickBound) {
        window.__cmTagsOutsideClickBound = true;

        document.addEventListener(
          "click",
          function (e) {
            const r = getModalRoot();
            if (!r) return;

            const pop = r.querySelector("#cm-tag-color-popover");
            if (!pop || pop.classList.contains("hidden")) return;

            if (e.target && (e.target.closest("#cm-tag-color-popover") || e.target.closest(".cm-tag-btn"))) return;

            pop.classList.add("hidden");
          },
          true
        );
      }

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

          if (res.status === 403) {
            const data403 = await res.json().catch(() => ({}));
            closePopover();
            alert(data403?.error || "Somente leitura.");
            return;
          }

          const respText = await res.text().catch(() => "");
          if (!res.ok) {
            alert(`HTTP ${res.status}\n${respText.slice(0, 400)}`);
            return;
          }

          const ctype = (res.headers.get("content-type") || "").toLowerCase();
          if (!ctype.includes("application/json")) {
            alert(`Não veio JSON (${ctype || "sem content-type"})\n${respText.slice(0, 400)}`);
            return;
          }

          let data = {};
          try { data = JSON.parse(respText || "{}"); } catch (_e) {}

          if (!data || typeof data.tags_bar !== "string") {
            alert(`JSON sem "tags_bar"\n${respText.slice(0, 400)}`);
            return;
          }

          // 1) atualiza a barra no modal
          if (tagsWrap) tagsWrap.innerHTML = data.tags_bar;

          // 1.5) atualiza o card na BOARD (se veio snippet)
          if (data && typeof data.snippet === "string" && data.card_id) {
            const cardEl = document.getElementById(`card-${data.card_id}`);
            if (cardEl) {
              // substitui o LI inteiro
              const tmp = document.createElement("div");
              tmp.innerHTML = data.snippet.trim();
              const freshLi = tmp.firstElementChild;
              if (freshLi) cardEl.replaceWith(freshLi);
            }
          
            // re-pinta TERM se existir (pra não perder overlay/cores)
            if (typeof window.applySavedTermColorsToBoard === "function") {
              const columnsList = document.getElementById("columns-list");
              window.applySavedTermColorsToBoard(columnsList || document);
            }
          
            // re-pinta TAGS se você tiver isso no global
            if (typeof window.applySavedTagColorsToBoard === "function") {
              const columnsList = document.getElementById("columns-list");
              window.applySavedTagColorsToBoard(columnsList || document);
            }
          }


          // 2) atualiza estado no root do modal
          const rawColors = root.getAttribute("data-tag-colors") || "{}";
          const colors = safeJsonParse(rawColors, {});
          colors[tag] = color;
          root.setAttribute("data-tag-colors", JSON.stringify(colors));

          // 3) rebind nos botões re-renderizados
          root.dataset.cmTagsBound = "0";
          window.Modal.tags.init();

          closePopover();
        } catch (err) {
          alert(err?.message || "Erro ao salvar cor.");
        }
      });
    },
  };
})();
// END boards/static/boards/modal/modal.tags.js
