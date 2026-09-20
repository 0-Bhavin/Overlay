/**
 * AI Overlay — Enhanced Highlighting Module
 *
 * This module provides better element highlighting using:
 * - Robust CSS with Tailwind-like utility classes
 * - Multiple highlight styles
 * - Better z-index management
 * - Animation performance improvements
 */

(function() {
  'use strict';

  // ─── Highlight Styles ─────────────────────────────────────────────────────
  const HighlightStyles = {
    PRIMARY: 'primary',
    SECONDARY: 'secondary',
    SUCCESS: 'success',
    WARNING: 'warning',
    ERROR: 'error'
  };

  // Color palette with Tailwind-like utility colors
  const HighlightColors = {
    primary: {
      border: '#3b82f6',      // blue-500
      shadow: 'rgba(59, 130, 246, 0.9)',
      inset: 'rgba(59, 130, 246, 0.2)',
      bg: 'rgba(59, 130, 246, 0.1)'
    },
    success: {
      border: '#10b981',      // emerald-500
      shadow: 'rgba(16, 185, 129, 0.9)',
      inset: 'rgba(16, 185, 129, 0.2)',
      bg: 'rgba(16, 185, 129, 0.1)'
    },
    warning: {
      border: '#f59e0b',      // amber-500
      shadow: 'rgba(245, 158, 11, 0.9)',
      inset: 'rgba(245, 158, 11, 0.2)',
      bg: 'rgba(245, 158, 11, 0.1)'
    },
    error: {
      border: '#ef4444',      // red-500
      shadow: 'rgba(239, 68, 68, 0.9)',
      inset: 'rgba(239, 68, 68, 0.2)',
      bg: 'rgba(239, 68, 68, 0.1)'
    }
  };

  // ─── Enhanced Highlight Manager ───────────────────────────────────────────
  class EnhancedHighlightManager {
    constructor() {
      this.highlightOverlay = null;
      this.dimOverlay = null;
      this.tooltipOverlay = null;
      this.currentElement = null;
      this.currentStyle = HighlightStyles.PRIMARY;
      this.zIndexCounter = 1000000; // Start with very high z-index

      this.injectStyles();
    }

    // ─── CSS Injection ──────────────────────────────────────────────────────
    injectStyles() {
      if (document.getElementById('ai-overlay-enhanced-styles')) {
        return; // Styles already injected
      }

      const style = document.createElement('style');
      style.id = 'ai-overlay-enhanced-styles';
      style.textContent = `
        /* Enhanced Highlight Styles - Tailwind-inspired */
        #ai-overlay-dim-enhanced {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.55);
          pointer-events: none;
          z-index: 999998;
          backdrop-filter: blur(2px);
        }

        #ai-overlay-spotlight-ring-enhanced {
          position: absolute;
          pointer-events: none;
          z-index: 999999;
          transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
          border-radius: 8px;
          border-width: 3px;
          border-style: solid;
          box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.1);
        }

        /* Highlight Style Classes */
        .ai-overlay-highlight-primary {
          border-color: #3b82f6;
          background: rgba(59, 130, 246, 0.1);
          box-shadow:
            0 0 0 1px rgba(255, 255, 255, 0.1),
            0 0 16px rgba(59, 130, 246, 0.9),
            inset 0 0 12px rgba(59, 130, 246, 0.2);
        }

        .ai-overlay-highlight-success {
          border-color: #10b981;
          background: rgba(16, 185, 129, 0.1);
          box-shadow:
            0 0 0 1px rgba(255, 255, 255, 0.1),
            0 0 16px rgba(16, 185, 129, 0.9),
            inset 0 0 12px rgba(16, 185, 129, 0.2);
        }

        .ai-overlay-highlight-warning {
          border-color: #f59e0b;
          background: rgba(245, 158, 11, 0.1);
          box-shadow:
            0 0 0 1px rgba(255, 255, 255, 0.1),
            0 0 16px rgba(245, 158, 11, 0.9),
            inset 0 0 12px rgba(245, 158, 11, 0.2);
        }

        .ai-overlay-highlight-error {
          border-color: #ef4444;
          background: rgba(239, 68, 68, 0.1);
          box-shadow:
            0 0 0 1px rgba(255, 255, 255, 0.1),
            0 0 16px rgba(239, 68, 68, 0.9),
            inset 0 0 12px rgba(239, 68, 68, 0.2);
        }

        /* Animation Keyframes */
        @keyframes aiOverlayPulseEnhanced {
          0% {
            transform: scale(1);
            box-shadow: 0 0 6px currentColor;
          }
          50% {
            transform: scale(1.01);
            box-shadow: 0 0 20px currentColor;
          }
          100% {
            transform: scale(1);
            box-shadow: 0 0 6px currentColor;
          }
        }

        @keyframes aiOverlayBreath {
          0%, 100% { opacity: 0.8; }
          50% { opacity: 1; }
        }

        .ai-overlay-animate-pulse {
          animation: aiOverlayPulseEnhanced 1.5s ease-in-out infinite;
        }

        .ai-overlay-animate-breath {
          animation: aiOverlayBreath 2s ease-in-out infinite;
        }

        /* Tooltip */
        #ai-overlay-tooltip-enhanced {
          position: absolute;
          background: rgba(15, 23, 42, 0.95);
          color: #f8fafc;
          padding: 6px 12px;
          border-radius: 6px;
          border: 1px solid rgba(59, 130, 246, 0.6);
          font-size: 13px;
          font-family: system-ui, -apple-system, sans-serif;
          font-weight: 500;
          pointer-events: none;
          z-index: 1000000;
          max-width: 350px;
          white-space: normal;
          word-wrap: break-word;
          box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
          backdrop-filter: blur(8px);
          transform-origin: bottom center;
          animation: aiOverlayBreath 3s ease-in-out infinite;
        }

        /* Step Progress Indicator */
        #ai-overlay-step-progress {
          position: fixed;
          top: 16px;
          right: 16px;
          background: rgba(15, 23, 42, 0.9);
          color: #f8fafc;
          padding: 8px 16px;
          border-radius: 12px;
          font-size: 14px;
          font-weight: 500;
          z-index: 1000001;
          backdrop-filter: blur(8px);
          border: 1px solid rgba(59, 130, 246, 0.3);
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }

        #ai-overlay-step-progress .step-number {
          font-weight: 700;
          color: #3b82f6;
        }

        #ai-overlay-step-progress .total-steps {
          color: #94a3b8;
          font-size: 12px;
        }
      `;

      document.head.appendChild(style);
      console.log('[EnhancedHighlight] Styles injected');
    }

    // ─── Create Dim Overlay ────────────────────────────────────────────────
    createDimOverlay() {
      this.removeDimOverlay();

      this.dimOverlay = document.createElement('div');
      this.dimOverlay.id = 'ai-overlay-dim-enhanced';
      document.body.appendChild(this.dimOverlay);

      // Animate in
      this.dimOverlay.style.opacity = '0';
      setTimeout(() => {
        this.dimOverlay.style.transition = 'opacity 0.3s ease';
        this.dimOverlay.style.opacity = '1';
      }, 10);

      console.log('[EnhancedHighlight] Dim overlay created');
      return this.dimOverlay;
    }

    // ─── Create Highlight Ring ──────────────────────────────���──────────────
    createHighlightRing(element, style = HighlightStyles.PRIMARY) {
      this.removeHighlightRing();
      this.currentElement = element;
      this.currentStyle = style;

      const rect = element.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) {
        console.warn('[EnhancedHighlight] Element has zero dimensions');
        return null;
      }

      // Create highlight ring
      this.highlightOverlay = document.createElement('div');
      this.highlightOverlay.id = 'ai-overlay-spotlight-ring-enhanced';
      this.highlightOverlay.className = `ai-overlay-highlight-${style} ai-overlay-animate-pulse`;

      // Calculate position with scroll offset
      const scrollX = window.scrollX || window.pageXOffset;
      const scrollY = window.scrollY || window.pageYOffset;

      this.highlightOverlay.style.cssText = `
        left: ${rect.left + scrollX - 4}px;
        top: ${rect.top + scrollY - 4}px;
        width: ${rect.width + 8}px;
        height: ${rect.height + 8}px;
        z-index: ${this.zIndexCounter++};
      `;

      // Ensure the element is visible
      try {
        element.scrollIntoView({
          behavior: 'smooth',
          block: 'center',
          inline: 'center'
        });
      } catch (e) {
        console.log('[EnhancedHighlight] Could not scroll element into view:', e);
      }

      // Add to document
      document.body.appendChild(this.highlightOverlay);

      // Apply enter animation
      this.highlightOverlay.style.transform = 'scale(0.9)';
      setTimeout(() => {
        this.highlightOverlay.style.transition = 'transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)';
        this.highlightOverlay.style.transform = 'scale(1)';
      }, 10);

      console.log('[EnhancedHighlight] Highlight ring created for element:', {
        tagName: element.tagName,
        id: element.id,
        className: element.className,
        rect: rect,
        style: style
      });

      return this.highlightOverlay;
    }

    // ─── Create Tooltip ────────────────────────────────────────────────────
    createTooltip(text, element, position = 'above') {
      this.removeTooltip();

      if (!text || !element) {
        return null;
      }

      const rect = element.getBoundingClientRect();
      const scrollX = window.scrollX || window.pageXOffset;
      const scrollY = window.scrollY || window.pageYOffset;

      this.tooltipOverlay = document.createElement('div');
      this.tooltipOverlay.id = 'ai-overlay-tooltip-enhanced';
      this.tooltipOverlay.textContent = text;

      // Position tooltip above or below element
      let top, left;

      if (position === 'above') {
        top = Math.max(8, rect.top + scrollY - 40);
      } else {
        top = rect.bottom + scrollY + 8;
      }

      // Center horizontally
      left = rect.left + scrollX + (rect.width / 2);
      this.tooltipOverlay.style.left = `${left}px`;
      this.tooltipOverlay.style.top = `${top}px`;
      this.tooltipOverlay.style.transform = 'translateX(-50%)';

      // Add to document
      document.body.appendChild(this.tooltipOverlay);

      // Animate in
      this.tooltipOverlay.style.opacity = '0';
      this.tooltipOverlay.style.transform = 'translateX(-50%) translateY(-10px)';
      setTimeout(() => {
        this.tooltipOverlay.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
        this.tooltipOverlay.style.opacity = '1';
        this.tooltipOverlay.style.transform = 'translateX(-50%) translateY(0)';
      }, 10);

      console.log('[EnhancedHighlight] Tooltip created:', text);
      return this.tooltipOverlay;
    }

    // ─── Show Step Progress ────────────────────────────────────────────────
    showStepProgress(currentStep, totalSteps) {
      this.removeStepProgress();

      const progressDiv = document.createElement('div');
      progressDiv.id = 'ai-overlay-step-progress';
      progressDiv.innerHTML = `
        Step <span class="step-number">${currentStep}</span>
        of <span class="total-steps">${totalSteps}</span>
      `;

      document.body.appendChild(progressDiv);

      // Animate in
      progressDiv.style.opacity = '0';
      progressDiv.style.transform = 'translateY(-20px)';
      setTimeout(() => {
        progressDiv.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
        progressDiv.style.opacity = '1';
        progressDiv.style.transform = 'translateY(0)';
      }, 10);

      console.log('[EnhancedHighlight] Step progress shown:', { currentStep, totalSteps });
      return progressDiv;
    }

    // ─── Update Highlight Position ─────────────────────────────────────────
    updateHighlightPosition() {
      if (!this.highlightOverlay || !this.currentElement) {
        return;
      }

      const rect = this.currentElement.getBoundingClientRect();
      const scrollX = window.scrollX || window.pageXOffset;
      const scrollY = window.scrollY || window.pageYOffset;

      this.highlightOverlay.style.left = `${rect.left + scrollX - 4}px`;
      this.highlightOverlay.style.top = `${rect.top + scrollY - 4}px`;
      this.highlightOverlay.style.width = `${rect.width + 8}px`;
      this.highlightOverlay.style.height = `${rect.height + 8}px`;

      console.log('[EnhancedHighlight] Highlight position updated');
    }

    // ─── Change Highlight Style ────────────────────────────────────────────
    changeHighlightStyle(newStyle) {
      if (!this.highlightOverlay) {
        return;
      }

      // Remove old style classes
      Object.values(HighlightStyles).forEach(style => {
        this.highlightOverlay.classList.remove(`ai-overlay-highlight-${style}`);
      });

      // Add new style
      this.highlightOverlay.classList.add(`ai-overlay-highlight-${newStyle}`);
      this.currentStyle = newStyle;

      console.log('[EnhancedHighlight] Style changed to:', newStyle);
    }

    // ─── Complete Step Animation ───────────────────────────────────────────
    completeStep() {
      if (!this.highlightOverlay) {
        return;
      }

      // Flash green success animation
      this.highlightOverlay.classList.remove(`ai-overlay-highlight-${this.currentStyle}`);
      this.highlightOverlay.classList.add('ai-overlay-highlight-success');

      // Add a "checkmark" effect
      const checkmark = document.createElement('div');
      checkmark.style.cssText = `
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        width: 48px;
        height: 48px;
        background: rgba(16, 185, 129, 0.9);
        border-radius: 50%;
        color: white;
        font-size: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: ${this.zIndexCounter++};
      `;
      checkmark.textContent = '✓';

      this.highlightOverlay.appendChild(checkmark);

      // Animate checkmark
      checkmark.style.transform = 'translate(-50%, -50%) scale(0)';
      setTimeout(() => {
        checkmark.style.transition = 'transform 0.3s cubic-bezier(0.68, -0.55, 0.265, 1.55)';
        checkmark.style.transform = 'translate(-50%, -50%) scale(1)';
      }, 10);

      // Remove after animation
      setTimeout(() => {
        if (checkmark.parentNode) {
          checkmark.parentNode.removeChild(checkmark);
        }
      }, 1500);

      console.log('[EnhancedHighlight] Step completed animation');
    }

    // ─── Cleanup Methods ───────────────────────────────────────────────────
    removeHighlightRing() {
      if (this.highlightOverlay && this.highlightOverlay.parentNode) {
        this.highlightOverlay.parentNode.removeChild(this.highlightOverlay);
        this.highlightOverlay = null;
        this.currentElement = null;
      }
    }

    removeDimOverlay() {
      if (this.dimOverlay && this.dimOverlay.parentNode) {
        this.dimOverlay.parentNode.removeChild(this.dimOverlay);
        this.dimOverlay = null;
      }
    }

    removeTooltip() {
      if (this.tooltipOverlay && this.tooltipOverlay.parentNode) {
        this.tooltipOverlay.parentNode.removeChild(this.tooltipOverlay);
        this.tooltipOverlay = null;
      }
    }

    removeStepProgress() {
      const progress = document.getElementById('ai-overlay-step-progress');
      if (progress && progress.parentNode) {
        progress.parentNode.removeChild(progress);
      }
    }

    removeAllOverlays() {
      this.removeHighlightRing();
      this.removeDimOverlay();
      this.removeTooltip();
      this.removeStepProgress();
      console.log('[EnhancedHighlight] All overlays removed');
    }

    // ─── Highlight Element (Main API) ──────────────────────────────────────
    highlight(element, options = {}) {
      const {
        tooltip = '',
        style = HighlightStyles.PRIMARY,
        showDim = true,
        showProgress = false,
        currentStep = 1,
        totalSteps = 1
      } = options;

      // Remove existing overlays
      this.removeAllOverlays();

      // Create dim layer if requested
      if (showDim) {
        this.createDimOverlay();
      }

      // Create highlight ring
      const ring = this.createHighlightRing(element, style);
      if (!ring) {
        console.error('[EnhancedHighlight] Failed to create highlight ring');
        return false;
      }

      // Create tooltip if provided
      if (tooltip) {
        this.createTooltip(tooltip, element);
      }

      // Show step progress if requested
      if (showProgress) {
        this.showStepProgress(currentStep, totalSteps);
      }

      return true;
    }
  }

  // ─── Export to Global Scope ──────────────────────────────────────────────
  window.AIOverlayEnhancedHighlight = {
    HighlightManager: EnhancedHighlightManager,
    HighlightStyles: HighlightStyles,

    // Convenience function for testing
    testHighlight: function(elementId = 'test-element') {
      const element = document.getElementById(elementId);
      if (!element) {
        console.error('[EnhancedHighlight] Test element not found:', elementId);
        return false;
      }

      const manager = new EnhancedHighlightManager();
      return manager.highlight(element, {
        tooltip: 'Test Highlight',
        style: HighlightStyles.PRIMARY,
        showDim: true,
        showProgress: true,
        currentStep: 1,
        totalSteps: 5
      });
    },

    // Integration with existing content.js
    enhanceExistingHighlight: function() {
      console.log('[EnhancedHighlight] Enhancing existing highlight system...');

      // Create manager instance
      const manager = new EnhancedHighlightManager();

      // Override content.js highlightElement if it exists
      if (typeof highlightElement !== 'undefined') {
        const originalHighlightElement = highlightElement;

        window.highlightElementEnhanced = function(elementId, targetText, tooltip, style = HighlightStyles.PRIMARY) {
          const element = findElement(elementId, targetText);
          if (!element) {
            console.warn('[EnhancedHighlight] Element not found:', elementId, targetText);
            return false;
          }

          return manager.highlight(element, {
            tooltip: tooltip || targetText,
            style: style,
            showDim: true
          });
        };

        console.log('[EnhancedHighlight] Enhanced highlight system ready');
      }
    }
  };

  console.log('[EnhancedHighlight] Module loaded successfully');
})();