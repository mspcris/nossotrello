// modal.fetch-guard.js
(() => {
  // evita bind duplo do guard
  if (window.__CM_MODAL_FETCH_GUARD__) return;
  window.__CM_MODAL_FETCH_GUARD__ = true;

  // ------------------------------------------------------------
  // 1) Guard do modal: bloqueia apenas chamadas de "abrir modal"
  //    quando Modal.canOpen() = false
  // ------------------------------------------------------------
  function canOpenModal() {
    try {
      return !window.Modal || typeof window.Modal.canOpen !== "function"
        ? true
        : !!window.Modal.canOpen();
    } catch (_e) {
      return true;
    }
  }

  function isModalOpenUrl(url) {
    // ajuste aqui se o seu endpoint de modal for diferente
    // exemplos comuns:
    //  - /card/292/modal
    //  - /card/292/modal/
    //  - /board/11/card/292/modal
    const u = String(url || "");
    return /\/card\/\d+\/modal\/?$/.test(u) || /\/card\/\d+\/modal\//.test(u);
  }

  if (window.fetch && !window.fetch.__GUARDED__) {
    const original = window.fetch;

    window.fetch = function (...args) {
      const url = args[0]?.toString?.() || "";

      // IMPORTANTE: não bloqueia nada de /activity/add aqui.
      // Só bloqueia abertura do modal.
      if (isModalOpenUrl(url) && !canOpenModal()) {
        return Promise.resolve(new Response("", { status: 204 }));
      }

      return original.apply(this, args);
    };

    window.fetch.__GUARDED__ = true;
  }

  // ------------------------------------------------------------
  // 2) Anti double-submit: cancela requisições duplicadas do HTMX
  //    (foco em POST /activity/add)
  // ------------------------------------------------------------
  const RECENT = new Map(); // key -> timestamp(ms)

  function getRequestPath(detail) {
    return (
      detail?.pathInfo?.requestPath ||
      detail?.path ||
      detail?.requestPath ||
      ""
    );
  }

  function buildActivitySignature(detail) {
    // Assinatura mínima para considerar “igual”:
    // - endpoint
    // - reply_to
    // - conteúdo (content/text/delta)
    const params = detail?.parameters || {};
    const replyTo = String(params.reply_to || "").trim();

    // tenta cobrir os 3 formatos que você já usa no projeto (html/text/delta)
    const content = String(params.content || "").trim();
    const text = String(params.text || "").trim();
    const delta = typeof params.delta === "string" ? params.delta : "";

    // chave curta (não precisa serializar tudo)
    return `${replyTo}::${content}::${text}::${delta}`;
  }

  document.body.addEventListener(
    "htmx:beforeRequest",
    function (evt) {
      const d = evt.detail;
      if (!d) return;

      const verb = String(d.verb || "").toUpperCase();
      if (verb !== "POST") return;

      const path = getRequestPath(d);
      if (!path.includes("/activity/add")) return;

      const sig = buildActivitySignature(d);
      const key = `${verb} ${path} ${sig}`;

      const now = Date.now();
      const prev = RECENT.get(key) || 0;

      // janela curta: suficiente pra “duplo clique” e “duplo gatilho”
      if (now - prev < 900) {
        evt.preventDefault();
        return;
      }

      RECENT.set(key, now);

      // limpeza simples para não crescer infinito
      // (remove entradas com mais de 20s)
      if (RECENT.size > 200) {
        for (const [k, t] of RECENT.entries()) {
          if (now - t > 20000) RECENT.delete(k);
        }
      }
    },
    true
  );
})();
