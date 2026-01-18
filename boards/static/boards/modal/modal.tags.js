// boards/static/boards/modal/modal.tags.js
(() => {
  if (!window.Modal || window.Modal.tags) return;

  function getCSRFToken() {
    return document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
  }

  function safeJsonParse(s, fallback) {
    try { return JSON.parse(s); } catch (_e) { return fallback; }
  }

  function getModalRoot() {
    const modalBody = document.getElementById("modal-body");
    if (modalBody) {
      const inModal = modalBody.querySelector("#cm-root");
      if (inModal) return inModal;
    }
    const all = document.querySelectorAll("#cm-root");
    return all && all.length ? all[all.length - 1] : null;
  }

  function positionPopover(popover, root, anchorEl) {
    if (!popover || !root || !anchorEl) return;

    // garante âncora pro absolute
    const cs = window.getComputedStyle(root);
    if (cs.position === "static") root.style.position = "relative";

    const a = anchorEl.getBoundingClientRect();
    const r = root.getBoundingClientRect();

    const left = Math.max(12, a.left - r.left);
    const top = Math.max(12, a.bottom - r.top + 8);

    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  }

  function getColorForTag(root, btn, tag) {
    const raw = root.getAttribute("data-tag-colors") || "{}";
    const colors = safeJsonParse(raw, {});
    return (
      (colors && colors[tag]) ||
      (btn?.dataset?.fallbackColor || "").trim() ||
      "#999999"
    );
  }

  function setRootColor(root, tag, color) {
    const rawColors = root.getAttribute("data-tag-colors") || "{}";
    const colors = safeJsonParse(rawColors, {});
    colors[tag] = color;
    root.setAttribute("data-tag-colors", JSON.stringify(colors));
  }


    // clique em tag: delegação global (resistente a HTMX swap)
  if (!window.__cmTagsDelegatedClickBound) {
    window.__cmTagsDelegatedClickBound = true;

    document.addEventListener(
      "click",
      function (e) {
        const r = getModalRoot();
        if (!r) return;

        const btn = e.target?.closest?.(".cm-tag-btn[data-tag]");
        if (!btn) return;
        if (!r.contains(btn)) return;

        const pop = r.querySelector("#cm-tag-color-popover");
        const pick = r.querySelector("#cm-tag-color-picker");
        const tInp = r.querySelector("#cm-tag-color-tag");
        const cInp = r.querySelector("#cm-tag-color-value");
        if (!pop || !pick || !tInp || !cInp) return;

        e.preventDefault();
        e.stopPropagation();

        const tag = (btn.dataset.tag || "").trim();
        if (!tag) return;

        const color = getColorForTag(r, btn, tag);

        tInp.value = tag;
        pick.value = color;
        cInp.value = color;

        positionPopover(pop, r, btn);
        pop.classList.remove("hidden");
      },
      true
    );
  }

  // fecha ao clicar fora
  if (!window.__cmTagsOutsideClickBound) {
    window.__cmTagsOutsideClickBound = true;

    document.addEventListener(
      "click",
      function (e) {
        const btn = e.target?.closest?.(".cm-tag-btn[data-tag]");
        if (!btn) return;

        const modalBody = document.getElementById("modal-body");
        if (!modalBody || !modalBody.contains(btn)) return;

        const cmRoot = getModalRoot(); // ainda útil p/ ler data-tag-colors
        if (!cmRoot) return;

        const pop = document.getElementById("cm-tag-color-popover");
        const pick = document.getElementById("cm-tag-color-picker");
        const tInp = document.getElementById("cm-tag-color-tag");
        const cInp = document.getElementById("cm-tag-color-value");
        if (!pop || !pick || !tInp || !cInp) return;

        e.preventDefault();
        e.stopPropagation();

        const tag = (btn.dataset.tag || "").trim();
        if (!tag) return;

        const color = getColorForTag(cmRoot, btn, tag);

        tInp.value = tag;
        pick.value = color;
        cInp.value = color;

        // posiciona relativo ao container do popover (offsetParent)
        const anchor = btn.getBoundingClientRect();
        const parent = (pop.offsetParent || modalBody).getBoundingClientRect();

        const left = Math.max(12, anchor.left - parent.left);
        const top = Math.max(12, anchor.bottom - parent.top + 8);

        pop.style.left = `${left}px`;
        pop.style.top = `${top}px`;

        pop.classList.remove("hidden");
      },
      true
    );

  

  
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

      if (!popover || !picker || !btnCancel || !btnSave || !form || !inputTag || !inputColor) return;

      // evita binds duplicados do núcleo (picker/save/cancel)
      if (root.dataset.cmTagsCoreBound === "1") return;
      root.dataset.cmTagsCoreBound = "1";

      function closePopover() {
        popover.classList.add("hidden");
      }

      // clique em tag: delegação global (resistente a HTMX swap)
      if (!window.__cmTagsDelegatedClickBound) {
        window.__cmTagsDelegatedClickBound = true;

        document.addEventListener(
          "click",
          function (e) {
            const r = getModalRoot();
            if (!r) return;

            const btn = e.target?.closest?.(".cm-tag-btn[data-tag]");
            if (!btn) return;
            if (!r.contains(btn)) return;

            const pop = r.querySelector("#cm-tag-color-popover");
            const pick = r.querySelector("#cm-tag-color-picker");
            const tInp = r.querySelector("#cm-tag-color-tag");
            const cInp = r.querySelector("#cm-tag-color-value");
            if (!pop || !pick || !tInp || !cInp) return;

            e.preventDefault();
            e.stopPropagation();

            const tag = (btn.dataset.tag || "").trim();
            if (!tag) return;

            const color = getColorForTag(r, btn, tag);

            tInp.value = tag;
            pick.value = color;
            cInp.value = color;

            positionPopover(pop, r, btn);
            pop.classList.remove("hidden");
          },
          true
        );
      }

      // fecha ao clicar fora
      if (!window.__cmTagsOutsideClickBound) {
        window.__cmTagsOutsideClickBound = true;

        document.addEventListener(
          "click",
          function (e) {
            const pop = document.getElementById("cm-tag-color-popover");
            if (!pop || pop.classList.contains("hidden")) return;

            if (!pop || pop.classList.contains("hidden")) return;

            if (e.target?.closest?.("#cm-tag-color-popover") || e.target?.closest?.(".cm-tag-btn")) return;

            pop.classList.add("hidden");
          },
          true
        );
      }

      // mantém toggle legado (qualquer [data-tag] que não seja a tag do topo)
      root.querySelectorAll("[data-tag]:not(.cm-tag-btn)").forEach((el) => {
        if (el.dataset.cmLegacyBound === "1") return;
        el.dataset.cmLegacyBound = "1";
        el.addEventListener("click", function () {
          el.classList.toggle("active");
        });
      });

      // picker sync
      if (picker.dataset.cmBound !== "1") {
        picker.dataset.cmBound = "1";
        picker.addEventListener("input", function () {
          inputColor.value = (picker.value || "").trim();
        });
      }

      // cancel
      if (btnCancel.dataset.cmBound !== "1") {
        btnCancel.dataset.cmBound = "1";
        btnCancel.addEventListener("click", function (e) {
          e.preventDefault();
          closePopover();
        });
      }

      // save
      if (btnSave.dataset.cmBound !== "1") {
        btnSave.dataset.cmBound = "1";

        btnSave.addEventListener("click", async function (e) {
          e.preventDefault();

          const r = getModalRoot();
          if (!r) return;

          const tag = (inputTag.value || "").trim();
          const color = (inputColor.value || "").trim();
          if (!tag || !color) return;

          const endpoint = form.getAttribute("action") || "";
          if (!endpoint) return;

          try {
            const csrf = getCSRFToken();
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

            const data = safeJsonParse(respText || "{}", {});
            if (!data || typeof data.tags_bar !== "string") {
              alert(`JSON sem "tags_bar"\n${respText.slice(0, 400)}`);
              return;
            }

            // atualiza barra no modal
            if (tagsWrap) tagsWrap.innerHTML = data.tags_bar;

            // atualiza snippet do card na board (se vier)
            if (typeof data.snippet === "string" && data.card_id) {
              const cardEl = document.getElementById(`card-${data.card_id}`);
              if (cardEl) {
                const tmp = document.createElement("div");
                tmp.innerHTML = data.snippet.trim();
                const freshLi = tmp.firstElementChild;
                if (freshLi) cardEl.replaceWith(freshLi);
              }

              if (typeof window.applySavedTermColorsToBoard === "function") {
                const columnsList = document.getElementById("columns-list");
                window.applySavedTermColorsToBoard(columnsList || document);
              }
              if (typeof window.applySavedTagColorsToBoard === "function") {
                const columnsList = document.getElementById("columns-list");
                window.applySavedTagColorsToBoard(columnsList || document);
              }
            }

            // atualiza estado local
            setRootColor(r, tag, color);
            closePopover();
          } catch (err) {
            alert(err?.message || "Erro ao salvar cor.");
          }
        });
      }
    },
  };
})();
// END boards/static/boards/modal/modal.tags.js
