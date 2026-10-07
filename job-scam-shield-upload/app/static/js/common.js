// Shared by every page: header/footer, API calls, and the result view.
// Everything is exposed on window.JSS so page scripts don't collide with each other.
(() => {
  const NAV = [
    { href: "/check", label: "Check a message" },
    { href: "/chat", label: "Check a chat" },
    { href: "/offer-letter", label: "Check an offer letter" },
    { href: "/report", label: "Report a scammer" },
    { href: "/tools", label: "Browser & Telegram" },
  ];

  const STAGES = {
    contact: [1, "Hook / job offer"],
    off_platform: [2, "Moved to Telegram/WhatsApp"],
    trust_task: [3, "Small paid task"],
    money_ask: [4, "Asked to pay"],
    pressure: [5, "Pay more to withdraw"],
  };
  const LEVEL_TEXT = { high: "High risk", medium: "Suspicious", low: "Low risk" };
  const NEXT_STEPS = {
    high: [
      "Do not pay anything: no fee, deposit, \"refundable\" amount or task top-up.",
      "Don't share Aadhaar, PAN, bank details or OTPs.",
      "Stop replying. If you already paid, call 1930 or report at cybercrime.gov.in right away.",
    ],
    medium: [
      "Verify the offer on the company's official careers page or official HR email.",
      "Don't pay or share documents until you've confirmed it's real.",
      "Ask your college placement cell if they know this recruiter.",
    ],
    low: [
      "No major red flags, but still confirm the recruiter through official channels.",
      "Remember: a genuine employer never asks you to pay to get or keep a job.",
    ],
  };
  const SERVER_DOWN = "Can't reach the Job Scam Shield server. Make sure it's running " +
    "(uvicorn app.main:app) and open this page through http://127.0.0.1:8000.";

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const SHIELD_SVG = `<svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Z" fill="var(--accent)"/>
    <path d="m8.5 12 2.5 2.5 4.5-5" stroke="var(--accent-ink)" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

  function renderChrome() {
    const path = location.pathname.replace(/\/$/, "") || "/";
    const header = document.createElement("header");
    header.className = "site-header";
    header.innerHTML = `<div class="inner">
      <a class="brand" href="/">${SHIELD_SVG}<span>Job Scam Shield</span></a>
      <nav class="nav" aria-label="Main">${NAV.map((n) =>
        `<a href="${n.href}"${n.href === path ? ' class="active" aria-current="page"' : ""}>${n.label}</a>`).join("")}</nav>
      <a class="header-cta" href="/dashboard">Placement cell login</a>
    </div>`;
    document.body.prepend(header);

    const footer = document.createElement("footer");
    footer.className = "site-footer";
    footer.innerHTML = `<div class="inner">
      <span>Lost money to a job scam? Call <strong>1930</strong> or report at
        <a href="https://cybercrime.gov.in" target="_blank" rel="noopener">cybercrime.gov.in</a>.</span>
      <span>Job Scam Shield gives a risk estimate, not a guarantee. Always verify offers officially.</span>
    </div>`;
    document.body.append(footer);
  }

  // POST JSON (or FormData). Returns {ok, status, data}; throws only when the server can't be reached.
  async function api(path, body, { method = "POST" } = {}) {
    if (location.protocol === "file:") throw new Error(SERVER_DOWN);
    const options = { method };
    if (body instanceof FormData) options.body = body;
    else if (body !== undefined) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    let res;
    try { res = await fetch(path, options); } catch { throw new Error(SERVER_DOWN); }
    const data = await res.json().catch(() => null);
    if (data === null && res.ok) throw new Error(SERVER_DOWN);
    return { ok: res.ok, status: res.status, data };
  }

  function errorText(data, status) {
    if (status === 429) return "Too many requests. Please wait a few minutes and try again.";
    const detail = data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((d) => d.msg).join("; ");
    return `Something went wrong (error ${status}).`;
  }

  function toast(message) {
    document.querySelector(".toast")?.remove();
    const el = Object.assign(document.createElement("div"), { className: "toast", textContent: message });
    el.setAttribute("role", "status");
    document.body.append(el);
    setTimeout(() => el.remove(), 3000);
  }

  // Shows a spinner on a button while `work` runs.
  async function busy(button, label, work) {
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner" aria-hidden="true"></span>${esc(label)}`;
    try { return await work(); } finally { button.disabled = false; button.innerHTML = original; }
  }

  // ---------- result view ----------

  function ring(score) {
    const r = 52, c = 2 * Math.PI * r;
    return `<div class="ring" role="img" aria-label="Risk score ${score} out of 100">
      <svg width="120" height="120" viewBox="0 0 120 120">
        <circle class="track" cx="60" cy="60" r="${r}" fill="none" stroke-width="12"/>
        <circle class="value" cx="60" cy="60" r="${r}" fill="none" stroke-width="12"
          stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - score / 100)}" data-full="${c}"/>
      </svg>
      <div class="label"><div><div class="num" data-count="${score}">${score}</div><div class="of">out of 100</div></div></div>
    </div>`;
  }

  // The markup already shows the final score; animation only replays it from zero. If the tab is
  // in the background (no animation frames), the correct value is still on screen.
  function animate(container) {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    container.querySelectorAll(".ring .value").forEach((el) => {
      const target = el.getAttribute("stroke-dashoffset");
      el.style.transition = "none";
      el.style.strokeDashoffset = el.dataset.full;
      el.getBoundingClientRect(); // apply the empty ring before transitioning to the score
      el.style.transition = "";
      el.style.strokeDashoffset = target;
    });
    container.querySelectorAll("[data-count]").forEach((el) => {
      const target = Number(el.dataset.count), start = performance.now();
      const tick = (now) => {
        const t = Math.min(1, (now - start) / 900);
        el.textContent = Math.round(target * (1 - Math.pow(1 - t, 3)));
        if (t < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }

  // Identifiers in the result that the student can report with one click.
  function reportTargets(data) {
    const found = new Map();
    for (const check of data.checks) {
      const d = check.details || {};
      if (check.check === "payment_request") {
        (d.upi_ids || []).forEach((v) => found.set(`upi:${v}`, ["upi", v]));
        (d.phones || []).forEach((v) => found.set(`phone:${v}`, ["phone", v]));
      }
      if (check.check === "recruiter_identity" && d.email && check.signals.some((s) => s.points > 0)) {
        found.set(`email:${d.email}`, ["email", d.email]);
      }
    }
    return [...found.values()].slice(0, 4);
  }

  const KIND_LABEL = { upi: "UPI ID", phone: "number", email: "email", domain: "website" };

  function flagList(items, good) {
    return `<ul class="flags">${items.map((f) => `<li class="${good ? "good" : ""}">
      <span class="pts">${f.points > 0 ? "+" : ""}${f.points}</span><span class="msg">${esc(f.message)}</span></li>`).join("")}</ul>`;
  }

  function renderResult(container, data, extraHtml = "") {
    const targets = data.level === "low" ? [] : reportTargets(data);
    container.innerHTML = `<section class="result lvl-${data.level}" aria-live="polite">
      <div class="result-head">
        ${ring(data.score)}
        <div class="verdict">
          <div class="level">${LEVEL_TEXT[data.level]}</div>
          <p>${esc(data.verdict)}</p>
        </div>
      </div>
      <div class="result-grid">
        <div class="card">
          <h3>Why we think so</h3>
          ${data.red_flags.length ? flagList(data.red_flags, false) : '<p class="muted">No red flags found.</p>'}
          ${data.good_signs.length ? `<h3 style="margin-top:14px">Good signs</h3>${flagList(data.good_signs, true)}` : ""}
        </div>
        <div class="card">
          <h3>What to do next</h3>
          <ul class="next">${NEXT_STEPS[data.level].map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
          ${targets.length ? `<p class="small muted" style="margin-top:12px">Warn other students: report what you found.</p>
            <div class="report-actions">${targets.map(([kind, value]) =>
              `<a class="btn btn-ghost" href="/report#kind=${kind}&value=${encodeURIComponent(value)}">🚩 Report ${KIND_LABEL[kind]} ${esc(value)}</a>`).join("")}</div>` : ""}
        </div>
      </div>
      ${extraHtml}
    </section>`;
    animate(container);
    container.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // 5-step bar showing how far a chat has progressed through the scam script.
  function stageStepper(furthest) {
    const reached = furthest ? STAGES[furthest][0] : 0;
    return `<div class="stepper" aria-label="Scam stage ${reached} of 5">${Object.values(STAGES).map(([n, label]) =>
      `<div class="step ${n <= reached ? "done" : ""} ${n >= 4 ? "danger" : ""}"><div class="bar"></div><span>${label}</span></div>`).join("")}</div>`;
  }

  function stageTag(stage) {
    if (!stage) return '<span class="tag">—</span>';
    const [n, label] = STAGES[stage];
    return `<span class="tag s${n}">${n}. ${label}</span>`;
  }

  // Click-or-drop file picker. onFile(file) is called with the chosen file.
  function dropzone(zone, onFile) {
    const input = zone.querySelector("input[type=file]");
    zone.addEventListener("click", (e) => { if (e.target !== input) input.click(); });
    zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    input.addEventListener("change", () => input.files[0] && onFile(input.files[0]));
    ["dragenter", "dragover"].forEach((type) => zone.addEventListener(type, (e) => { e.preventDefault(); zone.classList.add("over"); }));
    ["dragleave", "drop"].forEach((type) => zone.addEventListener(type, () => zone.classList.remove("over")));
    zone.addEventListener("drop", (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) onFile(f); });
  }

  // Reads "#key=value&key2=value2" and clears it from the address bar.
  function takeHashParams() {
    if (!location.hash.includes("=")) return {};
    const params = Object.fromEntries(new URLSearchParams(location.hash.slice(1)));
    history.replaceState(null, "", location.pathname);
    return params;
  }

  renderChrome();
  window.JSS = { esc, api, errorText, toast, busy, renderResult, stageStepper, stageTag, dropzone, takeHashParams, STAGES };
})();
