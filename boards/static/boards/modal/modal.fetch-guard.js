// modal.fetch-guard.js
(() => {
  if (!window.fetch || window.fetch.__GUARDED__) return;

  const original = window.fetch;

  window.fetch = function (...args) {
    const url = args[0]?.toString?.() || "";

    if (url.includes("/card/") && !window.Modal.canOpen()) {
      return Promise.resolve(new Response("", { status: 204 }));
    }

    return original.apply(this, args);
  };

  window.fetch.__GUARDED__ = true;
})();
