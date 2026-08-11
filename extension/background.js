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
        if (msg.type === 'get_tree') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            chrome.tabs.sendMessage(tab.id, { action: 'GET_TREE' }, (response) => {
              const tree = (response && response.tree) ? response.tree : [];
              sendToBridge({ type: 'tree_response', req_id: msg.req_id, tree: tree });
            });
          } else {
            sendToBridge({ type: 'tree_response', req_id: msg.req_id, tree: [] });
          }
        } else if (msg.type === 'highlight') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            chrome.tabs.sendMessage(tab.id, { action: 'HIGHLIGHT', elementId: msg.elementId }, (response) => {
              sendToBridge({ type: 'highlight_response', req_id: msg.req_id, success: response && response.status === 'ok' });
            });
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
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

// Forward content script messages to desktop bridge
chrome.runtime.onMessage.addListener((message) => {
  if (message.action === 'USER_CLICK') {
    sendToBridge({ type: 'user_click', elementId: message.elementId, url: message.url });
  } else if (message.action === 'DOM_MUTATED') {
    sendToBridge({ type: 'dom_mutated', url: message.url });
  }
});

// Initial connection
connectWebSocket();
