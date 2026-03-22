// boards/static/boards/home_groups.js
(function () {
  // ==========================
  // Helpers (CSRF + POST)
  // ==========================
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
        "X-CSRFToken": getCsrf(),
        Accept: "application/json",
      },
      body: new URLSearchParams(data || {}).toString(),
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
        Accept: "application/json",
      },
      body: JSON.stringify(data || {}),
    });
    return resp;
  }

  // ==========================
  // Sortable (drag & drop)
  // ==========================
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
        touchStartThreshold: 10,
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

          const resp = await post(`/home/groups/${groupId}/items/add/`, { board_id: boardId });
          if (!resp.ok) {
            // rollback visual
            try {
              evt.from.insertBefore(cardEl, evt.from.children[evt.oldIndex] || null);
            } catch (_e) {}
            return;
          }

          // MVP: recarrega para garantir render correto do card
          location.reload();
        },
      });
    });
  }

  // ==========================
  // Modal de agrupamento (sem dependências)
  // ==========================
  function closeGroupPickerModal() {
    const el = document.getElementById("group-picker-modal");
    if (el) el.remove();
  }

  function renderGroupPickerModal(groups, boardId) {
    closeGroupPickerModal();

    const modal = document.createElement("div");
    modal.id = "group-picker-modal";
    modal.className =
      "fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50";

    const sheet = document.createElement("div");
    sheet.className =
      "w-full sm:w-[420px] bg-white rounded-t-2xl sm:rounded-2xl shadow-xl p-4";

    sheet.innerHTML = `
      <div class="flex items-center justify-between mb-3">
        <div class="text-base font-bold">Agrupar quadro</div>
        <button type="button" class="text-sm px-2 py-1 rounded-md bg-gray-100 hover:bg-gray-200" aria-label="Fechar">Fechar</button>
      </div>
      <div class="text-sm text-gray-600 mb-3">Selecione um agrupamento:</div>
      <div class="flex flex-col gap-2" id="group-picker-list"></div>
    `;

    // fechar por botão
    sheet.querySelector("button")?.addEventListener("click", closeGroupPickerModal);

    // fechar clicando fora
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeGroupPickerModal();
    });

    const list = sheet.querySelector("#group-picker-list");
    groups.forEach((g) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "w-full text-left px-3 py-2 rounded-lg border hover:bg-gray-50";
      btn.textContent = g.name;

      btn.addEventListener("click", async () => {
        await window.HomeGroups.addToGroup(boardId, g.id);
      });

      list?.appendChild(btn);
    });

    modal.appendChild(sheet);
    document.body.appendChild(modal);
  }

  // ==========================
  // UI: atualiza barra de favoritos (topo) sem reload
  // ==========================
  function updateFavoritesBar(boardId, boardCard, favorited) {
    const favContainer = document.getElementById("home-favorites-items");
    if (!favContainer) return;

    const selector = `.board-card[data-board-id="${boardId}"]`;

    if (favorited) {
      const exists = favContainer.querySelector(selector);
      if (!exists && boardCard) {
        const clone = boardCard.cloneNode(true);

        // Ajusta a estrela no clone para refletir estado atual (evento será por delegação)
        const star = clone.querySelector(".favorite-star");
        if (star) {
          star.textContent = "★";
          star.setAttribute("data-board-id", String(boardId));
          if (!star.getAttribute("data-toggle-url")) {
            star.setAttribute("data-toggle-url", `/home/favorites/toggle/${boardId}/`);
          }
        }

        favContainer.prepend(clone);

        // remove placeholder "Sem favoritos" se existir
        const emptyMsg = favContainer.querySelector(":scope > .text-gray-300");
        if (emptyMsg && favContainer.querySelectorAll(".board-card").length > 0) {
          emptyMsg.remove();
        }
      }
    } else {
      const toRemove = favContainer.querySelector(selector);
      if (toRemove) toRemove.remove();

      if (favContainer.querySelectorAll(".board-card").length === 0) {
        favContainer.innerHTML = `
          <div class="text-gray-300 backdrop-blur-lg px-4 py-2 rounded-lg">
            Sem favoritos ainda.
          </div>
        `;
      }
    }
  }

  // ==========================
  // Delegação de eventos (para funcionar no clone)
  // ==========================
  function setupDelegatedHandlers() {
    if (document.body.dataset.homeGroupsDelegation === "1") return;
    document.body.dataset.homeGroupsDelegation = "1";

    document.body.addEventListener("click", (ev) => {
      const star = ev.target?.closest?.(".favorite-star");
      if (star) {
        const boardId =
          Number(star.getAttribute("data-board-id") || star.dataset.boardId || 0) ||
          Number(star.closest(".board-card")?.getAttribute("data-board-id") || 0);

        window.HomeGroups?.toggleFavorite(boardId, star, ev);
        return;
      }

      const groupBtn = ev.target?.closest?.("[data-home-open-group-picker]");
      if (groupBtn) {
        const boardId =
          Number(groupBtn.getAttribute("data-board-id") || groupBtn.dataset.boardId || 0) ||
          Number(groupBtn.closest(".board-card")?.getAttribute("data-board-id") || 0);

        window.HomeGroups?.openGroupPicker(boardId, ev);
        return;
      }

      const renameBtn = ev.target?.closest?.("[data-rename-board]");
      if (renameBtn) {
        const boardId =
          Number(renameBtn.getAttribute("data-board-id") || renameBtn.dataset.boardId || 0) ||
          Number(renameBtn.closest(".board-card")?.getAttribute("data-board-id") || 0);

        window.HomeGroups?.renameBoard(boardId, renameBtn, ev);
        return;
      }
    });
  }

  // ==========================
  // API pública (window.HomeGroups)
  // ==========================
  window.HomeGroups = {
    // ========= existentes =========
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

    // ========= favoritos =========
    toggleFavorite: async function (boardId, el, ev) {
      try {
        if (ev) {
          ev.preventDefault();
          ev.stopPropagation();
        }

        if (!el) return;
        if (el.dataset.busy === "1") return;
        el.dataset.busy = "1";

        const url = el.getAttribute("data-toggle-url") || `/home/favorites/toggle/${boardId}/`;

        const resp = await fetch(url, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "X-CSRFToken": getCsrf(),
            Accept: "application/json",
          },
        });

        if (!resp.ok) {
          const txt = await resp.text();
          console.error("toggleFavorite failed:", resp.status, txt);
          return;
        }

        const data = await resp.json();
        const favorited = !!data.favorited;

        // Atualiza estrela clicada
        el.textContent = favorited ? "★" : "☆";

        // Atualiza a barra de favoritos (topo) sem reload
        const boardCard = el.closest(".board-card");
        updateFavoritesBar(boardId, boardCard, favorited);
      } catch (e) {
        console.error("toggleFavorite error:", e);
      } finally {
        if (el) el.dataset.busy = "0";
      }
    },

    // ========= renomear quadro (htmx) =========
    renameBoard: function (boardId, btn, ev) {
      try {
        ev?.preventDefault?.();
        ev?.stopPropagation?.();

        const card = btn?.closest?.(".board-card");
        if (!card) return;

        const h2 = card.querySelector(".board-card__body h2");
        const current = (h2?.textContent || "").trim();
        const next = (prompt("Novo nome do quadro:", current) || "").trim();

        if (!next || next === current) return;

        const url = btn.dataset.renameUrl;
        if (!url || !window.htmx) return;

        // POST (usa o endpoint existente: rename_board)
        window.htmx.ajax("POST", url, {
          swap: "none",
          values: { name: next },
        });

        // UI otimista
        if (h2) h2.textContent = next;
        card.dataset.boardName = next.toLowerCase();
      } catch (e) {
        console.error("renameBoard error:", e);
      }
    },

    // ========= novo: agrupar por botão =========
    openGroupPicker: function (boardId, event) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }

      // Lê do DOM para refletir create/delete/rename sem F5
      const groups = Array.from(
        document.querySelectorAll("#home-custom-groups .home-group-wrapper")
      )
        .map((wrap) => {
          const idRaw = (wrap.id || "").replace("group-", "");
          const id = Number(idRaw || 0);
          const name = (wrap.querySelector("h2")?.textContent || "").trim();
          return id && name ? { id, name } : null;
        })
        .filter(Boolean);

      if (!groups.length) {
        alert("Nenhum agrupamento disponível. Crie um agrupamento primeiro.");
        return;
      }

      renderGroupPickerModal(groups, boardId);
    },

    addToGroup: async function (boardId, groupId) {
      try {
        const resp = await post(`/home/groups/${groupId}/items/add/`, { board_id: boardId });

        if (!resp.ok) {
          const txt = await resp.text();
          console.error("addToGroup failed:", resp.status, txt);
          alert("Não foi possível agrupar. Verifique permissões e tente novamente.");
          return;
        }

        closeGroupPickerModal();
        // MVP: garante consistência visual sem mexer na renderização parcial
        location.reload();
      } catch (e) {
        console.error("addToGroup error:", e);
        alert("Não foi possível agrupar. Verifique permissões e tente novamente.");
      }
    },
  };

  // ==========================
  // Boot
  // ==========================
  document.addEventListener("DOMContentLoaded", function () {
    setupDelegatedHandlers();
    ensureSortableHome();
  });

  document.body.addEventListener("htmx:afterSwap", function () {
    setupDelegatedHandlers();
    ensureSortableHome();
  });

  document.body.addEventListener("htmx:load", function () {
    setupDelegatedHandlers();
    ensureSortableHome();
  });
})();
