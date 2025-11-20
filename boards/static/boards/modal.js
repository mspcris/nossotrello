// Variável global usada para saber qual card está aberto
window.currentCardId = null;

function openModal() {
    document.getElementById("modal")?.classList.remove("hidden");
}

function refreshCardSnippet(cardId) {
    if (!cardId) return;
    htmx.ajax("GET", `/card/${cardId}/snippet/`, {
        target: `#card-${cardId}`,
        swap: "outerHTML"
    });
}

function closeModal() {
    document.getElementById("modal")?.classList.add("hidden");
    document.getElementById("modal-body").innerHTML = "";
}

document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target.id !== "modal-body") return;

    const hiddenInput = document.getElementById("description-input");

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

    openModal();
});
