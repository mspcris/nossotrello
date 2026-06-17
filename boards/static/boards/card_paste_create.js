// boards/static/boards/card_paste_create.js
//
// Criar card colando imagem (Ctrl+V) no formulário "+ Card":
// - a imagem colada vira a CAPA do card;
// - o card é criado na hora (título vazio -> "Card criado por <nome>" no servidor);
// - o modal do card abre automaticamente pra você preencher nome/descrição.
(function () {
  if (window.__cardPasteCreateBound) return;
  window.__cardPasteCreateBound = true;

  function csrf() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : "";
  }

  function createCardWithCover(form, file) {
    const colId = form.getAttribute("data-column-id");
    const where = (form.getAttribute("data-where") || "bottom").trim();
    const url = form.getAttribute("hx-post") || `/column/${colId}/add_card/`;

    const titleInput = form.querySelector('input[name="title"]');
    const title = ((titleInput && titleInput.value) || "").trim();

    const fd = new FormData();
    if (title) fd.append("title", title); // vazio -> servidor usa o padrão
    fd.append("where", where);
    fd.append("cover", file, file.name || "capa.png");

    // feedback simples: desabilita o form enquanto cria
    form.style.opacity = "0.6";
    form.style.pointerEvents = "none";

    fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: fd,
    })
      .then((r) => (r.ok ? r.text() : Promise.reject(r.status)))
      .then((html) => {
        const list = document.getElementById("cards-col-" + colId);
        const tmp = document.createElement("div");
        tmp.innerHTML = (html || "").trim();
        const li = tmp.querySelector("li[data-card-id]");
        if (li && list) {
          if (where === "top") list.prepend(li);
          else list.appendChild(li);
        }
        try { form.remove(); } catch (_e) {}
        try { window.initSortable && window.initSortable(); } catch (_e) {}
        try { window.updateAggregatorCounts && window.updateAggregatorCounts(); } catch (_e) {}

        const cardId = li && li.getAttribute("data-card-id");
        if (cardId && window.Modal && typeof window.Modal.openCard === "function") {
          // abre o card recém-criado pra preencher nome/descrição
          window.Modal.openCard(cardId, false, li);
        }
      })
      .catch(() => {
        form.style.opacity = "";
        form.style.pointerEvents = "";
        alert("Não consegui criar o card com a imagem colada. Tente de novo.");
      });
  }

  document.addEventListener("paste", function (e) {
    const form = e.target && e.target.closest && e.target.closest("[data-add-card-form]");
    if (!form) return;

    const cd = e.clipboardData;
    if (!cd) return;
    const items = cd.items ? Array.prototype.slice.call(cd.items) : [];
    const imgItem = items.find((it) => (it.type || "").startsWith("image/"));
    if (!imgItem) return;

    const file = imgItem.getAsFile && imgItem.getAsFile();
    if (!file) return;

    e.preventDefault();
    createCardWithCover(form, file);
  });
})();
