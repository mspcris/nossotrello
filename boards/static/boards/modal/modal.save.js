// modal.save.js — Orquestra o "Salvar" do CM modal
// - Dirty tracking do #cm-main-form
// - Botão #cm-save-btn dispara submit do form
// - Integra com HTMX (beforeRequest/afterRequest) para UX de "Salvando..."

(function () {
  const STATE_KEY = "__cmSaveBound";

  function getRoot() {
    return document.getElementById("cm-root");
  }

  function getForm(root) {
    return root?.querySelector("#cm-main-form") || null;
  }

  function getSaveBtn(root) {
    return root?.querySelector("#cm-save-btn") || null;
  }

  function setDirty(root, isDirty) {
    if (!root) return;
    root.dataset.cmDirty = isDirty ? "1" : "0";

    const btn = getSaveBtn(root);
    if (btn) btn.classList.toggle("is-dirty", !!isDirty);
  }

  function isDirty(root) {
    return (root?.dataset?.cmDirty || "0") === "1";
  }

  function bind(root) {
    if (!root) return;
    if (root.dataset[STATE_KEY] === "1") return;
    root.dataset[STATE_KEY] = "1";

    const form = getForm(root);
    const btn = getSaveBtn(root);
    if (!form || !btn) return;

    // Dirty tracking (inputs do form)
    form.addEventListener("input", function (e) {
      const t = e.target;
      if (!t) return;
      setDirty(root, true);
    });

    form.addEventListener("change", function () {
      setDirty(root, true);
    });

    // Permite que outros módulos forcem dirty (ex.: Quill)
    root.addEventListener("cm:dirty", function () {
      setDirty(root, true);
    });

    // Clique em Salvar => submit no form (HTMX intercepta)
    btn.addEventListener("click", function () {
      if (!isDirty(root)) return;

      try {
        form.requestSubmit();
      } catch (_e) {
        form.submit();
      }
    });

    // UX "Salvando..." (HTMX)
    if (!document.body.dataset.__cmSaveHTMXBound) {
      document.body.dataset.__cmSaveHTMXBound = "1";

      document.body.addEventListener("htmx:beforeRequest", function (evt) {
        const elt = evt.detail?.elt;
        if (!elt) return;

        const r = getRoot();
        const f = getForm(r);
        const b = getSaveBtn(r);
        if (!r || !f || !b) return;

        if (elt === f) {
          b.dataset.__cmOldText = b.textContent || "Salvar";
          b.textContent = "Salvando...";
          b.disabled = true;
        }
      });

      document.body.addEventListener("htmx:afterRequest", function (evt) {
        const elt = evt.detail?.elt;
        if (!elt) return;

        const r = getRoot();
        const f = getForm(r);
        const b = getSaveBtn(r);
        if (!r || !f || !b) return;

        if (elt === f) {
          const ok = evt.detail?.successful === true;
          b.disabled = false;
          b.textContent = b.dataset.__cmOldText || "Salvar";
          delete b.dataset.__cmOldText;

          if (ok) setDirty(r, false);
        }
      });
    }
  }

  function boot() {
    bind(getRoot());
  }

  document.addEventListener("DOMContentLoaded", boot);

  document.body.addEventListener("htmx:afterSwap", function (e) {
    const t = e.target;
    if (!t) return;
    if (t.id === "modal-body") boot();
  });
})();
