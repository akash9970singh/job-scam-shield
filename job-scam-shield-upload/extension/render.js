// Result card shared by the popup, the right-click toast and the Gmail banner.
// Rendered inside a shadow root so the host page's CSS can't restyle it.
(() => {
  if (window.JobScamShield) return; // injected more than once on the same page

  const LABELS = { high: "High risk", medium: "Suspicious", low: "Low risk" };
  const COLLAPSED_FLAGS = 3;

  const STYLE = `
    :host { all: initial; }
    .card { --bg: #ffffff; --text: #1d2330; --muted: #5b6475; --border: #dde1e8;
            --high: #c62828; --medium: #b26a00; --low: #2e7d32; --accent: #2457d6;
            font: 13px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--text);
            background: var(--bg); border: 1px solid var(--border); border-left: 5px solid var(--level);
            border-radius: 8px; padding: 10px 12px; box-sizing: border-box; max-width: 100%; }
    @media (prefers-color-scheme: dark) {
      .card { --bg: #1b1f27; --text: #e6e9ef; --muted: #9aa3b5; --border: #2c323d;
              --high: #ff6b6b; --medium: #ffb54d; --low: #66c66b; --accent: #6d95ff; }
    }
    .card.high { --level: var(--high); } .card.medium { --level: var(--medium); }
    .card.low { --level: var(--low); } .card.error, .card.pending { --level: var(--muted); }
    .head { display: flex; align-items: center; gap: 8px; }
    .title { font-weight: 700; font-size: 14px; color: var(--level); }
    .brand { color: var(--muted); font-size: 11px; margin-left: auto; }
    .close { border: 0; background: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 0 2px; }
    p { margin: 6px 0; }
    ul { margin: 6px 0; padding-left: 18px; }
    li { margin: 3px 0; overflow-wrap: anywhere; }
    .more { border: 0; background: none; color: var(--accent); cursor: pointer; padding: 0; font: inherit; }
    .good { color: var(--low); }
  `;

  function esc(value) {
    return String(value).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  function bodyHtml(response) {
    if (response.pending) {
      return { level: "pending", head: "Checking for scam signs…", html: "" };
    }
    if (!response.ok) {
      return { level: "error", head: "Couldn't check this", html: `<p>${esc(response.error)}</p>` };
    }
    const r = response.result;
    const flags = r.red_flags.map((f, i) =>
      `<li ${i >= COLLAPSED_FLAGS ? 'hidden data-extra' : ""}>${esc(f.message)}</li>`).join("");
    const extra = r.red_flags.length - COLLAPSED_FLAGS;
    const good = r.good_signs.map((g) => `<li class="good">${esc(g.message)}</li>`).join("");
    return {
      level: r.level,
      head: `${LABELS[r.level]} · ${r.score}/100`,
      html: `<p>${esc(r.verdict)}</p>
        ${flags ? `<ul>${flags}</ul>` : ""}
        ${extra > 0 ? `<button class="more" type="button">Show ${extra} more</button>` : ""}
        ${good ? `<ul>${good}</ul>` : ""}`,
    };
  }

  // response: {ok, result} | {ok: false, error} | {pending: true}
  function renderCard(response, { onClose } = {}) {
    const host = document.createElement("div");
    host.setAttribute("data-job-scam-shield", "");
    const root = host.attachShadow({ mode: "open" });
    const { level, head, html } = bodyHtml(response);
    root.innerHTML = `<style>${STYLE}</style>
      <div class="card ${level}" role="status">
        <div class="head">
          <span class="title">${esc(head)}</span>
          <span class="brand">Job Scam Shield</span>
          ${onClose ? '<button class="close" type="button" aria-label="Close">×</button>' : ""}
        </div>
        ${html}
      </div>`;
    root.querySelector(".close")?.addEventListener("click", onClose);
    root.querySelector(".more")?.addEventListener("click", (e) => {
      root.querySelectorAll("[data-extra]").forEach((li) => (li.hidden = false));
      e.currentTarget.remove();
    });
    return host;
  }

  function showToast(response) {
    document.getElementById("job-scam-shield-toast")?.remove();
    const host = renderCard(response, { onClose: () => host.remove() });
    host.id = "job-scam-shield-toast";
    Object.assign(host.style, {
      position: "fixed", top: "16px", right: "16px", width: "min(380px, calc(100vw - 32px))",
      zIndex: "2147483647", boxShadow: "0 8px 24px rgba(0,0,0,.25)", borderRadius: "8px",
    });
    document.body.append(host);
  }

  window.JobScamShield = { renderCard, showToast };
})();
