"""Main entry point for the AI overlay application."""
from __future__ import annotations

import logging
import os
import sys

from PyQt6.QtCore import Qt, QRect, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication

# Force 1:1 pixel mapping so pywinauto's physical pixel coords match Qt's
# coordinate space exactly. Without this, on a 125% DPI display Qt uses
# logical pixels (physical / 1.25) which shifts every spotlight/dim rect.
QApplication.setAttribute(Qt.ApplicationAttribute.AA_Use96Dpi)

from core.overlay_window import OverlayWindow
from core.layer_manager import LayerManager
from core.task_controller import TaskController
from core.action_watcher import ActionWatcher
from core.step import Step
from core.UI import TaskInputDialog
from core.tts import TTSEngine
from core.completion_toast import CompletionToast
from platforms.browser_connector import BrowserConnector
from dotenv import load_dotenv
load_dotenv()

_log = logging.getLogger(__name__)


def _get_step_element_id(step: Step) -> int | None:
    """Return the DOM element ID for a step, or None if not available."""
    # For website mode steps, the element id might be in step.element['id']
    if hasattr(step, 'element') and isinstance(step.element, dict):
        elem_id = step.element.get('id')
        if elem_id is not None:
            return elem_id
    return getattr(step, "element_id", None)

# ── API key ───────────────────────────────────────────────────────────────────
# Optional: GEMINI_API_KEY can be set in .env for Gemini fallback.
# If not set, local Ollama model (qwen-fast:latest) will be used automatically.
_GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")


def main() -> None:
    # ── 1. Application ────────────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setApplicationName("AI Overlay")

    # ── 2. TTS engine & Browser Connector ─────────────────────────────
    tts = TTSEngine()
    browser_connector = BrowserConnector()  # Starts WebSocket server on ws://localhost:8765

    # ── 3. Core overlay objects (hidden until task is ready) ──────────
    overlay       = OverlayWindow()
    layer_manager = LayerManager(overlay, tts=tts)
    controller    = TaskController(layer_manager)
    hud           = layer_manager.hud_layer
    watcher       = ActionWatcher()

    # ── 4. Shared exit handler ────────────────────────────────────────
    def _on_exit() -> None:
        watcher.shutdown()
        controller.shutdown()
        tts.shutdown()
        browser_connector.shutdown()
        overlay.hide_overlay()
        app.quit()

    # ── 5. Task-completion celebration (feature 1.4) ──────────────────
    def _on_task_completed() -> None:
        watcher.shutdown()
        controller.shutdown()
        browser_connector.shutdown()
        overlay.hide_overlay()
        # Show toast; quit when it finishes fading out
        _toast = CompletionToast(callback=lambda: (tts.shutdown(), app.quit()))  # noqa: F841
        # Keep a reference so GC doesn't collect it
        app._completion_toast = _toast  # type: ignore[attr-defined]

    # ── 6. HUD navigation signals ─────────────────────────────────────
    hud.exit_clicked.connect(_on_exit)

    # Pause: hide spotlight/dim/tooltip but keep HUD visible
    def _on_pause(is_paused: bool) -> None:
        layer_manager.set_paused(is_paused)
        if is_paused:
            watcher.stop_watching()

    hud.paused.connect(_on_pause)

    # 1.8  Step dots — random-access navigation
    hud.step_dot_clicked.connect(controller.go_to_step)

    # ── 7. Step-complete flash (feature 1.3) before advancing ─────────
    def _advance_with_flash() -> None:
        """Show green ✓ flash on current spotlight, then advance."""
        layer_manager.flash_step_complete(callback=controller.next_step)

    def _go_back_with_flash() -> None:
        layer_manager.flash_step_complete(callback=controller.prev_step)

    hud.next_clicked.connect(_advance_with_flash)
    hud.back_clicked.connect(_go_back_with_flash)

    # ── 8. Async coord-resolution signals ────────────────────────────
    controller.coords_resolved.connect(layer_manager.on_coords_resolved)
    controller.resolution_failed.connect(layer_manager.show_resolution_failed)

    def _on_element_not_found(target: str, error: object) -> None:
        layer_manager.show_recovery_panel(
            target=target,
            error=error,
            on_skip=controller.next_step,
            on_retry=lambda: controller.go_to_step(controller.current_step_index())
        )
    controller.element_not_found.connect(_on_element_not_found)

    # ── 8b. ActionWatcher — auto-advance on menu/dialog/focus events ──
    def _on_coords_resolved(step) -> None:
        if layer_manager.is_website_mode:
            return  # Website mode: extension handles overlay + click detection
        layer_manager.on_coords_resolved(step)
        if step.coords:
            l, t, r, b = step.coords
            watcher.start_watching(QRect(l, t, r - l, b - t))

    controller.coords_resolved.disconnect(layer_manager.on_coords_resolved)
    controller.coords_resolved.connect(_on_coords_resolved)

    # Auto-advance with flash when ActionWatcher fires
    def _on_action_detected() -> None:
        watcher.stop_watching()
        layer_manager.flash_step_complete(callback=controller.next_step)

    watcher.action_detected.connect(_on_action_detected)

    # Stop watcher when user manually navigates
    hud.next_clicked.connect(watcher.stop_watching)
    hud.back_clicked.connect(watcher.stop_watching)
    controller.task_completed.connect(watcher.shutdown)

    # ── 9. Step-counter: HUD + window title ───────────────────────────
    def _on_step_changed(index: int, total: int) -> None:
        hud.update_progress(index, total)
        overlay.setWindowTitle(f"AI Overlay — Step {index + 1} of {total}")
        # Send step update to browser extension for progress bar
        browser_connector.send_custom_message({
            'type': 'stepUpdate',
            'currentStep': index + 1,
            'totalSteps': total
        })

    controller.step_changed.connect(_on_step_changed)
    controller.task_completed.connect(_on_task_completed)

    # ── 10. Keyboard shortcuts ─────────────────────────────────────────
    sc_next = QShortcut(QKeySequence(Qt.Key.Key_Right), overlay)
    sc_next.setContext(Qt.ShortcutContext.ApplicationShortcut)
    sc_next.activated.connect(_advance_with_flash)

    sc_prev = QShortcut(QKeySequence(Qt.Key.Key_Left), overlay)
    sc_prev.setContext(Qt.ShortcutContext.ApplicationShortcut)
    sc_prev.activated.connect(_go_back_with_flash)

    sc_exit = QShortcut(QKeySequence(Qt.Key.Key_Escape), overlay)
    sc_exit.setContext(Qt.ShortcutContext.ApplicationShortcut)
    sc_exit.activated.connect(_on_exit)

    # ── 11. Task-input dialog ─────────────────────────────────────────
    dialog = TaskInputDialog(api_key=_GEMINI_API_KEY, browser_connector=browser_connector)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    def _on_task_ready(path: str, mode: str) -> None:
        """Called when AI generator finishes and the task JSON file is saved."""
        dialog.task_ready.disconnect(_on_task_ready)  # prevent double-load
        dialog.hide()
        dialog.close()

        if mode == "website":
            # ── Website mode setup ────────────────────────────────────────────
            # 1. Hide PyQt overlay immediately — browser extension renders instead
            layer_manager.set_mode("website")
            overlay.hide_overlay()

            # Track pending element_id and target for click detection
            pending_element_id: int | None = None
            pending_target: str = ""

            # ── Bug 1 fix: connect BEFORE load_task so step 1 is not missed ──
            def _on_step_resolved_website(step) -> None:
                # Try to highlight immediately
                result1 = browser_connector.highlight(
                    _get_step_element_id(step),
                    tooltip=step.tooltip,
                    target=getattr(step, "target", ""),
                )
                if not result1:
                    _log.warning("Highlight failed for step %d (first attempt)", step.id)
                # Try again after a short delay
                def try_again():
                    result2 = browser_connector.highlight(
                        _get_step_element_id(step),
                        tooltip=step.tooltip,
                        target=getattr(step, "target", ""),
                    )
                    if not result2:
                        _log.warning("Highlight failed for step %d (second attempt)", step.id)
                QTimer.singleShot(200, try_again)

            def _track_element(step) -> None:
                nonlocal pending_element_id, pending_target
                pending_element_id = _get_step_element_id(step)
                pending_target = getattr(step, "target", "")

            def _on_website_click(data: dict) -> None:
                nonlocal pending_element_id, pending_target
                msg_type = data.get("type")

                # ── Bug 3 fix: refresh DOM snapshot on mutation ───────────────
                if msg_type == "dom_mutated":
                    import threading as _threading
                    def _refresh_dom() -> None:
                        try:
                            new_tree = browser_connector.get_tree(timeout=3.0)
                            if new_tree:
                                _log.info("DOM refreshed after mutation: %d nodes", len(new_tree))
                                # Re-highlight the current step with fresh DOM data
                                from PyQt6.QtCore import QTimer as _QTimer
                                _QTimer.singleShot(0, lambda: browser_connector.highlight(
                                    pending_element_id,
                                    tooltip="",
                                    target=pending_target,
                                ))
                        except Exception as exc:
                            _log.warning("DOM refresh after mutation failed: %s", exc)
                    _threading.Thread(target=_refresh_dom, daemon=True).start()
                    return

                if msg_type != "user_click":
                    return

                clicked = data.get("elementId")
                clicked_text = (data.get("targetText") or "").strip().lower()

                matched = False
                if clicked is not None and pending_element_id is not None:
                    if str(clicked) == str(pending_element_id):
                        matched = True
                if not matched and pending_target and clicked_text:
                    if pending_target.lower() in clicked_text or clicked_text in pending_target.lower():
                        matched = True

                if matched:
                    pending_element_id = None
                    pending_target = ""
                    if data.get("isNavigation"):
                        # Wait for navigation to complete (2 seconds) then advance
                        QTimer.singleShot(2000, controller.next_step)
                    else:
                        controller.next_step()

            # Connect website-mode signals before loading the task
            controller.coords_resolved.disconnect(_on_coords_resolved)
            controller.resolution_failed.disconnect(layer_manager.show_resolution_failed)
            controller.coords_resolved.connect(_on_step_resolved_website)
            controller.coords_resolved.connect(_track_element)

            # Wire click/mutation detection from browser connector
            browser_connector.observe_changes(_on_website_click)

            # Now load the task — coords_resolved will fire for step 1 immediately
            # and _on_step_resolved_website is already connected to catch it
            try:
                controller.load_task(path)
            except Exception:
                _log.exception("Failed to load task from %s", path)
                return

        else:
            # ── App mode ─────────────────────────────────────────────────────
            try:
                controller.load_task(path)
            except Exception:
                _log.exception("Failed to load task from %s", path)
                return
            overlay.show_overlay()


    dialog.task_ready.connect(_on_task_ready)

    def _on_dialog_closed() -> None:
        # Only quit if no task was started
        if controller.total_steps() == 0 and not overlay.isVisible():
            controller.shutdown()
            tts.shutdown()
            app.quit()

    app.lastWindowClosed.connect(_on_dialog_closed)

    # ── 12. Show the input dialog ─────────────────────────────────────
    dialog.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
