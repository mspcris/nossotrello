// modal.gate.js — Gate de segurança do Modal
(() => {
  if (!window.Modal) {
    console.error("Modal.core.js precisa ser carregado antes do modal.gate.js");
    return;
  }

  if (window.Modal.gate) return; // evita double-load

  const blocks = new Map(); // reason -> until(timestamp)

  function now() {
    return Date.now();
  }

  function cleanup() {
    const t = now();
    for (const [reason, until] of blocks.entries()) {
      if (t >= until) blocks.delete(reason);
    }
  }

  window.Modal.gate = {
    block(ms, reason = "unknown") {
      if (!ms || ms <= 0) return;
      blocks.set(reason, now() + ms);
    },

    unblock(reason) {
      blocks.delete(reason);
    },

    isBlocked() {
      cleanup();
      return blocks.size > 0;
    },

    debug() {
      cleanup();
      return Array.from(blocks.entries()).map(([r, u]) => ({
        reason: r,
        until: u,
        msLeft: Math.max(0, u - now()),
      }));
    },
  };

  // API de conveniência
  window.Modal.canOpen = function () {
    return !window.Modal.gate.isBlocked();
  };
})();
