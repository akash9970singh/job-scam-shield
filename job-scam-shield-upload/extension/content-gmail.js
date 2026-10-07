// Gmail: when auto-scan is on, check each opened email and show a banner above
// suspicious ones. Low-risk emails get no banner, to avoid noise.
// Gmail's markup isn't a public API: div.a3s = message body, div.adn = one message in a
// thread, span.gD[email] = sender, h2.hP = subject. Update these if Gmail changes them.
(() => {
  const ext = globalThis.browser ?? globalThis.chrome; // Firefox exposes `browser`, Chromium `chrome`
  const MAX_TEXT = 50000;
  const SCAN_DELAY_MS = 600;
  let enabled = false;
  let timer = null;
  let serverErrorShown = false;

  ext.storage.sync.get({ gmailAutoScan: false }).then((s) => {
    enabled = s.gmailAutoScan;
    if (enabled) schedule();
  });
  ext.storage.onChanged.addListener((changes) => {
    if (!changes.gmailAutoScan) return;
    enabled = changes.gmailAutoScan.newValue;
    if (enabled) schedule();
  });

  new MutationObserver(() => {
    if (enabled) schedule();
  }).observe(document.body, { childList: true, subtree: true });

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(scan, SCAN_DELAY_MS);
  }

  function scan() {
    for (const body of document.querySelectorAll("div.a3s")) {
      if (body.dataset.jssScanned || !body.innerText.trim()) continue;
      body.dataset.jssScanned = "1";
      checkMessage(body);
    }
  }

  async function checkMessage(body) {
    const message = body.closest("div.adn") || document;
    const sender = message.querySelector("span.gD[email]")?.getAttribute("email") || null;
    const subject = document.querySelector("h2.hP")?.innerText || "";
    const text = `${subject}\n\n${body.innerText}`.slice(0, MAX_TEXT);

    const slot = JobScamShield.renderCard({ pending: true });
    slot.style.margin = "0 0 12px";
    body.before(slot);

    let response;
    try {
      response = await ext.runtime.sendMessage({ type: "analyze", payload: { text, sender_email: sender } });
    } catch {
      response = { ok: false, error: "The extension was reloaded. Refresh Gmail to scan again." };
    }
    const quiet = response.ok ? response.result.level === "low" : serverErrorShown;
    if (quiet) {
      slot.remove();
      return;
    }
    if (!response.ok) serverErrorShown = true; // say it once, not on every email
    const card = JobScamShield.renderCard(response, { onClose: () => card.remove() });
    card.style.margin = "0 0 12px";
    slot.replaceWith(card);
  }
})();
