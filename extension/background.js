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
            try {
              const response = await chrome.tabs.sendMessage(tab.id, { action: 'GET_TREE' });
              sendToBridge({
                type: 'tree_response',
                req_id: msg.req_id,
                tree: (response && response.tree) ? response.tree : [],
                viewportOffset: (response && response.viewportOffset) || { x: 0, y: 0 },
              });
            } catch (err) {
              console.error('[BG] tabs.sendMessage error:', err.message);
              sendToBridge({ type: 'tree_response', req_id: msg.req_id, tree: [], viewportOffset: { x: 0, y: 0 } });
            }
          } else {
            sendToBridge({ type: 'tree_response', req_id: msg.req_id, tree: [], viewportOffset: { x: 0, y: 0 } });
          }
        } else if (msg.type === 'highlight') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            try {
              // Forward tooltip text if provided
              const payload = { action: 'HIGHLIGHT', elementId: msg.elementId };
              if (msg.tooltip) {
                payload.tooltip = msg.tooltip;
              }
              await chrome.tabs.sendMessage(tab.id, payload);
              sendToBridge({ type: 'highlight_response', req_id: msg.req_id, success: true });
            } catch (err) {
              sendToBridge({ type: 'highlight_response', req_id: msg.req_id, success: false });
            }
          }
        } else if (msg.type === 'clear_overlay') {
          const tab = await getActiveTab();
          if (tab && tab.id) {
            try {
              await chrome.tabs.sendMessage(tab.id, { action: 'CLEAR_HIGHLIGHT' });
              sendToBridge({ type: 'clear_overlay_response', req_id: msg.req_id, success: true });
            } catch (err) {
              sendToBridge({ type: 'clear_overlay_response', req_id: msg.req_id, success: false });
            }
          }
        }
      } catch (err) {
        console.error('[AI Overlay Extension] Error:', err);
      }
    };

    socket.onclose = () => scheduleReconnect();
    socket.onerror = () => socket.close();
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

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.action === 'USER_CLICK') {
    sendToBridge({ type: 'user_click', elementId: message.elementId, url: message.url });
  } else if (message.action === 'DOM_MUTATED') {
    sendToBridge({ type: 'dom_mutated', url: message.url });
  }
});

connectWebSocket();
