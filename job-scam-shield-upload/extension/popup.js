const ext = globalThis.browser ?? globalThis.chrome; // Firefox exposes `browser`, Chromium `chrome`
const DEFAULTS = { serverUrl: "http://127.0.0.1:8000", gmailAutoScan: false };
const MAX_TEXT = 50000;
const $ = (id) => document.getElementById(id);

function show(response) {
  $("result").replaceChildren(JobScamShield.renderCard(response));
}

async function analyze(text, button) {
  if (!text.trim()) {
    show({ ok: false, error: "Nothing to check. Paste a message or select text on the page first." });
    return;
  }
  button.disabled = true;
  show({ pending: true });
  const response = await ext.runtime.sendMessage({ type: "analyze", payload: { text } });
  show(response);
  button.disabled = false;
}

// Runs a function in the current tab. Fails on pages that block extensions (browser pages, stores).
async function runInTab(func) {
  const [tab] = await ext.tabs.query({ active: true, currentWindow: true });
  const [{ result }] = await ext.scripting.executeScript({ target: { tabId: tab.id }, func });
  return result;
}

$("checkText").addEventListener("click", () => analyze($("text").value, $("checkText")));

$("checkPage").addEventListener("click", async () => {
  let text;
  try {
    text = await runInTab(() => document.body.innerText);
  } catch {
    show({ ok: false, error: "This page doesn't allow extensions to read it." });
    return;
  }
  analyze((text || "").slice(0, MAX_TEXT), $("checkPage"));
});

$("save").addEventListener("click", async () => {
  let url;
  try {
    url = new URL($("serverUrl").value.trim() || DEFAULTS.serverUrl);
  } catch {
    $("saved").textContent = "That server address isn't a valid URL.";
    return;
  }
  // The default local server is allowed in the manifest; any other server needs permission.
  const origin = `${url.protocol}//${url.host}/*`;
  if (!(await ext.permissions.contains({ origins: [origin] }))) {
    const granted = await ext.permissions.request({ origins: [origin] });
    if (!granted) {
      $("saved").textContent = "Permission to contact that server was not granted.";
      return;
    }
  }
  await ext.storage.sync.set({
    serverUrl: url.origin,
    gmailAutoScan: $("gmailAutoScan").checked,
  });
  $("serverUrl").value = url.origin;
  $("saved").textContent = "Saved.";
});

(async () => {
  const settings = await ext.storage.sync.get(DEFAULTS);
  $("serverUrl").value = settings.serverUrl;
  $("gmailAutoScan").checked = settings.gmailAutoScan;
  try {
    const selection = await runInTab(() => window.getSelection().toString());
    if (selection?.trim()) $("text").value = selection.slice(0, MAX_TEXT);
  } catch {
    // No access to this tab: the user can still paste text.
  }
})();
