// boards/static/boards/modal/modal.tags.js
(() => {
  if (!window.Modal || window.Modal.tags) return;

  // Auditoria: ative com:
  // localStorage.setItem("DEBUG_TAGS","1"); location.reload();
  // ou abra a URL com ?debug_tags=1
  const DEBUG =
    localStorage.getItem("DEBUG_TAGS") === "1" ||
    new URLSearchParams(location.search).get("debug_tags") === "1";

  const log = (...a) => DEBUG && console.log("[modal.tags]", ...a);
  const warn = (...a) => DEBUG && console.warn("[modal.tags]", ...a);

  function getCSRFToken() {
    return (
      document.querySelector("meta[name='csrf-token']")?.content ||
      document.querySelector('input[name="csrfmiddlewaretoken"]')?.value ||
      ""
    );
  }

  function safeJsonParse(s, fallback) {
    try {
      return JSON.parse(s);
    } catch (_e) {
      return fallback;
    }
  }

  function getModalRootFallback() {
    const modalBody = document.getElementById("modal-body");
    if (modalBody) {
      const inModal = modalBody.querySelector("#cm-root");
      if (inModal) return inModal;
    }
    const all = document.querySelectorAll("#cm-root");
    return all && all.length ? all[all.length - 1] : null;
  }

  function getRootFrom(el) {
    return el?.closest?.("#cm-root") || getModalRootFallback();
  }

  function getColorForTag(root, btn, tag) {
    const raw = root?.getAttribute?.("data-tag-colors") || "{}";
    const colors = safeJsonParse(raw, {});
    return (
      (colors && colors[tag]) ||
      (btn?.dataset?.fallbackColor || "").trim() ||
      "#999999"
    );
  }

  function setRootColor(root, tag, color) {
    if (!root) return;
    const rawColors = root.getAttribute("data-tag-colors") || "{}";
    const colors = safeJsonParse(rawColors, {});
    colors[tag] = color;
    root.setAttribute("data-tag-colors", JSON.stringify(colors));
  }

  function positionPopover(popover, _root, anchorEl) {
    if (!popover || !anchorEl) return;

    // usa viewport: não sofre com overflow hidden nem stacking context do cm-root
    const a = anchorEl.getBoundingClientRect();
    const left = Math.max(12, a.left);
    const top = Math.max(12, a.bottom + 8);

    popover.style.position = "fixed";
    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
    popover.style.zIndex = "99999";
  }


  function getPopoverEl(root) {
    // popover fica dentro do cm-root
    return root?.querySelector?.("#cm-tag-color-popover") || document.getElementById("cm-tag-color-popover");
  }

  function closePopover() {
    const pop = document.getElementById("cm-tag-color-popover");
    if (!pop) return;
    pop.classList.add("hidden");
  }

  function openPopoverForButton(btn) {
    const root = getRootFrom(btn);
    if (!root) {
      warn("openPopoverForButton: sem #cm-root para o botão", btn);
      return false;
    }

    const pop = getPopoverEl(root);
    const pick = root.querySelector("#cm-tag-color-picker");
    const tInp = root.querySelector("#cm-tag-color-tag");
    const cInp = root.querySelector("#cm-tag-color-value");

    if (!pop || !pick || !tInp || !cInp) {
      warn("openPopoverForButton: faltando elementos", {
        pop: !!pop,
        pick: !!pick,
        tInp: !!tInp,
        cInp: !!cInp,
      });
      return false;
    }

    const tag = (btn.dataset.tag || "").trim();
    if (!tag) {
      warn("openPopoverForButton: botão sem data-tag", btn);
      return false;
    }

    const color = getColorForTag(root, btn, tag);

    tInp.value = tag;
    pick.value = color;
    cInp.value = color;

    // CRÍTICO: posiciona relativo ao #cm-root (não ao modal) para não clipar no overflow:hidden
    // Teleporta o popover para fora do cm-root para não ser clipado por overflow/stacking context
    const modalContainer =
      document.getElementById("card-modal-root") ||
      document.getElementById("modal") ||
      document.body;

    if (modalContainer && pop.parentElement !== modalContainer) {
      modalContainer.appendChild(pop);
    }

    positionPopover(pop, root, btn);
    pop.classList.remove("hidden");


    log("popover aberto", { tag, color });
    return true;
  }

  // ============================================================
  // Delegation global (não depende de HTMX, não duplica)
  // ============================================================
  if (!window.__cmTagsDelegatedClickBound) {
    window.__cmTagsDelegatedClickBound = true;

    document.addEventListener(
      "click",
      function (e) {
        // Só considera cliques na área de tags
        const inTagsArea = e.target?.closest?.("#cm-tags-wrap, #cm-tags-bar");

        // Botão de tag (padrão do seu template card_tags_bar.html)
        const btn =
          e.target?.closest?.("button.cm-tag-btn[data-tag]") ||
          e.target?.closest?.("#cm-tags-bar button[data-tag]");

        // Auditoria quando clica na área mas não casa o seletor
        if (!btn) {
          if (DEBUG && inTagsArea) {
            log("click dentro da área de tags, mas não encontrei botão de tag", e.target);
          }
          return;
        }

        // garante que é dentro do modal
        const modalRoot = document.getElementById("card-modal-root") || document.getElementById("modal");
        if (modalRoot && !modalRoot.contains(btn)) {
          if (DEBUG) log("botão de tag fora do modal (ignorado)", btn);
          return;
        }

        e.preventDefault();
        e.stopPropagation();

        const ok = openPopoverForButton(btn);
        if (DEBUG && !ok) warn("openPopoverForButton retornou false");
      },
      true
    );

    // Auditoria extra (opcional): ajuda a descobrir se o click não está chegando no botão
    if (DEBUG && !window.__cmTagsAuditBound) {
      window.__cmTagsAuditBound = true;

      document.addEventListener(
        "pointerdown",
        function (e) {
          const area = e.target?.closest?.("#cm-tags-wrap, #cm-tags-bar");
          if (!area) return;
          log("pointerdown na área de tags:", e.target);
        },
        true
      );
    }
  }

  if (!window.__cmTagsOutsideClickBound) {
    window.__cmTagsOutsideClickBound = true;

    // Fecha ao clicar fora
    document.addEventListener(
      "click",
      function (e) {
        const pop = document.getElementById("cm-tag-color-popover");
        if (!pop || pop.classList.contains("hidden")) return;

        if (e.target?.closest?.("#cm-tag-color-popover")) return;
        if (e.target?.closest?.("button.cm-tag-btn[data-tag]")) return;
        if (e.target?.closest?.("#cm-tags-bar button[data-tag]")) return;

        closePopover();
      },
      true
    );

    // Fecha com ESC
    document.addEventListener(
      "keydown",
      function (e) {
        if (e.key === "Escape") closePopover();
      },
      true
    );
  }

  // ============================================================
  // Core (picker/save/cancel) — roda a cada swap do modal
  // ============================================================
  window.Modal.tags = {
    __version: "2026-01-18-debuggable",

    init() {
      const root = getModalRootFallback();
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
        if (DEBUG) {
          warn("init(): faltando elementos do core", {
            popover: !!popover,
            picker: !!picker,
            btnCancel: !!btnCancel,
            btnSave: !!btnSave,
            form: !!form,
            inputTag: !!inputTag,
            inputColor: !!inputColor,
          });
        }
        return;
      }

      // evita binds duplicados do núcleo (picker/save/cancel)
      if (root.dataset.cmTagsCoreBound === "1") return;
      root.dataset.cmTagsCoreBound = "1";

      function closeLocal() {
        popover.classList.add("hidden");
      }

      // mantém toggle legado (qualquer [data-tag] que não seja botão de tag)
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
          closeLocal();
        });
      }

      // save
      if (btnSave.dataset.cmBound !== "1") {
        btnSave.dataset.cmBound = "1";

        btnSave.addEventListener("click", async function (e) {
          e.preventDefault();

          const r = getModalRootFallback();
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
              closeLocal();
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

            closeLocal();
          } catch (err) {
            alert(err?.message || "Erro ao salvar cor.");
          }
        });
      }
    },
  };

  log("loaded", window.Modal.tags.__version);
})();
