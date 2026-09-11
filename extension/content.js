/**
 * AI Overlay — Content Script
 * Manages DOM extraction, element highlighting, click detection, and mutation tracking.
 * Handles both standard websites and canvas-based apps like Google Sheets.
 */

(function () {
  'use strict';

  let highlightOverlay = null;
  let dimOverlay = null;
  let tooltipOverlay = null;

  // ─── Element extraction ─────────────────────────────────────────────────────

  /**
   * Get the viewport offset: top-left corner of the browser content area in screen coords.
   * Formula: screenX + (outerWidth - innerWidth), screenY + (outerHeight - innerHeight)
   * This accounts for the browser chrome (toolbar, sidebar, etc.) around the content area.
   */
  function getViewportOffset() {
    return {
      x: window.screenX + window.outerWidth - window.innerWidth,
      y: window.screenY + window.outerHeight - window.innerHeight,
    };
  }

  /**
   * Extract interactive elements from the standard DOM.
   * Used for regular websites.
   */
  function extractFromDOM() {
    if (!window.AIOverlayDOMExtractor) return [];
    return window.AIOverlayDOMExtractor.extractSimplifiedDOM();
  }

  /**
   * Extract elements from Google Sheets' shadow-DOM canvas toolbar.
   * Google Sheets renders its toolbar on a canvas element, but the interactive
   * elements (Format, Bold, etc.) ARE in the DOM — they live inside a shadow root
   * attached to the <waffle-iron> custom element.
   */
  function extractFromGoogleSheets() {
    const nodes = [];
    let idCounter = 1;

    // The toolbar host: <waffle-iron> holds the shadow DOM with the toolbar buttons
    const waffleIron = document.querySelector('waffle-iron');
    if (!waffleIron) return [];

    let toolbar;
    try {
      toolbar = waffleIron.shadowRoot;
    } catch (err) {
      console.log('[Content] Google Sheets: shadowRoot inaccessible (cross-origin?)');
      return [];
    }

    if (!toolbar) return [];

    // Google Sheets toolbar buttons have these patterns:
    // <div class="goog-toolbarbutton" role="button" title="Format cells">...</div>
    // <div class="goog-menu-button goog-inline-block" role="button" title="Format">...</div>
    const buttons = toolbar.querySelectorAll(
      '[role="button"][title], [role="menuitem"][title], [aria-label]'
    );

    for (const btn of buttons) {
      const title = btn.getAttribute('title') || btn.getAttribute('aria-label') || '';
      if (!title.trim()) continue;

      // Get bounding rect in viewport coords
      let rect;
      try {
        rect = btn.getBoundingClientRect();
      } catch (err) {
        continue;
      }

      if (rect.width <= 0 || rect.height <= 0) continue;

      const style = window.getComputedStyle(btn);
      if (style.display === 'none' || style.visibility === 'hidden') continue;

      const role = btn.getAttribute('role') || 'button';
      // Map Google Sheets role to our schema
      const typeMap = {
        'button': 'button',
        'menuitem': 'menuitem',
        'menu': 'menu',
        'tab': 'tab',
      };
      const type = typeMap[role] || role;

      // Tag the element with an ID for click detection
      const nodeId = idCounter++;
      btn.setAttribute('data-ai-overlay-id', String(nodeId));

      nodes.push({
        id: nodeId,
        type: type,
        text: title.trim(),
        role: role,
        enabled: !btn.disabled,
        visible: true,
        bounds: {
          x: Math.round(rect.left),
          y: Math.round(rect.top),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        },
      });
    }

    // Also extract from the formula bar if present
    const formulaBar = toolbar.querySelector('.ink-pseudobutton, .goog-textinput');
    if (formulaBar) {
      const rect = formulaBar.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        const nodeId = idCounter++;
        formulaBar.setAttribute('data-ai-overlay-id', String(nodeId));
        nodes.push({
          id: nodeId,
          type: 'textbox',
          text: formulaBar.getAttribute('title') || 'Formula bar',
          role: 'textbox',
          enabled: true,
          visible: true,
          bounds: {
            x: Math.round(rect.left),
            y: Math.round(rect.top),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          },
        });
      }
    }

    console.log('[Content] Google Sheets extraction:', nodes.length, 'nodes from shadow DOM');
    return nodes;
  }

  /**
   * Detect which extraction strategy to use.
   */
  function extractElements() {
    const url = window.location.href;

    // Google Sheets: has a <waffle-iron> custom element with shadow DOM toolbar
    if (url.includes('docs.google.com/spreadsheets') && document.querySelector('waffle-iron')) {
      const nodes = extractFromGoogleSheets();
      if (nodes.length > 0) return nodes;
    }

    // Standard DOM extraction for everything else
    return extractFromDOM();
  }

  // ─── Overlay Layers ────────────────────────────────────────────────────────

  /**
   * Create or update the dim overlay covering the viewport.
   */
  function createDimOverlay() {
    removeDimOverlay();
    dimOverlay = document.createElement('div');
    dimOverlay.id = 'ai-overlay-dim';
    dimOverlay.style.cssText = `
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.55);
      pointer-events: none;
      z-index: 999998;
    `;
    document.body.appendChild(dimOverlay);
  }

  /**
   * Remove the dim overlay.
   */
  function removeDimOverlay() {
    if (dimOverlay && dimOverlay.parentNode) {
      dimOverlay.parentNode.removeChild(dimOverlay);
      dimOverlay = null;
    }
  }

  /**
   * Create or update the tooltip overlay near the target element.
   * @param {string} text - Tooltip text to display
   * @param {number|string} elementId - ID of the element to anchor to
   */
  function createTooltipOverlay(text, elementId) {
    removeTooltipOverlay();
    const targetEl = document.querySelector(`[data-ai-overlay-id="${elementId}"]`);
    if (!targetEl) return false;

    // Also try shadow DOM (for Google Sheets)
    let el = targetEl;
    if (!el) {
      const waffle = document.querySelector('waffle-iron');
      if (waffle && waffle.shadowRoot) {
        el = waffle.shadowRoot.querySelector(`[data-ai-overlay-id="${elementId}"]`);
      }
    }
    if (!el) return false;

    const rect = el.getBoundingClientRect();
    tooltipOverlay = document.createElement('div');
    tooltipOverlay.id = 'ai-overlay-tooltip';
    tooltipOverlay.style.cssText = `
      position: fixed;
      left: ${rect.left + window.scrollX}px;
      top: ${rect.top + window.scrollY - 28}px; /* Above the element */
      background: rgba(0, 0, 0, 0.75);
      color: white;
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 12px;
      pointer-events: none;
      z-index: 999999;
      max-width: 200px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    `;
    tooltipOverlay.textContent = text;
    document.body.appendChild(tooltipOverlay);
    return true;
  }

  /**
   * Remove the tooltip overlay.
   */
  function removeTooltipOverlay() {
    if (tooltipOverlay && tooltipOverlay.parentNode) {
      tooltipOverlay.parentNode.removeChild(tooltipOverlay);
      tooltipOverlay = null;
    }
  }

  /**
   * Create or update the spotlight overlay on the target element.
   * @param {number|string} elementId
   */
  function highlightElement(elementId) {
    // Remove all existing overlays
    removeHighlight();
    removeDimOverlay();
    removeTooltipOverlay();

    const targetEl = document.querySelector(`[data-ai-overlay-id="${elementId}"]`);
    if (!targetEl) return false;

    // Also try shadow DOM (for Google Sheets)
    let el = targetEl;
    if (!el) {
      const waffle = document.querySelector('waffle-iron');
      if (waffle && waffle.shadowRoot) {
        el = waffle.shadowRoot.querySelector(`[data-ai-overlay-id="${elementId}"]`);
      }
    }
    if (!el) return false;

    const rect = el.getBoundingClientRect();

    // Create dim layer
    createDimOverlay();

    // Create highlight ring
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
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    return true;
  }

  /**
   * Remove all overlays (highlight, dim, tooltip).
   */
  function removeAllOverlays() {
    removeHighlight();
    removeDimOverlay();
    removeTooltipOverlay();
  }

  // ─── Message handling ──────────────────────────────────────────────────────

  // Handle messages from background service worker / extension
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    console.log('[Content] Received message:', request.action);
    if (request.action === 'GET_TREE') {
      const tree = extractElements();
      const viewportOffset = getViewportOffset();
      console.log('[Content] Extracted', tree.length, 'nodes, viewportOffset:', viewportOffset);
      sendResponse({
        status: 'ok',
        tree: tree,
        url: window.location.href,
        viewportOffset: viewportOffset,
      });
    } else if (request.action === 'HIGHLIGHT') {
      const success = highlightElement(request.elementId);
      // If we have tooltip text, show it
      if (request.tooltip) {
        createTooltipOverlay(request.tooltip, request.elementId);
      }
      console.log('[Content] HIGHLIGHT elementId:', request.elementId, 'success:', success);
      sendResponse({ status: success ? 'ok' : 'not_found' });
    } else if (request.action === 'CLEAR_HIGHLIGHT') {
      removeAllOverlays();
      sendResponse({ status: 'ok' });
    }
    // New message type for CSP blocking feedback
    else if (request.action === 'OVERLAY_BLOCKED') {
      // Just log for now; could be used to trigger fallback in Python
      console.warn('[Content] Overlay blocked by CSP on:', request.url);
      sendResponse({ status: 'ok' });
    }
    return true; // Keep response channel open for async
  });

  // ─── Click tracking ───────────────────────────────────────────────────────

  // Track user clicks to send event back to background
  document.addEventListener('click', (event) => {
    // Check normal DOM first, then shadow DOM
    let target = event.target.closest('[data-ai-overlay-id]');
    if (!target) {
      const waffle = document.querySelector('waffle-iron');
      if (waffle && waffle.shadowRoot) {
        target = waffle.shadowRoot.querySelector('[data-ai-overlay-id]');
      }
    }
    const clickedId = target ? target.getAttribute('data-ai-overlay-id') : null;
    chrome.runtime.sendMessage({
      action: 'USER_CLICK',
      elementId: clickedId,
      tagName: event.target.tagName,
      url: window.location.href,
    }).catch(() => {});
  }, true);

  // ─── Mutation tracking ─────────────────────────────────────────────────────

  let mutationTimeout = null;
  const observer = new MutationObserver(() => {
    if (mutationTimeout) clearTimeout(mutationTimeout);
    mutationTimeout = setTimeout(() => {
      chrome.runtime.sendMessage({
        action: 'DOM_MUTATED',
        url: window.location.href,
      }).catch(() => {});
    }, 300);
  });

  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
  }

})();
