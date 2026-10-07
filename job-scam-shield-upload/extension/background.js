// Background script: talks to the Job Scam Shield server and handles the right-click menu.
// Content scripts can't call the server directly (page CORS rules), so they message us.
// Runs as a service worker in Chrome/Brave/Edge/Opera and as an event page in Firefox.

const ext = globalThis.browser ?? globalThis.chrome; // Firefox exposes `browser`, Chromium `chrome`

const DEFAULTS = { serverUrl: "http://127.0.0.1:8000", gmailAutoScan: false };
const MAX_TEXT = 50000;
const MENU_ID = "jss-check-selection";

async function getSettings() {
  return { ...DEFAULTS, ...(await ext.storage.sync.get(DEFAULTS)) };
}

async function analyze(payload) {
  const { serverUrl } = await getSettings();
  const body = { online: true, ...payload, text: (payload.text || "").slice(0, MAX_TEXT) };
  let res;
  try {
    res = await fetch(`${serverUrl}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(`Can't reach the Job Scam Shield server at ${serverUrl}. Is it running?`);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok || !data) {
    throw new Error(data?.detail ? `Server rejected the request: ${JSON.stringify(data.detail)}` : `Server error ${res.status}`);
  }
  return data;
}

async function respond(payload) {
  try {
    return { ok: true, result: await analyze(payload) };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

ext.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "analyze") {
    respond(message.payload).then(sendResponse);
    return true; // keep the channel open for the async response
  }
  return false;
});

ext.runtime.onInstalled.addListener(() => {
  ext.contextMenus.create({ id: MENU_ID, title: "Check for job scam", contexts: ["selection"] });
});

ext.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID || !tab?.id) return;
  const response = await respond({ text: info.selectionText || "" });
  try {
    await ext.scripting.executeScript({ target: { tabId: tab.id }, files: ["render.js"] });
    await ext.scripting.executeScript({
      target: { tabId: tab.id },
      func: (r) => window.JobScamShield.showToast(r),
      args: [response],
    });
  } catch (e) {
    // Browser pages (chrome://, about:) and extension stores don't allow scripts; nothing to show there.
    console.warn("Job Scam Shield: can't show the result on this page.", e);
  }
});
