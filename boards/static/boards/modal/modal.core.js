// boards/static/boards/modal/modal.core.js
(() => {
  const Modal =
    (window.Modal && typeof window.Modal === "object") ? window.Modal : {};
  window.Modal = Modal;

  // evita duplicidade
  if (Modal.__coreLoaded) return;
  Modal.__coreLoaded = true;

  const DEBUG =
    location.hostname === "localhost" ||
    localStorage.getItem("DEBUG") === "1";

  const log = (...a) => DEBUG && console.log("[modal.core]", ...a);
  const warn = (...a) => DEBUG && console.warn("[modal.core]", ...a);

  const state =
    (Modal.state && typeof Modal.state === "object") ? Modal.state : {};
  Modal.state = state;

  state.isOpen ??= false;
  state.currentCardId ??= null;
  state.lastOpenedAt ??= 0;
  state.lastCardRect ??= null;
  state.lastFocusedEl ??= null;

  // ============================================================
  // Helpers DOM
  // ============================================================
  function getModalEl() {
    return document.getElementById("modal");
  }

  function getRootEl() {
    return document.getElementById("card-modal-root");
  }

  function getBodyEl() {
    return document.getElementById("modal-body");
  }

  function getCmRootEl() {
    return document.getElementById("cm-root");
  }

  function isInsideModal(el) {
    const modal = getModalEl();
    return !!(modal && el && modal.contains(el));
  }

  function tryFocus(el) {
    try {
      if (el && typeof el.focus === "function") {
        el.focus({ preventScroll: true });
        return true;
      }
    } catch {}
    return false;
  }

  function restoreFocusBeforeHide() {
    const active = document.activeElement;
    if (!isInsideModal(active)) return;

    const last = state.lastFocusedEl;
    if (last && document.contains(last) && !isInsideModal(last)) {
      if (tryFocus(last)) return;
    }

    try {
      document.body.tabIndex = document.body.tabIndex || -1;
      tryFocus(document.body);
    } catch {}
  }

  // ============================================================
  // Inert (trava fundo sem travar modal)
  // Regra: nunca aplicar inert em um ancestral do modal.
  // ============================================================
  function getModalTopContainer() {
    const modal = getModalEl();
    if (!modal) return null;

    let node = modal;
    while (node && node.parentElement && node.parentElement !== document.body) {
      node = node.parentElement;
    }
    return node && node.parentElement === document.body ? node : null;
  }

  function applyInert(isOpen) {
    const modal = getModalEl();
    if (!modal) return;

    const boardRoot = document.getElementById("board-root");
    if (boardRoot && !boardRoot.contains(modal)) {
      if (isOpen) boardRoot.setAttribute("inert", "");
      else boardRoot.removeAttribute("inert");
      return;
    }

    const top = getModalTopContainer();
    if (!top) return;

    const kids = Array.from(document.body.children || []);
    for (const k of kids) {
      if (k === top) continue;
      if (isOpen) k.setAttribute("inert", "");
      else k.removeAttribute("inert");
    }
  }

  // ============================================================
  // URL (?card=)
  // ============================================================
  function clearCardFromUrl() {
    try {
      const url = new URL(window.location.href);
      url.searchParams.delete("card");
      history.replaceState(history.state || {}, "", url.toString());
    } catch {}
  }

  // ============================================================
  // CM — Nova Atividade (toggle do composer) — HTMX safe
  // (IDs: #cm-activity-toggle, #cm-activity-composer, #cm-activity-gap)
  // ============================================================
  function initActivityComposerToggle() {
  const composer = document.getElementById("cm-activity-composer");
  if (!composer) return;

  // evita double-bind quando HTMX faz swap
  if (composer.dataset.cmToggleBound === "1") return;
  composer.dataset.cmToggleBound = "1";

  const tabFeed = document.getElementById("cm-activity-tab-feed");
  const tabNew  = document.getElementById("cm-activity-tab-new");
  const btnToggle = document.getElementById("cm-activity-toggle"); // legado (se existir)
  const feedPanel = document.getElementById("cm-activity-feed");   // opcional

  function isOpen() {
    // suportar legado e novo
    if (composer.classList.contains("is-open")) return true;
    if (composer.classList.contains("is-hidden")) return false;
    // fallback: se não tem is-hidden, considera aberto
    return true;
  }

  function setOpen(open) {
    // Novo padrão: is-hidden manda
    composer.classList.toggle("is-hidden", !open);
    // compat com CSS/JS antigo
    composer.classList.toggle("is-open", open);

    // se quiser esconder o feed enquanto edita, mantém coerente
    if (feedPanel) feedPanel.classList.toggle("is-hidden", open);

    if (tabNew) {
      tabNew.classList.toggle("is-active", open);
      tabNew.setAttribute("aria-selected", open ? "true" : "false");
    }
    if (tabFeed) {
      tabFeed.classList.toggle("is-active", !open);
      tabFeed.setAttribute("aria-selected", open ? "false" : "true");
    }

    // garante que o Quill/mention sobe quando abre
    if (open) {
      try { window.ensureActivityQuill?.(); } catch (_e) {}
    }
  }

  // estado inicial (respeita aria-selected se existir)
  const initialOpen =
    (tabNew && tabNew.getAttribute("aria-selected") === "true") ? true :
    (!composer.classList.contains("is-hidden"));

  setOpen(initialOpen);

  // Legado: botão único
  if (btnToggle) {
    btnToggle.addEventListener("click", function (e) {
      e.preventDefault();
      setOpen(!isOpen());
    }, true);
  }

  // Novo: abas
  if (tabNew) {
    tabNew.addEventListener("click", function (e) {
      e.preventDefault();
      setOpen(true);
    }, true);
  }

  if (tabFeed) {
    tabFeed.addEventListener("click", function (e) {
      e.preventDefault();
      setOpen(false);
    }, true);
  }

  // Pós-submit da atividade: volta pro feed (e deixa “Nova Atividade” reabrir sempre)
  if (window.__cmActivityAfterSubmitBound !== true) {
    window.__cmActivityAfterSubmitBound = true;

    document.body.addEventListener("htmx:afterRequest", function (evt) {
      const elt = evt.detail && evt.detail.elt;
      if (!elt || elt.id !== "cm-activity-form") return;
      if (!evt.detail.successful) return;

      // re-query porque HTMX pode ter trocado partes
      const c = document.getElementById("cm-activity-composer");
      if (!c) return;

      c.classList.add("is-hidden");
      c.classList.remove("is-open");

      const tf = document.getElementById("cm-activity-tab-feed");
      const tn = document.getElementById("cm-activity-tab-new");
      const fp = document.getElementById("cm-activity-feed");

      if (fp) fp.classList.remove("is-hidden");
      if (tf) { tf.classList.add("is-active"); tf.setAttribute("aria-selected", "true"); }
      if (tn) { tn.classList.remove("is-active"); tn.setAttribute("aria-selected", "false"); }
    }, true);
  }
}

  // ============================================================
  // Tabs — sempre abrir em "Descrição" (audit + force)
  // ============================================================
    function forceDescriptionTab() {
    const modal = getModalEl();
    const body = getBodyEl();
    const scope = body || modal || document;
    if (!scope) return false;

    const norm = (s) =>
      (s || "")
        .trim()
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "");

    const tabs = Array.from(
      scope.querySelectorAll("[role='tab'], [data-tab], [data-target], a[href], button")
    );

    const descTab = tabs.find((el) => {
      const text = norm(el.textContent);
      const dt = norm(el.getAttribute("data-tab"));
      const dtarget = norm(el.getAttribute("data-target"));
      const aria = norm(el.getAttribute("aria-controls"));
      const href = norm(el.getAttribute("href"));

      return (
        text.includes("descricao") ||
        dt.includes("descricao") || dt.includes("description") ||
        dtarget.includes("descricao") || dtarget.includes("description") ||
        aria.includes("descricao") || aria.includes("description") ||
        href.includes("#descricao") || href.includes("#description")
      );
    });

    if (!descTab) {
      warn("forceDescriptionTab(): não achou aba Descrição");
      return false;
    }

    try {
      descTab.click();
      log("forceDescriptionTab(): clicked", (descTab.textContent || "").trim());
      return true;
    } catch (e) {
      warn("forceDescriptionTab(): click falhou", e);
      return false;
    }
  }


  // ============================================================
  // CM — Init do conteúdo do modal (HTMX safe)
  // - AA (dock + data-font)
  // - Nova Atividade (toggle)
  // ============================================================
  function initCardModalContent() {
    // AA
    //try { Modal.fontSize?.init?.(); } catch {}

    // Nova Atividade
    try { initActivityComposerToggle?.(); } catch {}

    // ✅ CHECKLIST DnD / UX
    try { Modal.checklists?.init?.(); } catch {}

    // Bind HTMX (uma vez) — sem forçar aba aqui (evita quebrar DnD)
    if (!window.__cmModalContentInitBound) {
      window.__cmModalContentInitBound = true;

      document.body.addEventListener("htmx:afterSwap", (evt) => {
        if (evt.target && evt.target.id === "modal-body") {
          initCardModalContent();
        }
      });

      document.body.addEventListener("htmx:afterSettle", (evt) => {
        if (evt.target && evt.target.id === "modal-body") {
          initCardModalContent();
        }
      });
    }
  }


  // ============================================================
  // OPEN
  // ============================================================
  Modal.open = function () {
    const modal = getModalEl();
    const root = getRootEl();

    if (!modal || !root) {
      warn("open(): modal/root não encontrado");
      return false;
    }

    // salva foco anterior
    state.lastFocusedEl = document.activeElement;

    modal.classList.add("modal-open");
    modal.setAttribute("aria-hidden", "false");

    // trava o fundo (sem travar o modal)
    applyInert(true);

    const rect = state.lastCardRect;

    // Genie (se tiver geometria do card)
    if (rect) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      const rw = root.offsetWidth || 1;
      const rh = root.offsetHeight || 1;

      const scaleX = rect.width / rw;
      const scaleY = rect.height / rh;

      const translateX = rect.left + rect.width / 2 - vw / 2;
      const translateY = rect.top + rect.height / 2 - vh / 2;

      root.style.transition = "none";
      root.style.transformOrigin = "center center";
      root.style.transform =
        `translate(${translateX}px, ${translateY}px) scale(${scaleX}, ${scaleY})`;
      root.style.opacity = "0";

      root.getBoundingClientRect();

      requestAnimationFrame(() => {
        root.style.transition =
          "transform 420ms cubic-bezier(0.22, 1, 0.36, 1), opacity 200ms ease";
        root.style.transform = "translate(0,0) scale(1)";
        root.style.opacity = "1";
      });
    }

    // foco dentro do modal
    requestAnimationFrame(() => {
      const closeBtn =
        modal.querySelector("button.modal-top-x, [data-modal-close], #modal-top-x") ||
        modal.querySelector("button, [tabindex]:not([tabindex='-1'])");
      if (closeBtn) tryFocus(closeBtn);
    });

    state.isOpen = true;
    state.lastOpenedAt = Date.now();

    // IMPORTANTE: conteúdo pode entrar via HTMX; roda init "logo depois"
    setTimeout(() => {
      try { initCardModalContent(); } catch {}
    }, 0);

    log("open()");
    return true;
  };

  // ============================================================
  // CLOSE
  // ============================================================
  Modal.close = function ({ clearBody = true, clearUrl = true } = {}) {
    const modal = getModalEl();
    const root = getRootEl();
    const body = getBodyEl();

    const rect = state.lastCardRect;

    state.isOpen = false;
    state.currentCardId = null;

    restoreFocusBeforeHide();

    const finalize = () => {
      modal?.classList.remove("modal-open");
      modal?.setAttribute("aria-hidden", "true");

      applyInert(false);

      if (root) {
        root.style.transition = "";
        root.style.transform = "";
        root.style.opacity = "";
      }

      if (clearBody && body) body.innerHTML = "";
      if (clearUrl) clearCardFromUrl();
      
      //  AA destroy
      //try { Modal.fontSize?.destroy?.(); } catch {}

      document.dispatchEvent(new Event("modal:closed"));
    };

    // Genie close (se tiver geometria)
    if (rect && root && modal) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      const rw = root.offsetWidth || 1;
      const rh = root.offsetHeight || 1;

      const scaleX = rect.width / rw;
      const scaleY = rect.height / rh;

      const translateX = rect.left + rect.width / 2 - vw / 2;
      const translateY = rect.top + rect.height / 2 - vh / 2;

      root.style.transition = "transform 220ms ease, opacity 180ms ease";
      root.style.transform =
        `translate(${translateX}px, ${translateY}px) scale(${scaleX}, ${scaleY})`;
      root.style.opacity = "0";

      setTimeout(finalize, 240);
    } else {
      finalize();
    }

    log("close()");
    return true;
  };

  // ============================================================
  // CM — Font size selector (sm/md/lg) + localStorage
  // - CSS alvo: #cm-root[data-font="sm|md|lg"]
  // ============================================================
  // (() => {
  //   const KEY = "cm_modal_font_size"; // "sm" | "md" | "lg"
  //   const DEFAULT = "sm";

  //   function currentFont() {
  //     try {
  //       return localStorage.getItem(KEY) || DEFAULT;
  //     } catch {
  //       return DEFAULT;
  //     }
  //   }

  //   function applyFont(size) {
  //     // FONTE ÚNICA DE VERDADE: #cm-root (é onde seu CSS está)
  //     const cmRoot = getCmRootEl();
  //     if (cmRoot) cmRoot.setAttribute("data-font", size);

  //     // fallback (não atrapalha)
  //     const modalRoot = getRootEl();
  //     const modal = getModalEl();
  //     if (modalRoot) modalRoot.setAttribute("data-font", size);
  //     if (modal) modal.setAttribute("data-font", size);

  //     try { localStorage.setItem(KEY, size); } catch {}
  //   }

  //   function ensureDock() {
  //     // dock já existe?
  //     if (document.getElementById("cm-fontsize-dock")) return;

  //     const dock = document.createElement("div");
  //     dock.id = "cm-fontsize-dock";
  //     dock.innerHTML = `
  //       <div class="dock-wrap">
  //         <button class="dock-toggle" type="button" aria-label="Tamanho da fonte">AA</button>
  //         <div class="dock-actions">
  //           <button class="dock-action" type="button" data-size="sm">A</button>
  //           <button class="dock-action" type="button" data-size="md">AA</button>
  //           <button class="dock-action" type="button" data-size="lg">AAA</button>
  //         </div>
  //       </div>
  //     `;

  //     // DOCK DENTRO DO CM ROOT (pra CSS/posicionamento bater)
  //     const host = getCmRootEl() || getModalEl() || document.body;
  //     host.appendChild(dock);

  //     const toggle = dock.querySelector(".dock-toggle");
  //     toggle?.addEventListener("click", () => dock.classList.toggle("is-open"));

  //     dock.querySelectorAll(".dock-action").forEach((btn) => {
  //       btn.addEventListener("click", () => {
  //         applyFont(btn.getAttribute("data-size") || DEFAULT);
  //         dock.classList.remove("is-open");
  //       });
  //     });
  //   }

  //   function destroyDock() {
  //     const dock = document.getElementById("cm-fontsize-dock");
  //     if (dock) dock.remove();
  //   }

  //   Modal.fontSize = {
  //     init() {
  //       ensureDock();
  //       applyFont(currentFont());
  //     },
  //     destroy() {
  //       destroyDock();
  //     },
  //     apply(size) {
  //       applyFont(size || DEFAULT);
  //     },
  //     get() {
  //       return currentFont();
  //     }
  //   };
  // })();

  // expõe (opcional)
  Modal.getElements = () => ({
    modal: getModalEl(),
    body: getBodyEl(),
    root: getRootEl(),
    cmRoot: getCmRootEl(),
  });
})();
// end boards/static/boards/modal/modal.core.js
