// =====================================================
// Variáveis globais
// =====================================================
window.currentCardId = null;

// =====================================================
// Abrir modal
// =====================================================
window.openModal = function () {
    const modal = document.getElementById("modal");
    if (modal) modal.classList.remove("hidden");
};

// =====================================================
// Fechar modal
// =====================================================
window.closeModal = function () {
    const modal = document.getElementById("modal");
    const modalBody = document.getElementById("modal-body");
    if (modal) modal.classList.add("hidden");
    if (modalBody) modalBody.innerHTML = "";
};

// =====================================================
// Atualiza o snippet do card na board
// =====================================================
window.refreshCardSnippet = function (cardId) {
    if (!cardId) return;

    htmx.ajax("GET", `/card/${cardId}/snippet/`, {
        target: `#card-${cardId}`,
        swap: "outerHTML"
    });
};

// =====================================================
// Alternar abas do modal (GLOBAL)
// =====================================================
window.cardOpenTab = function (panelId) {
    document.querySelectorAll('.card-tab-btn').forEach(btn => {
        btn.classList.toggle('card-tab-active',
            btn.getAttribute('data-tab-target') === panelId);
    });

    document.querySelectorAll('.card-tab-panel').forEach(panel => {
        panel.classList.toggle('block', panel.id === panelId);
        panel.classList.toggle('hidden', panel.id !== panelId);

    });

    sessionStorage.setItem('modalActiveTab', panelId);
};

// =====================================================
// Aplicar tema (GLOBAL)
// =====================================================
window.cardSetTheme = function (mode) {
    const root = document.getElementById('card-modal-root');
    if (!root) return;

    root.classList.remove("card-theme-white", "card-theme-aero", "card-theme-dark");
    root.classList.add(`card-theme-${mode}`);

    sessionStorage.setItem("currentModalTheme", `card-theme-${mode}`);
};

// =====================================================
// Tela cheia
// =====================================================
window.cardToggleFull = function () {
    const root = document.getElementById('card-modal-root');
    if (!root) return;

    root.classList.toggle('max-h-[80vh]');
    root.classList.toggle('h-[90vh]');
};

// =====================================================
// Inicializa Quill e aplica tema salvo
// =====================================================
window.initCardModal = function () {
    const hiddenInput = document.getElementById("description-input");
    if (!hiddenInput) return;

    const quill = new Quill("#quill-editor", {
        theme: "snow",
        modules: {
            toolbar: [
                [{ header: [1, 2, 3, false] }],
                ["bold", "italic", "underline"],
                ["link", "image"],
                [{ list: "ordered" }, { list: "bullet" }]
            ]
        }
    });

    quill.root.innerHTML = hiddenInput.value || "";
    quill.on("text-change", () => hiddenInput.value = quill.root.innerHTML);

    // Reaplicar tema salvo
    const savedTheme = sessionStorage.getItem("currentModalTheme");
    if (savedTheme) {
        const root = document.getElementById("card-modal-root");
        if (root) root.classList.add(savedTheme);
    }
};

// =====================================================
// HTMX: quando o modal for injetado
// =====================================================
document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target.id !== "modal-body") return;

    openModal();
    initCardModal();

    // Restaurar aba ativa
    const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
    cardOpenTab(active);
});

// =====================================================
// Remover TAG em tempo real
// =====================================================
window.removeTagInstant = async function (cardId, tag) {
    const csrf = document.querySelector("meta[name='csrf-token']").content;

    const formData = new FormData();
    formData.append("tag", tag);

    const response = await fetch(`/card/${cardId}/remove_tag/`, {
        method: "POST",
        headers: { "X-CSRFToken": csrf },
        body: formData
    });

    if (!response.ok) return;

    const data = await response.json();

    document.getElementById("modal-body").innerHTML = data.modal;

    const card = document.querySelector(`#card-${data.card_id}`);
    if (card) card.outerHTML = data.snippet;

   window.initCardModal = function () {

    /* EDITOR DE DESCRIÇÃO (JÁ EXISTENTE) */
    const hiddenInput = document.getElementById("description-input");
    if (hiddenInput) {
        const quill = new Quill("#quill-editor", {
            theme: "snow",
            modules: {
                toolbar: [
                    [{ header: [1, 2, 3, false] }],
                    ["bold", "italic", "underline"],
                    ["link", "image"],
                    [{ list: "ordered" }, { list: "bullet" }]
                ]
            }
        });

        quill.root.innerHTML = hiddenInput.value || "";
        quill.on("text-change", () => hiddenInput.value = quill.root.innerHTML);
    }

    /* EDITOR DE ATIVIDADE (NOVO) */
    const activityHidden = document.getElementById("activity-input");
    if (activityHidden) {
        const quillAtiv = new Quill("#quill-editor-ativ", {
            theme: "snow",
            modules: {
                toolbar: [
                    [{ header: [1, 2, 3, false] }],
                    ["bold", "italic", "underline"],
                    ["link", "image"],
                    [{ list: "ordered" }, { list: "bullet" }]
                ]
            }
        });

        quillAtiv.on("text-change", () => {
            activityHidden.value = quillAtiv.root.innerHTML;
        });
    }

    /* TEMA SALVO */
    const savedTheme = sessionStorage.getItem("currentModalTheme");
    if (savedTheme) {
        const root = document.getElementById("card-modal-root");
        if (root) root.classList.add(savedTheme);
    }
};


    const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
    cardOpenTab(active);
};

window.submitActivity = async function(cardId) {
    const content = document.getElementById("activity-input").value;
    const csrf = document.querySelector("meta[name='csrf-token']").content;

    if (!content.trim()) return;

    const formData = new FormData();
    formData.append("content", content);

    const response = await fetch(`/card/${cardId}/activity/add/`, {
        method: "POST",
        headers: { "X-CSRFToken": csrf },
        body: formData
    });

    if (response.ok) {
        const html = await response.text();
        document.querySelector("#card-tab-ativ").innerHTML = html;
        initCardModal();
    }
};

window.clearActivityEditor = function() {
    const container = document.querySelector("#quill-editor-ativ .ql-editor");
    if (container) container.innerHTML = "";
    document.getElementById("activity-input").value = "";
};
