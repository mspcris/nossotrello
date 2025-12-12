// =====================================================
// Variáveis globais
// =====================================================
window.currentCardId = null;
let quillAtiv = null;   // necessário para limpar corretamente


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
// Aplicar tema manual
// =====================================================
window.cardSetTheme = function (mode) {
    const root = document.getElementById('card-modal-root');
    if (!root) return;

    root.classList.remove("card-theme-white", "card-theme-aero", "card-theme-dark");
    root.classList.add(`card-theme-${mode}`);

    sessionStorage.setItem("currentModalTheme", `card-theme-${mode}`);
};


// =====================================================
// Inicializa Quill + Prism
// =====================================================
window.initCardModal = function () {

    // Forçar tema AERO como default
    const root = document.getElementById("card-modal-root");
    if (root) {
        root.classList.remove("card-theme-white", "card-theme-dark", "card-theme-aero");
        root.classList.add("card-theme-aero");
    }

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

    // ----- ATIVIDADE -----
    const activityHidden = document.getElementById("activity-input");

    if (activityHidden) {

        quillAtiv = new Quill("#quill-editor-ativ", {
            theme: "snow",
            modules: {
                toolbar: {
                    container: [
                        [{ header: [1, 2, 3, false] }],
                        ["bold", "italic", "underline"],
                        ["link", "image"],
                        [{ list: "ordered" }, { list: "bullet" }]
                    ],
                    handlers: {
                        image: function () {
                            let fileInput = document.createElement("input");
                            fileInput.setAttribute("type", "file");
                            fileInput.setAttribute("accept", "image/*");

                            fileInput.onchange = async () => {
                                const file = fileInput.files[0];
                                if (!file) return;

                                let formData = new FormData();
                                formData.append("image", file);

                                const resp = await fetch("/quill/upload/", {
                                    method: "POST",
                                    body: formData
                                });

                                const data = await resp.json();

                                if (data.url) {
                                    let range = quillAtiv.getSelection();
                                    quillAtiv.insertEmbed(range.index, "image", data.url);
                                }
                            };

                            fileInput.click();
                        }
                    }
                }
            }
        });

        quillAtiv.root.innerHTML = "";
        activityHidden.value = "";

        quillAtiv.on("text-change", () => {
            activityHidden.value = quillAtiv.root.innerHTML;
        });
    }
};


// =====================================================
// HTMX – Modal carregado
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
// Limpar editor de atividade
// =====================================================
window.clearActivityEditor = function () {
    const activityHidden = document.getElementById("activity-input");

    if (quillAtiv) {
        quillAtiv.setText("");
    }

    if (activityHidden) {
        activityHidden.value = "";
    }
};


// =====================================================
// Enviar nova atividade
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
    if (wrapper) wrapper.innerHTML = html;

    clearActivityEditor();
    ativSwitchSubTab("ativ-historico-panel");

    if (window.Prism) Prism.highlightAll();
};


// =====================================================
// Sub-abas de atividade
// =====================================================
window.ativSwitchSubTab = function (panelId) {

    document.querySelectorAll(".ativ-subtab-panel")
        .forEach(p => p.classList.add("hidden"));

    document.getElementById(panelId).classList.remove("hidden");

    document.querySelectorAll(".ativ-subtab-btn")
        .forEach(b => b.classList.remove("ativ-subtab-active"));

    const btn = document.querySelector(`.ativ-subtab-btn[data-subtab='${panelId}']`);
    if (btn) btn.classList.add("ativ-subtab-active");
};
