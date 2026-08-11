/**
 * AI Overlay — Content Script
 * Manages DOM extraction, element highlighting, click detection, and mutation tracking.
 */

(function () {
  'use strict';

  let highlightOverlay = null;

  /**
   * Create or update the spotlight overlay on the target element.
   * @param {number|string} elementId
   */
  function highlightElement(elementId) {
    removeHighlight();

    const targetEl = document.querySelector(`[data-ai-overlay-id="${elementId}"]`);
    if (!targetEl) return false;

    const rect = targetEl.getBoundingClientRect();
    highlightOverlay = document.createElement('div');
    highlightOverlay.id = 'ai-overlay-spotlight-ring';
    highlightOverlay.style.cssText = `
      position: absolute;
      left: ${rect.left + window.scrollX - 4}px;
      top: ${rect.top + window.scrollY - 4}px;
      width: ${rect.width + 8}px;
      height: ${rect.height + 8}px;
      border: 3px solid #3b82f6;
      border-radius: 6px;
      box-shadow: 0 0 12px rgba(59, 130, 246, 0.8), inset 0 0 12px rgba(59, 130, 246, 0.2);
      pointer-events: none;
      z-index: 999999;
      transition: all 0.2s ease-in-out;
      animation: aiOverlayPulse 1.5s infinite;
    `;

    // Inject pulse keyframes if not already present
    if (!document.getElementById('ai-overlay-style')) {
      const style = document.createElement('style');
      style.id = 'ai-overlay-style';
      style.textContent = `
        @keyframes aiOverlayPulse {
          0% { box-shadow: 0 0 6px rgba(59, 130, 246, 0.6); }
          50% { box-shadow: 0 0 18px rgba(59, 130, 246, 1); }
          100% { box-shadow: 0 0 6px rgba(59, 130, 246, 0.6); }
        }
      `;
      document.head.appendChild(style);
    }

    document.body.appendChild(highlightOverlay);
    targetEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    return true;
  }

  /**
   * Remove current highlight overlay.
   */
  function removeHighlight() {
    if (highlightOverlay && highlightOverlay.parentNode) {
      highlightOverlay.parentNode.removeChild(highlightOverlay);
      highlightOverlay = null;
    }
  }

  // Handle messages from background service worker / extension
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'GET_TREE') {
      const tree = window.AIOverlayDOMExtractor ? window.AIOverlayDOMExtractor.extractSimplifiedDOM() : [];
      sendResponse({ status: 'ok', tree: tree, url: window.location.href });
    } else if (request.action === 'HIGHLIGHT') {
      const success = highlightElement(request.elementId);
      sendResponse({ status: success ? 'ok' : 'not_found' });
    } else if (request.action === 'CLEAR_HIGHLIGHT') {
      removeHighlight();
      sendResponse({ status: 'ok' });
    }
    return true; // Keep response channel open for async
  });

  // Track user clicks to send event back to background
  document.addEventListener('click', (event) => {
    const target = event.target.closest('[data-ai-overlay-id]');
    const clickedId = target ? target.getAttribute('data-ai-overlay-id') : null;
    chrome.runtime.sendMessage({
      action: 'USER_CLICK',
      elementId: clickedId,
      tagName: event.target.tagName,
      url: window.location.href
    }).catch(() => {});
  }, true);

  // Set up MutationObserver to detect DOM changes (Level 3 adaptive behavior)
  let mutationTimeout = null;
  const observer = new MutationObserver(() => {
    if (mutationTimeout) clearTimeout(mutationTimeout);
    mutationTimeout = setTimeout(() => {
      chrome.runtime.sendMessage({
        action: 'DOM_MUTATED',
        url: window.location.href
      }).catch(() => {});
    }, 300);
  });

  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
  }

})();
