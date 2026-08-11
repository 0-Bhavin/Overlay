"""Main entry point for the AI overlay application."""
from __future__ import annotations

import os
import sys

from PyQt6.QtCore import Qt, QRect
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
from core.UI import TaskInputDialog
from core.tts import TTSEngine
from core.completion_toast import CompletionToast
from dotenv import load_dotenv
load_dotenv()

# ── API key ───────────────────────────────────────────────────────────────────
# Set GEMINI_API_KEY in your environment (.env file or system variable).
_GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
if not _GEMINI_API_KEY:
    raise EnvironmentError(
        "GEMINI_API_KEY is not set.\n"
        "Add it to a .env file or set it as a system environment variable."
    )


def main() -> None:
    # ── 1. Application ────────────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setApplicationName("AI Overlay")

    # ── 2. TTS engine (feature 1.5) ───────────────────────────────────
    tts = TTSEngine()

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
        overlay.hide_overlay()
        app.quit()

    # ── 5. Task-completion celebration (feature 1.4) ──────────────────
    def _on_task_completed() -> None:
        watcher.shutdown()
        controller.shutdown()
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

    # ── 8b. ActionWatcher — auto-advance on menu/dialog/focus events ──
    def _on_coords_resolved(step) -> None:
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
    dialog = TaskInputDialog(api_key=_GEMINI_API_KEY)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    def _on_task_ready(path: str) -> None:
        """Called when Gemini finishes and the task JSON file is saved."""
        dialog.hide()
        controller.load_task(path)
        overlay.show_overlay()

    dialog.task_ready.connect(_on_task_ready)

    def _on_dialog_closed() -> None:
        if not overlay.isVisible():
            controller.shutdown()
            tts.shutdown()
            app.quit()

    app.lastWindowClosed.connect(_on_dialog_closed)

    # ── 12. Show the input dialog ─────────────────────────────────────
    dialog.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
