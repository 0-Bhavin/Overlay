/**
 * AI Overlay — DOM Extractor
 * Traverses live DOM, applies tag & visibility filtering rules per Project Plan,
 * and extracts simplified UI nodes in standard UINode JSON schema format.
 */

(function (global) {
  'use strict';

  // Interactive tags always retained (if visible)
  const INTERACTIVE_TAGS = new Set([
    'BUTTON', 'A', 'INPUT', 'TEXTAREA', 'SELECT', 'OPTION',
    'LABEL', 'FORM', 'SUMMARY', 'DETAILS'
  ]);

  // Structural tags retained if containing text, ARIA attributes, or interactive descendants
  const STRUCTURAL_TAGS = new Set([
    'NAV', 'MENU', 'HEADER', 'FOOTER', 'MAIN',
    'SECTION', 'ARTICLE', 'ASIDE', 'DIV', 'SPAN'
  ]);

  // Tags completely ignored
  const IGNORED_TAGS = new Set([
    'SCRIPT', 'STYLE', 'META', 'LINK', 'NOSCRIPT', 'TEMPLATE',
    'SVG', 'PATH', 'DEFS', 'CLIPPATH', 'SYMBOL', 'USE', 'G'
  ]);

  /**
   * Check if an element is visible in the viewport and rendered.
   * @param {Element} el
   * @param {DOMRect} rect
   * @returns {boolean}
   */
  function isElementVisible(el, rect) {
    if (!el || !(el instanceof Element)) return false;
    if (el.hasAttribute('hidden') || el.getAttribute('aria-hidden') === 'true') return false;
    if (rect.width <= 0 || rect.height <= 0) return false;

    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
      return false;
    }
    return true;
  }

  /**
   * Extract meaningful text from element.
   * @param {Element} el
   * @returns {string}
   */
  function extractElementText(el) {
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      return (el.value || el.placeholder || el.getAttribute('aria-label') || el.name || '').trim();
    }
    const ariaLabel = el.getAttribute('aria-label') || el.getAttribute('title');
    if (ariaLabel) return ariaLabel.trim();

    // Direct child text nodes or clean innerText (truncated to avoid giant text blocks)
    let text = (el.innerText || el.textContent || '').trim();
    return text.replace(/\s+/g, ' ').slice(0, 100);
  }

  /**
   * Determine node type string (e.g., "button", "input:text", "link").
   * @param {Element} el
   * @returns {string}
   */
  function determineNodeType(el) {
    const tag = el.tagName.toLowerCase();
    if (tag === 'input') {
      const inputType = el.getAttribute('type') || 'text';
      return `input:${inputType.toLowerCase()}`;
    }
    if (tag === 'a') return 'link';
    return tag;
  }

  /**
   * Main DOM Extraction Function
   * Returns array of simplified UI node objects.
   * @returns {Array<Object>}
   */
  function extractSimplifiedDOM() {
    const nodes = [];
    let idCounter = 1;

    function walkNode(el) {
      if (!el || el.nodeType !== Node.ELEMENT_NODE) return;

      const tagName = el.tagName.toUpperCase();

      // Skip explicitly ignored elements
      if (IGNORED_TAGS.has(tagName)) return;

      const rect = el.getBoundingClientRect();
      const visible = isElementVisible(el, rect);
      if (!visible) return;

      const isInteractive = INTERACTIVE_TAGS.has(tagName) || el.hasAttribute('onclick') || el.getAttribute('role') === 'button';
      const isStructural = STRUCTURAL_TAGS.has(tagName);
      const text = extractElementText(el);
      const hasAriaRole = el.hasAttribute('role');

      // Keep node if interactive OR if structural with meaningful content/role
      let shouldKeep = false;
      if (isInteractive) {
        shouldKeep = true;
      } else if (isStructural) {
        if (hasAriaRole || (text && text.length > 0 && text.length < 150)) {
          shouldKeep = true;
        }
      }

      if (shouldKeep) {
        const nodeId = idCounter++;
        // Tag element in DOM for fast reference when highlighting / waiting for click
        el.setAttribute('data-ai-overlay-id', String(nodeId));

        const node = {
          id: nodeId,
          type: determineNodeType(el),
          text: text,
          role: el.getAttribute('role') || el.tagName.toLowerCase(),
          enabled: !el.disabled,
          visible: true,
          bounds: {
            x: Math.round(rect.left + window.scrollX),
            y: Math.round(rect.top + window.scrollY),
            width: Math.round(rect.width),
            height: Math.round(rect.height)
          }
        };
        nodes.push(node);
      }

      // Recurse into children
      for (let i = 0; i < el.children.length; i++) {
        walkNode(el.children[i]);
      }
    }

    walkNode(document.body);
    return nodes;
  }

  // Export to global scope
  global.AIOverlayDOMExtractor = {
    extractSimplifiedDOM: extractSimplifiedDOM
  };

})(typeof window !== 'undefined' ? window : this);
