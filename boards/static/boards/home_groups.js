(function () {
  function getCsrf() {
    return (
      document.querySelector("[name=csrfmiddlewaretoken]")?.value ||
      document.querySelector("input[name=csrfmiddlewaretoken]")?.value ||
      ""
    );
  }

  async function post(url, data) {
    const resp = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-CSRFToken": getCsrf()
      },
      body: new URLSearchParams(data || {}).toString()
    });
    return resp;
  }

  async function postJson(url, data) {
    const resp = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrf(),
        "Accept": "application/json"
      },
      body: JSON.stringify(data || {})
    });
    return resp;
  }

  function ensureSortableHome() {
    if (!window.Sortable) return;

    // cards originais (meus + compartilhados) viram “source lists”
    const sourceLists = Array.from(document.querySelectorAll(".home-source-list"));
    const dropZones = Array.from(document.querySelectorAll(".home-group-dropzone"));

    // Se não tiver marcação ainda, não ativa
    if (!dropZones.length) return;

    // Source: permite arrastar e CLONAR
    sourceLists.forEach((list) => {
      if (list.dataset.sortableApplied === "1") return;
      list.dataset.sortableApplied = "1";

      new Sortable(list, {
        group: { name: "homeboards", pull: "clone", put: false },
        sort: false,
        animation: 150,
        draggable: ".board-card[data-board-id]",
        delay: 280,
        delayOnTouchOnly: true,
        touchStartThreshold: 10
      });
    });

    // Dropzones: recebem clones, e ao soltar criam vínculo
    dropZones.forEach((zone) => {
      if (zone.dataset.sortableApplied === "1") return;
      zone.dataset.sortableApplied = "1";

      const groupId = Number(zone.getAttribute("data-group-id") || 0);
      const itemsEl = zone.querySelector(`[id^="home-group-items-"]`) || zone;

      new Sortable(itemsEl, {
        group: { name: "homeboards", pull: false, put: true },
        sort: true,
        animation: 150,
        draggable: ".board-card[data-board-id]",
        delay: 280,
        delayOnTouchOnly: true,
        touchStartThreshold: 10,

        onAdd: async (evt) => {
          const cardEl = evt.item;
          const boardId = Number(cardEl.getAttribute("data-board-id") || 0);
          if (!groupId || !boardId) return;

          // Remove o clone “temporário” se ele veio de clone e não tem botões corretos
          // Por simplicidade, mantém e depois recarrega a página se quiser.
          const resp = await post(`/home/groups/${groupId}/items/add/`, { board_id: boardId });
          if (!resp.ok) {
            // rollback visual
            try { evt.from.insertBefore(cardEl, evt.from.children[evt.oldIndex] || null); } catch (_e) {}
            return;
          }

          // Recarrega para renderizar o card do jeito certo (com botões remover/estrela)
          // (fase 2: retornar html parcial e trocar só o card)
          location.reload();
        }
      });
    });
  }

  window.HomeGroups = {
    renameGroup: async function (groupId, currentName) {
      const name = prompt("Novo nome do agrupamento:", currentName || "");
      if (!name) return;

      const resp = await post(`/home/groups/${groupId}/rename/`, { name });
      if (resp.ok) location.reload();
    },

    deleteGroup: async function (groupId) {
      if (!confirm("Apagar este agrupamento? Os quadros não serão apagados.")) return;

      const resp = await post(`/home/groups/${groupId}/delete/`, {});
      if (resp.ok) location.reload();
    },

    removeFromGroup: async function (groupId, boardId, btnEl) {
      if (!confirm("Remover este quadro do agrupamento?")) return;

      const resp = await post(`/home/groups/${groupId}/items/${boardId}/remove/`, {});
      if (resp.ok) location.reload();
    },

    toggleFavorite: async function (boardId, btnEl) {
      const resp = await postJson(`/home/favorites/toggle/`, { board_id: boardId });
      if (!resp.ok) return;

      const data = await resp.json().catch(() => null);
      if (!data) return;

      if (btnEl) btnEl.textContent = data.favorited ? "★" : "☆";

      // opcional: se está em Favoritos, recarrega para refletir lista
      // (simples e consistente)
      location.reload();
    }
  };

  document.addEventListener("DOMContentLoaded", ensureSortableHome);
  document.body.addEventListener("htmx:afterSwap", ensureSortableHome);
})();
