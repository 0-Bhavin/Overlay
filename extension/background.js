/**
 * AI Overlay — Background Service Worker
 * Maintains WebSocket bridge to Python desktop application on ws://localhost:8765.
 * Note: WebSocket has no authentication per architectural decision (localhost only).
 */

const WS_URL = 'ws://127.0.0.1:8765';
let socket = null;
let reconnectTimer = null;

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
            chrome.tabs.sendMessage(tab.id, { action: 'GET_TREE' }, (response) => {
              if (chrome.runtime.lastError) {
                console.warn('[AI Overlay Extension] GET_TREE message error:', chrome.runtime.lastError.message);
                sendToBridge({ type: 'tree_response', req_id: msg.req_id, tree: [] });
                return;
              }
              const tree = (response && response.tree) ? response.tree : [];
              sendToBridge({ type: 'tree_response', req_id: msg.req_id, tree: tree });
            });
          } else {
            sendToBridge({ type: 'tree_response', req_id: msg.req_id, tree: [] });
          }

        // ── DOM-based highlight (existing) ─────────────────────────
        } else if (msg.type === 'highlight') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            chrome.tabs.sendMessage(tab.id, { action: 'HIGHLIGHT', elementId: msg.elementId }, (response) => {
              if (chrome.runtime.lastError) {
                sendToBridge({ type: 'highlight_response', req_id: msg.req_id, success: false });
                return;
              }
              sendToBridge({
                type: 'highlight_response',
                req_id: msg.req_id,
                success: response && response.status === 'ok'
              });
            });
          }

        // ── Viewport geometry (new — for WebResolver coord conversion) ──
        } else if (msg.type === 'get_viewport_info') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            chrome.tabs.sendMessage(tab.id, { action: 'GET_VIEWPORT_INFO' }, (response) => {
              if (chrome.runtime.lastError || !response || response.status !== 'ok') {
                sendToBridge({ type: 'get_viewport_info', req_id: msg.req_id, screenX: 0, screenY: 0, outerWidth: 0, outerHeight: 0, innerWidth: 0, innerHeight: 0 });
                return;
              }
              sendToBridge({
                type: 'get_viewport_info',
                req_id: msg.req_id,
                screenX:     response.screenX,
                screenY:     response.screenY,
                outerWidth:  response.outerWidth,
                outerHeight: response.outerHeight,
                innerWidth:  response.innerWidth,
                innerHeight: response.innerHeight,
              });
            });
          } else {
            sendToBridge({ type: 'get_viewport_info', req_id: msg.req_id, screenX: 0, screenY: 0, outerWidth: 0, outerHeight: 0, innerWidth: 0, innerHeight: 0 });
          }

        // ── Live element resolution (new — for WebResolver) ────────
        } else if (msg.type === 'resolve_element') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            chrome.tabs.sendMessage(
              tab.id,
              { action: 'RESOLVE_ELEMENT', selector: msg.selector, targetName: msg.targetName },
              (response) => {
                if (chrome.runtime.lastError || !response) {
                  sendToBridge({ type: 'resolve_element', req_id: msg.req_id, found: false, elementId: null, rect: null, resolvedBy: 'none' });
                  return;
                }
                sendToBridge({
                  type: 'resolve_element',
                  req_id:      msg.req_id,
                  found:       response.found       || false,
                  elementId:   response.elementId  || null,
                  rect:        response.rect        || null,
                  resolvedBy:  response.resolvedBy  || 'none',
                });
              }
            );
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

async function getActiveTab() {
  try {
    // 1. Try lastFocusedWindow (active tab in last focused Chrome window)
    let tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tabs && tabs.length > 0 && tabs[0].url && !tabs[0].url.startsWith('chrome://')) {
      return tabs[0];
    }

    // 2. Try active tab in any window (e.g. when PyQt app has OS focus)
    tabs = await chrome.tabs.query({ active: true });
    if (tabs && tabs.length > 0) {
      const httpTab = tabs.find(t => t.url && (t.url.startsWith('http://') || t.url.startsWith('https://')));
      if (httpTab) return httpTab;
      return tabs[0];
    }

    // 3. Fallback to any http/https tab
    tabs = await chrome.tabs.query({});
    if (tabs && tabs.length > 0) {
      const webTab = tabs.find(t => t.url && (t.url.startsWith('http://') || t.url.startsWith('https://')));
      if (webTab) return webTab;
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

chrome.runtime.onMessage.addListener((message) => {
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
