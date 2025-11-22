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
// Alternar abas do modal
// =====================================================
window.cardOpenTab = function (panelId) {
    document.querySelectorAll('.card-tab-btn').forEach(btn => {
        btn.classList.toggle(
            'card-tab-active',
            btn.getAttribute('data-tab-target') === panelId
        );
    });

    document.querySelectorAll('.card-tab-panel').forEach(panel => {
        const isTarget = panel.id === panelId;
        panel.classList.toggle('block', isTarget);
        panel.classList.toggle('hidden', !isTarget);
    });

    sessionStorage.setItem('modalActiveTab', panelId);
};

// =====================================================
// Aplicar tema
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
// Inicializa Quill + Prism + Copiar Código
// =====================================================
window.initCardModal = function () {

    // ----- DESCRIÇÃO -----
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
        quill.on("text-change", () => {
            hiddenInput.value = quill.root.innerHTML;
        });
    }

    // =====================================================
    // ----- ATIVIDADE (100% corrigido — texto puro) -----
    // =====================================================

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

        quillAtiv.root.innerHTML = "";
        activityHidden.value = "";

        // TEXTO PURO — sem HTML, sem template
        quillAtiv.on("text-change", () => {
            let text = quillAtiv.getText().trim();
            activityHidden.value = text;
        });
    }

    // ----- Tema salvo -----
    const savedTheme = sessionStorage.getItem("currentModalTheme");
    if (savedTheme) {
        const root = document.getElementById("card-modal-root");
        if (root) root.classList.add(savedTheme);
    }

    // ----- PrismJS Highlight -----
    if (window.Prism) {
        Prism.highlightAll();
    }

    // ----- Copiar botão e wrapper -----
    enhanceCodeBlocks();
};

// =====================================================
// HTMX — quando o modal é injetado
// =====================================================
document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target.id !== "modal-body") return;

    openModal();
    initCardModal();

    const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
    cardOpenTab(active);
});

// =====================================================
// Remover TAG
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

    initCardModal();

    const active = sessionStorage.getItem("modalActiveTab") || "card-tab-desc";
    cardOpenTab(active);
};

// =====================================================
// Nova atividade
// =====================================================
window.submitActivity = async function (cardId) {
    const csrf = document.querySelector("meta[name='csrf-token']").content;
    const activityInput = document.getElementById("activity-input");
    if (!activityInput) return;

    const content = activityInput.value.trim();
    if (!content) return;

    const formData = new FormData();
    formData.append("content", content);

    const response = await fetch(`/card/${cardId}/activity/add/`, {
        method: "POST",
        headers: { "X-CSRFToken": csrf },
        body: formData
    });

    if (!response.ok) return;

    const html = await response.text();

    const wrapper = document.getElementById("activity-panel-wrapper");
    if (wrapper) {
        wrapper.innerHTML = html;
    }

    window.clearActivityEditor();

    enhanceCodeBlocks();
    if (window.Prism) Prism.highlightAll();
};

window.clearActivityEditor = function () {
    const editor = document.querySelector("#quill-editor-ativ .ql-editor");
    const hidden = document.getElementById("activity-input");

    if (editor) editor.innerHTML = "";
    if (hidden) hidden.value = "";
};


// =====================================================
// Abrir/fechar editor futurista de atividade
// =====================================================
window.toggleAtividadeEditor = function (forceClose = false) {
    const wrapper = document.getElementById("ativ-editor-wrapper");
    const btn = document.getElementById("ativ-toggle-btn");

    if (!wrapper || !btn) return;

    const isOpen = !wrapper.classList.contains("hidden");

    if (forceClose || isOpen) {
        wrapper.classList.add("hidden");
        btn.classList.remove("ativ-mini-tab-active");
        return;
    }

    wrapper.classList.remove("hidden");
    btn.classList.add("ativ-mini-tab-active");
};



// =====================================================
// REMOVER COMPLETAMENTE O BOTÃO COPIAR E WRAPPERS
// =====================================================
function enhanceCodeBlocks() {
    // Não envolve, não modifica, não adiciona nada
    // Apenas reaplica Prism se necessário
    if (window.Prism) {
        Prism.highlightAll();
    }
}

// Remove listeners antigos (caso algum esteja ativo)
document.removeEventListener("click", function () {});








// // =====================================================
// // Expandir / Recolher itens de atividade
// // =====================================================
// window.toggleActivityItem = function (btn) {
//     const wrapper = btn.previousElementSibling;

//     const expanded = wrapper.classList.toggle("expanded");

//     // Se expandiu, some o fade
//     const fade = wrapper.querySelector(".activity-fade");
//     if (fade) fade.style.display = expanded ? "none" : "block";

//     btn.textContent = expanded ? "Recolher" : "Expandir";
// };

// window.toggleActivityItem = function (el) {
//     const box = el.closest(".activity-item");

//     if (box.classList.contains("collapsed")) {
//         box.classList.remove("collapsed");
//         box.classList.add("expanded");
//         el.innerText = "Recolher";
//     } else {
//         box.classList.remove("expanded");
//         box.classList.add("collapsed");
//         el.innerText = "Expandir";
//     }
// };
