document.body.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target.id === "modal-content") {
        openModal();
    }
});
