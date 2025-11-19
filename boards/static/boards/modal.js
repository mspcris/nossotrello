function openModal() {
    document.getElementById("modal-overlay")?.classList.remove("hidden");
    document.getElementById("modal")?.classList.remove("hidden");
}

function closeModal() {
    document.getElementById("modal-overlay")?.classList.add("hidden");
    document.getElementById("modal")?.classList.add("hidden");
    document.getElementById("modal-body").innerHTML = "";
}

document.body.addEventListener("htmx:afterSwap", function (e) {
    // Só inicializa quando o modal receber conteúdo
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

    // Carrega no editor o HTML do hidden
    quill.root.innerHTML = hiddenInput.value || "";

    // Mantém hidden atualizado
    quill.on("text-change", () => {
        hiddenInput.value = quill.root.innerHTML;
    });

    // Zera o editor depois que o modal recarrega
quill.root.innerHTML = "";
hiddenInput.value = "";

    // Agora o modal deve abrir
    openModal();
});
