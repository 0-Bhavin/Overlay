/**
 * AI Overlay — Background Service Worker
 * Maintains WebSocket bridge to Python desktop application on ws://localhost:8765.
 * Note: WebSocket has no authentication per architectural decision (localhost only).
 */

const WS_URL = 'ws://127.0.0.1:8765';
let socket = null;
let reconnectTimer = null;

// ---------------------------------------------------------------------------
// Tab tracking — remember the last real content-script tab so requests still
// work when the PyQt overlay window has OS focus (Chrome is not foreground).
// ---------------------------------------------------------------------------
let lastKnownTabId = null;

/**
 * Update the cached tab from any source that gives us a confirmed tab ID.
 * @param {number} tabId
 * @param {string|undefined} url
 */
function recordTabId(tabId, url) {
  if (!tabId) return;
  // Only cache real web pages (ignore chrome:// and extension pages).
  if (url && (url.startsWith('chrome://') || url.startsWith('chrome-extension://'))) return;
  lastKnownTabId = tabId;
}

// Also track via the tabs API — fires when the user switches tabs in Chrome,
// giving us the tab ID *before* the PyQt overlay ever steals OS focus.
chrome.tabs.onActivated.addListener((activeInfo) => {
  chrome.tabs.get(activeInfo.tabId, (tab) => {
    if (!chrome.runtime.lastError && tab) {
      recordTabId(tab.id, tab.url);
    }
  });
});

function connectWebSocket() {
  if (socket && (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN)) {
    return;
  }

  try {
    socket = new WebSocket(WS_URL);

    socket.onopen = () => {
      console.log('[AI Overlay Extension] Connected to desktop bridge server');
      if (reconnectTimer) {
        clearInterval(reconnectTimer);
        reconnectTimer = null;
      }
    };

    socket.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data);

        // ── DOM tree (existing) ────────────────────────────────────
        if (msg.type === 'get_tree') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            const response = await sendMessageWithInject(tab.id, { action: 'GET_TREE' });
            const tree = (response && response.tree) ? response.tree : [];
            sendToBridge({ type: 'tree_response', req_id: msg.req_id, tree: tree });
          } else {
            sendToBridge({ type: 'tree_response', req_id: msg.req_id, tree: [] });
          }

        // ── DOM-based highlight (existing) ─────────────────────────
        } else if (msg.type === 'highlight') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            const response = await sendMessageWithInject(tab.id, { action: 'HIGHLIGHT', elementId: msg.elementId });
            sendToBridge({
              type: 'highlight_response',
              req_id: msg.req_id,
              success: !!(response && response.status === 'ok')
            });
          }

        // ── Viewport geometry (new — for WebResolver coord conversion) ──
        } else if (msg.type === 'get_viewport_info') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            const response = await sendMessageWithInject(tab.id, { action: 'GET_VIEWPORT_INFO' });
            if (!response || response.status !== 'ok') {
              sendToBridge({ type: 'get_viewport_info', req_id: msg.req_id, screenX: 0, screenY: 0, screenLeft: 0, screenTop: 0, outerWidth: 0, outerHeight: 0, innerWidth: 0, innerHeight: 0, devicePixelRatio: 1 });
            } else {
              sendToBridge({
                type: 'get_viewport_info',
                req_id: msg.req_id,
                screenX:          response.screenX,
                screenY:          response.screenY,
                screenLeft:       response.screenLeft,
                screenTop:        response.screenTop,
                outerWidth:       response.outerWidth,
                outerHeight:      response.outerHeight,
                innerWidth:       response.innerWidth,
                innerHeight:      response.innerHeight,
                devicePixelRatio: response.devicePixelRatio,
              });
            }
          } else {
            sendToBridge({ type: 'get_viewport_info', req_id: msg.req_id, screenX: 0, screenY: 0, screenLeft: 0, screenTop: 0, outerWidth: 0, outerHeight: 0, innerWidth: 0, innerHeight: 0, devicePixelRatio: 1 });
          }

        // ── Live element resolution (new — for WebResolver) ────────
        } else if (msg.type === 'resolve_element') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            const response = await sendMessageWithInject(
              tab.id,
              { action: 'RESOLVE_ELEMENT', selector: msg.selector, targetName: msg.targetName }
            );
            if (!response) {
              sendToBridge({ type: 'resolve_element', req_id: msg.req_id, found: false, elementId: null, rect: null, resolvedBy: 'none' });
            } else {
              sendToBridge({
                type: 'resolve_element',
                req_id:      msg.req_id,
                found:       response.found      || false,
                elementId:   response.elementId  || null,
                rect:        response.rect        || null,
                resolvedBy:  response.resolvedBy  || 'none',
              });
            }
          } else {
            sendToBridge({ type: 'resolve_element', req_id: msg.req_id, found: false, elementId: null, rect: null, resolvedBy: 'none' });
          }
        }

      } catch (err) {
        console.error('[AI Overlay Extension] Error processing bridge message:', err);
      }
    };

    socket.onclose = () => {
      scheduleReconnect();
    };

    socket.onerror = () => {
      socket.close();
    };
  } catch (err) {
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (!reconnectTimer) {
    reconnectTimer = setInterval(connectWebSocket, 3000);
  }
}

function sendToBridge(data) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(data));
  }
}

/**
 * Send a message to a tab's content script, injecting the scripts first if
 * the content script isn't loaded (e.g. after extension reload without tab refresh).
 * @param {number} tabId
 * @param {object} message
 * @returns {Promise<object|null>}  The response, or null on failure.
 */
async function sendMessageWithInject(tabId, message) {
  // First attempt — content script may already be loaded.
  try {
    return await new Promise((resolve, reject) => {
      chrome.tabs.sendMessage(tabId, message, (response) => {
        if (chrome.runtime.lastError) reject(chrome.runtime.lastError);
        else resolve(response);
      });
    });
  } catch (firstErr) {
    const msg = firstErr.message || '';
    // Only attempt injection if the error is a connection problem.
    const isConnErr = msg.includes('Could not establish connection') ||
                      msg.includes('Receiving end does not exist') ||
                      msg.includes('No tab with id');
    if (!isConnErr) return null;

    // Inject the content scripts programmatically and retry once.
    console.log('[AI Overlay Extension] Content script missing on tab', tabId, '— injecting...');
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ['dom_extractor.js', 'content.js'],
      });
    } catch (injectErr) {
      console.warn('[AI Overlay Extension] Script injection failed:', injectErr.message);
      return null;
    }

    // Retry the message after injection.
    try {
      return await new Promise((resolve, reject) => {
        chrome.tabs.sendMessage(tabId, message, (response) => {
          if (chrome.runtime.lastError) reject(chrome.runtime.lastError);
          else resolve(response);
        });
      });
    } catch (retryErr) {
      console.warn('[AI Overlay Extension] Retry after inject failed:', retryErr.message);
      return null;
    }
  }
}

async function getActiveTab() {
  // 1. Prefer the last tab we heard from — this keeps working even when the
  //    PyQt overlay window has OS focus and Chrome is not in the foreground.
  if (lastKnownTabId !== null) {
    try {
      const tab = await chrome.tabs.get(lastKnownTabId);
      if (tab && tab.url && (tab.url.startsWith('http://') || tab.url.startsWith('https://'))) {
        return tab;
      }
    } catch (_) {
      // Tab was closed; clear the cache and fall through to the query chain.
      lastKnownTabId = null;
    }
  }

  try {
    // 2. Try lastFocusedWindow (works when Chrome still has OS focus)
    let tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tabs && tabs.length > 0 && tabs[0].url && !tabs[0].url.startsWith('chrome://')) {
      recordTabId(tabs[0].id, tabs[0].url);
      return tabs[0];
    }

    // 3. Try active tab in any window (e.g. when PyQt app has OS focus)
    tabs = await chrome.tabs.query({ active: true });
    if (tabs && tabs.length > 0) {
      const httpTab = tabs.find(t => t.url && (t.url.startsWith('http://') || t.url.startsWith('https://')));
      if (httpTab) { recordTabId(httpTab.id, httpTab.url); return httpTab; }
      return tabs[0];
    }

    // 4. Last resort — any open http/https tab
    tabs = await chrome.tabs.query({});
    if (tabs && tabs.length > 0) {
      const webTab = tabs.find(t => t.url && (t.url.startsWith('http://') || t.url.startsWith('https://')));
      if (webTab) { recordTabId(webTab.id, webTab.url); return webTab; }
      return tabs[0];
    }
  } catch (err) {
    console.error('[AI Overlay Extension] Error querying active tab:', err);
  }
  return null;
}

// ---------------------------------------------------------------------------
// Forward content script messages to desktop bridge
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender) => {
  // Keep the tab cache warm from every content-script message.
  if (sender && sender.tab) recordTabId(sender.tab.id, sender.tab.url);
  if (message.action === 'USER_CLICK') {
    // Forward as web_action_detected so ActionWatcher's web callback fires.
    // Also keep the legacy user_click type for backward compatibility.
    sendToBridge({ type: 'user_click',           elementId: message.elementId, url: message.url });
    sendToBridge({ type: 'web_action_detected',  elementId: message.elementId, url: message.url });

  } else if (message.action === 'DOM_MUTATED') {
    sendToBridge({ type: 'dom_mutated', url: message.url });
  }
});

// Initial connection
connectWebSocket();
