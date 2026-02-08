// modal.fetch-guard.js
(() => {
  if (!window.fetch || window.fetch.__GUARDED__) return;

  const original = window.fetch;

  // Dedup: mantém POSTs idênticos "in-flight" por uma janela curta
  const inFlight = new Map(); // key -> { ts, promise }

  const DEDUP_WINDOW_MS = 1200;
  const ADD_PATH_RE = /\/card\/\d+\/activity\/add\/?$/;

  function now() {
    return Date.now();
  }

  function getUrl(input) {
    try {
      if (typeof input === "string") return input;
      if (input && typeof input.url === "string") return input.url; // Request
      return input?.toString?.() || "";
    } catch {
      return "";
    }
  }

  function getMethod(init) {
    const m = (init?.method || "GET").toString().toUpperCase();
    return m;
  }

  function looksLikeAdd(url) {
    try {
      // aceita url absoluta/relativa
      const u = new URL(url, window.location.origin);
      return ADD_PATH_RE.test(u.pathname);
    } catch {
      return url.includes("/activity/add");
    }
  }

  function stableStringifyFormData(fd) {
    // Serializa FormData de forma determinística (inclui File metadados)
    const items = [];
    for (const [k, v] of fd.entries()) {
      if (v instanceof File) {
        items.push([k, `__file__:${v.name}:${v.size}:${v.type}`]);
      } else {
        items.push([k, String(v)]);
      }
    }
    items.sort((a, b) => (a[0] + "\u0000" + a[1]).localeCompare(b[0] + "\u0000" + b[1]));
    return items.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
  }

  function bodySignature(body) {
    if (!body) return "";
    try {
      if (typeof body === "string") return body;
      if (body instanceof URLSearchParams) return body.toString();
      if (body instanceof FormData) return stableStringifyFormData(body);
      if (body instanceof Blob) return `__blob__:${body.type}:${body.size}`;
      // fallback (obj, etc)
      return `__body__:${Object.prototype.toString.call(body)}`;
    } catch {
      return "__body__:unreadable";
    }
  }

  function makeDedupKey(url, init) {
    const method = getMethod(init);
    const sig = bodySignature(init?.body);
    return `${method} ${url} :: ${sig}`;
  }

  function cleanupOld() {
    const t = now();
    for (const [k, v] of inFlight.entries()) {
      if (t - v.ts > DEDUP_WINDOW_MS) inFlight.delete(k);
    }
  }

  window.fetch = function (input, init = {}) {
    const url = getUrl(input);

    // Guard do modal (se não pode abrir, não deixa /card/ disparar)
    if (url.includes("/card/") && !window.Modal?.canOpen?.()) {
      return Promise.resolve(new Response("", { status: 204 }));
    }

    // Dedup específico: POST no add de activity
    const method = getMethod(init);
    if (method === "POST" && looksLikeAdd(url)) {
      cleanupOld();

      const key = makeDedupKey(url, init);
      const existing = inFlight.get(key);

      if (existing && (now() - existing.ts) <= DEDUP_WINDOW_MS) {
        // Reaproveita a mesma promise: impede dupla gravação e dupla renderização
        return existing.promise;
      }

      const p = original.call(this, input, init).finally(() => {
        // Remove quando terminar (sucesso/erro)
        inFlight.delete(key);
      });

      inFlight.set(key, { ts: now(), promise: p });
      return p;
    }

    return original.call(this, input, init);
  };

  window.fetch.__GUARDED__ = true;
})();
