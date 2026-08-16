/**
 * AI Overlay — Content Script
 * Manages DOM extraction, element highlighting, click detection, mutation tracking,
 * viewport geometry reporting, and live element resolution for the WebResolver.
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

  // ---------------------------------------------------------------------------
  // Live element resolution — used by WebResolver via resolve_element message
  // ---------------------------------------------------------------------------

  /**
   * Locate an element using a priority chain of selector strategies, assign
   * a fresh data-ai-overlay-id, and return a live getBoundingClientRect().
   *
   * Priority: id → name → data-testid → aria-label → css_selector → xpath
   *
   * @param {Object} selector  The web_element descriptor from the Step.
   * @returns {{ found: boolean, elementId: string|null, rect: DOMRect|null, resolvedBy: string }}
   */
  function resolveElement(selector) {
    let el = null;
    let resolvedBy = 'none';

    // 1. DOM id
    if (!el && selector.id != null && selector.id !== '') {
      const idStr = String(selector.id);
      el = document.getElementById(idStr);
      if (!el) {
        // Gemini sometimes produces numeric ids from dom_extractor.js — try data attr
        el = document.querySelector(`[data-ai-overlay-id="${idStr}"]`);
      }
      if (el) resolvedBy = 'id';
    }

    // 2. name attribute
    if (!el && selector.name) {
      el = document.querySelector(`[name="${CSS.escape(selector.name)}"]`);
      if (el) resolvedBy = 'name';
    }

    // 3. data-testid
    if (!el && selector.data_testid) {
      el = document.querySelector(`[data-testid="${CSS.escape(selector.data_testid)}"]`);
      if (el) resolvedBy = 'data-testid';
    }

    // 4. aria-label (exact)
    if (!el && selector.aria_label) {
      el = document.querySelector(`[aria-label="${CSS.escape(selector.aria_label)}"]`);
      if (el) resolvedBy = 'aria-label';
    }

    // 5. Text content match (for links/buttons with no id)
    if (!el && selector.text && selector.tag) {
      const needle = selector.text.trim().toLowerCase();
      const candidates = document.querySelectorAll(selector.tag);
      for (const c of candidates) {
        const txt = (c.textContent || c.innerText || '').trim().toLowerCase();
        if (txt === needle || txt.startsWith(needle)) {
          el = c;
          resolvedBy = 'text+tag';
          break;
        }
      }
    }

    // 6. CSS selector
    if (!el && selector.css_selector) {
      try {
        el = document.querySelector(selector.css_selector);
        if (el) resolvedBy = 'css_selector';
      } catch (_) { /* invalid selector */ }
    }

    // 7. XPath
    if (!el && selector.xpath) {
      try {
        const result = document.evaluate(
          selector.xpath, document, null,
          XPathResult.FIRST_ORDERED_NODE_TYPE, null
        );
        el = result.singleNodeValue;
        if (el) resolvedBy = 'xpath';
      } catch (_) { /* invalid xpath */ }
    }

    if (!el) {
      return { found: false, elementId: null, rect: null, resolvedBy: 'none' };
    }

    // Scroll into view so getBoundingClientRect() is accurate
    el.scrollIntoView({ behavior: 'instant', block: 'nearest' });

    // Assign / refresh the tracking id
    let elemId = el.getAttribute('data-ai-overlay-id');
    if (!elemId) {
      // Use a unique timestamp-based id to avoid collisions with dom_extractor
      elemId = 'aiov-' + Date.now();
      el.setAttribute('data-ai-overlay-id', elemId);
    }

    const rawRect = el.getBoundingClientRect();
    return {
      found: true,
      elementId: elemId,
      resolvedBy: resolvedBy,
      rect: {
        x:      Math.round(rawRect.x),
        y:      Math.round(rawRect.y),
        width:  Math.round(rawRect.width),
        height: Math.round(rawRect.height),
      }
    };
  }

  // ---------------------------------------------------------------------------
  // Message handlers
  // ---------------------------------------------------------------------------

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

    } else if (request.action === 'GET_VIEWPORT_INFO') {
      // Return live window geometry so WebResolver can convert DOM coords → screen coords.
      // outerHeight - innerHeight = browser chrome/toolbar height in CSS pixels.
      sendResponse({
        status: 'ok',
        screenX:     window.screenX,
        screenY:     window.screenY,
        outerWidth:  window.outerWidth,
        outerHeight: window.outerHeight,
        innerWidth:  window.innerWidth,
        innerHeight: window.innerHeight,
      });

    } else if (request.action === 'RESOLVE_ELEMENT') {
      // Locate element by priority chain and return live bbox.
      const result = resolveElement(request.selector || {});
      sendResponse({ status: result.found ? 'ok' : 'not_found', ...result });
    }

    return true; // Keep response channel open for async
  });

  // ---------------------------------------------------------------------------
  // Click detection — forward to background → Python bridge
  // ---------------------------------------------------------------------------

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

  // ---------------------------------------------------------------------------
  // MutationObserver — detect DOM changes (Level 3 adaptive behaviour)
  // ---------------------------------------------------------------------------

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
