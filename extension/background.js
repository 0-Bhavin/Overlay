/**
 * AI Overlay — Background Service Worker
 * Maintains WebSocket bridge to Python desktop application on ws://localhost:8765.
 * Forwards GET_TREE requests to the active tab's content script, which handles
 * extraction (standard DOM for normal sites, shadow-DOM for Google Sheets).
 */

const WS_URL = 'ws://127.0.0.1:8765';
let socket = null;
let reconnectTimer = null;

function connectWebSocket() {
  console.log('[AI Overlay Extension] 🚀 Attempting WebSocket connection to', WS_URL);
  console.log('[AI Overlay Extension] Service worker is running:', self.serviceWorker.state);

  if (socket && (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN)) {
    console.log('[AI Overlay Extension] Socket already exists, readyState:', socket.readyState);
    return;
  }

  try {
    // Test if we can even create a WebSocket
    if (typeof WebSocket === 'undefined') {
      console.error('[AI Overlay Extension] WebSocket API is not available!');
      return;
    }

    socket = new WebSocket(WS_URL);

    console.log('[AI Overlay Extension] WebSocket instance created, readyState:', socket.readyState);
    console.log('[AI Overlay Extension] WebSocket URL:', socket.url);
    console.log('[AI Overlay Extension] WebSocket protocol:', socket.protocol);

    socket.onopen = () => {
      console.log('[AI Overlay Extension] ✅ Connected to desktop bridge server');
      console.log('[AI Overlay Extension] WebSocket readyState after open:', socket.readyState);
      if (reconnectTimer) {
        clearInterval(reconnectTimer);
        reconnectTimer = null;
      }
    };

    socket.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.action === 'GET_TREE') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            try {
              const response = await sendToTabWithFallback(tab.id, { action: 'GET_TREE' });
              sendToBridge({
                type: 'tree_response',
                req_id: msg.req_id,
                tree: (response && response.tree) ? response.tree : [],
                viewportOffset: (response && response.viewportOffset) || { x: 0, y: 0 },
              });
            } catch (err) {
              console.error('[BG] get_tree error:', err.message);
              sendToBridge({ type: 'tree_response', req_id: msg.req_id, tree: [], viewportOffset: { x: 0, y: 0 } });
            }
          } else {
            console.warn('[BG] No active web tab found for get_tree');
            sendToBridge({ type: 'tree_response', req_id: msg.req_id, tree: [], viewportOffset: { x: 0, y: 0 } });
          }
        } else if (msg.action === 'HIGHLIGHT') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            try {
              const payload = {
                action: 'HIGHLIGHT',
                elementId: msg.elementId,
                target: msg.target || '',
                tooltip: msg.tooltip || '',
              };
              const response = await sendToTabWithFallback(tab.id, payload);
              sendToBridge({ type: 'highlight_response', req_id: msg.req_id, success: Boolean(response && response.status === 'ok') });
            } catch (err) {
              console.error('[BG] highlight error:', err.message);
              sendToBridge({ type: 'highlight_response', req_id: msg.req_id, success: false });
            }
          } else {
            sendToBridge({ type: 'highlight_response', req_id: msg.req_id, success: false });
          }
        } else if (msg.type === 'clear_overlay') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            try {
              await sendToTabWithFallback(tab.id, { action: 'CLEAR_HIGHLIGHT' });
              sendToBridge({ type: 'clear_overlay_response', req_id: msg.req_id, success: true });
            } catch (err) {
              sendToBridge({ type: 'clear_overlay_response', req_id: msg.req_id, success: false });
            }
          } else {
            sendToBridge({ type: 'clear_overlay_response', req_id: msg.req_id, success: true });
          }
        }
      } catch (err) {
        console.error('[AI Overlay Extension] Error:', err);
      }
    };

    socket.onclose = (event) => {
      console.log('[AI Overlay Extension] WebSocket closed:', event.code, event.reason);
      scheduleReconnect();
    };

    socket.onerror = (error) => {
      console.error('[AI Overlay Extension] WebSocket error:', error);
      // Don't close() here - let onclose handle it
    };
  } catch (err) {
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (!reconnectTimer) reconnectTimer = setInterval(connectWebSocket, 3000);
}

function sendToBridge(data) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(data));
}

async function sendToTabWithFallback(tabId, payload) {
  try {
    return await chrome.tabs.sendMessage(tabId, payload);
  } catch (err) {
    console.log('[BG] sendMessage initial failure, trying injection into tab:', tabId, err.message);
    try {
      if (chrome.scripting) {
        await chrome.scripting.executeScript({
          target: { tabId: tabId },
          files: ['dom_extractor.js', 'content.js'],
        });
        await new Promise((r) => setTimeout(r, 150));
        return await chrome.tabs.sendMessage(tabId, payload);
      }
    } catch (injectErr) {
      console.error('[BG] Content script injection failed:', injectErr);
    }
    throw err;
  }
}

async function getActiveTab() {
  try {
    // 1. Try active tab in last focused window
    const [focusedTab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (focusedTab && focusedTab.id && isValidWebUrl(focusedTab.url)) {
      return focusedTab;
    }

    // 2. Try all active tabs across all normal windows
    const activeTabs = await chrome.tabs.query({ active: true });
    for (const t of activeTabs) {
      if (t.id && isValidWebUrl(t.url)) {
        return t;
      }
    }

    // 3. Fallback: all tabs search for web URL
    const allTabs = await chrome.tabs.query({});
    for (const t of allTabs) {
      if (t.id && isValidWebUrl(t.url)) {
        return t;
      }
    }

    return activeTabs[0] || null;
  } catch (err) {
    console.error('[BG] getActiveTab error:', err);
    return null;
  }
}

function isValidWebUrl(url) {
  if (!url) return false;
  return !url.startsWith('chrome://') && !url.startsWith('chrome-extension://') && !url.startsWith('devtools://');
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.action === 'USER_CLICK') {
    sendToBridge({ type: 'user_click', elementId: message.elementId, targetText: message.targetText || '', url: message.url });
  } else if (message.action === 'DOM_MUTATED') {
    sendToBridge({ type: 'dom_mutated', url: message.url });
  }
});

connectWebSocket();
