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
from dotenv import load_dotenv
load_dotenv()

# ── API key ───────────────────────────────────────────────────────────────────
# Set GEMINI_API_KEY in your environment, or replace the fallback string.
_GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")


def main() -> None:
    # ── 1. Application ────────────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setApplicationName("AI Overlay")

    # ── 2. Core overlay objects (hidden until task is ready) ──────────
    overlay       = OverlayWindow()
    layer_manager = LayerManager(overlay)
    controller    = TaskController(layer_manager)
    hud           = layer_manager.hud_layer
    watcher       = ActionWatcher()

    # ── 3. Shared exit handler ────────────────────────────────────────
    def _on_exit() -> None:
        watcher.shutdown()
        controller.shutdown()
        overlay.hide_overlay()
        app.quit()

    # ── 4. HUD navigation signals ─────────────────────────────────────
    hud.next_clicked.connect(controller.next_step)
    hud.back_clicked.connect(controller.prev_step)
    hud.exit_clicked.connect(_on_exit)

    # Pause: hide spotlight/dim/tooltip but keep HUD visible
    hud.paused.connect(layer_manager.set_paused)

    # ── 5. Async coord-resolution signals ────────────────────────────
    controller.coords_resolved.connect(layer_manager.on_coords_resolved)
    controller.resolution_failed.connect(layer_manager.show_resolution_failed)

    # ── 5b. ActionWatcher — auto-advance on menu/dialog/focus events ──
    # Start watching once real coords are known; stop on any navigation.
    def _on_coords_resolved(step) -> None:
        layer_manager.on_coords_resolved(step)
        if step.coords:
            l, t, r, b = step.coords
            watcher.start_watching(QRect(l, t, r - l, b - t))

    controller.coords_resolved.disconnect(layer_manager.on_coords_resolved)
    controller.coords_resolved.connect(_on_coords_resolved)

    watcher.action_detected.connect(controller.next_step)

    # Stop the watcher whenever the user navigates manually (or exits)
    def _stop_watcher() -> None:
        watcher.stop_watching()

    hud.next_clicked.connect(_stop_watcher)
    hud.back_clicked.connect(_stop_watcher)
    controller.task_completed.connect(watcher.shutdown)

    # Pause also stops watching (no ghost advances while paused)
    def _on_pause(is_paused: bool) -> None:
        layer_manager.set_paused(is_paused)
        if is_paused:
            watcher.stop_watching()

    hud.paused.disconnect(layer_manager.set_paused)
    hud.paused.connect(_on_pause)

    # ── 6. Step-counter: HUD + window title ──────────────────────────
    def _on_step_changed(index: int, total: int) -> None:
        hud.update_progress(index, total)
        overlay.setWindowTitle(f"AI Overlay — Step {index + 1} of {total}")

    controller.step_changed.connect(_on_step_changed)
    controller.task_completed.connect(_on_exit)

    # ── 7. Keyboard shortcuts (ApplicationShortcut — focus independent) ─
    sc_next = QShortcut(QKeySequence(Qt.Key.Key_Right), overlay)
    sc_next.setContext(Qt.ShortcutContext.ApplicationShortcut)
    sc_next.activated.connect(controller.next_step)

    sc_prev = QShortcut(QKeySequence(Qt.Key.Key_Left), overlay)
    sc_prev.setContext(Qt.ShortcutContext.ApplicationShortcut)
    sc_prev.activated.connect(controller.prev_step)

    sc_exit = QShortcut(QKeySequence(Qt.Key.Key_Escape), overlay)
    sc_exit.setContext(Qt.ShortcutContext.ApplicationShortcut)
    sc_exit.activated.connect(_on_exit)

    # ── 8. Task-input dialog ──────────────────────────────────────────
    dialog = TaskInputDialog(api_key=_GEMINI_API_KEY)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    def _on_task_ready(path: str) -> None:
        """Called when Gemini finishes and the task JSON file is saved."""
        dialog.hide()
        controller.load_task(path)
        overlay.show_overlay()

    dialog.task_ready.connect(_on_task_ready)

    # Quit if the user closes the dialog before a task is started
    def _on_dialog_closed() -> None:
        if not overlay.isVisible():
            controller.shutdown()
            app.quit()

    app.lastWindowClosed.connect(_on_dialog_closed)

    # ── 9. Show the input dialog ──────────────────────────────────────
    dialog.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
