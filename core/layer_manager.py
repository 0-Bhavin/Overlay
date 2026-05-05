"""LayerManager — orchestrates OverlayWindow, TooltipLayer, and HUDLayer.

Wires:
    1.1  Pulse animation start/stop when resolving.
    1.3  Step-complete flash before advancing.
    1.5  TTS speak on each step render.
"""
from __future__ import annotations

import dataclasses

from PyQt6.QtCore import QObject, QRect, pyqtSignal, pyqtSlot

from core.layers.hud_layer import HUDLayer
from core.layers.tooltip_layer import TooltipLayer
from core.step import Step


def _coords_to_rect(coords: tuple[int, int, int, int], padding: int = 0) -> QRect:
    l, t, r, b = coords

    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    dpr = 1.0
    if app is not None and app.primaryScreen() is not None:
        dpr = app.primaryScreen().devicePixelRatio()

    return QRect(
        int((l - padding) / dpr),
        int((t - padding) / dpr),
        int(((r - l) + padding * 2) / dpr),
        int(((b - t) + padding * 2) / dpr),
    )


class LayerManager(QObject):
    """Orchestrator with pulse animation, step flash, and TTS support."""

    # Emitted after the flash animation finishes — callers can connect
    # their "advance to next step" logic here.
    step_complete_done: pyqtSignal = pyqtSignal()

    def __init__(self, overlay, tts=None) -> None:
        """
        Parameters
        ----------
        overlay:
            The :class:`~core.overlay_window.OverlayWindow` instance.
        tts:
            Optional :class:`~core.tts.TTSEngine` instance for feature 1.5.
            Pass ``None`` to disable TTS.
        """
        super().__init__()
        self._overlay = overlay
        self._tts = tts

        self._tooltip = TooltipLayer(overlay)
        self._hud     = HUDLayer(overlay)

        overlay.set_child_layers([self._tooltip, self._hud])

        self._tooltip.raise_()
        self._hud.raise_()

        self._current_step: Step | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def tooltip_layer(self) -> TooltipLayer:
        return self._tooltip

    @property
    def hud_layer(self) -> HUDLayer:
        return self._hud

    # ------------------------------------------------------------------
    # Pause / resume
    # ------------------------------------------------------------------

    def set_paused(self, paused: bool) -> None:
        self._tooltip.setVisible(not paused)
        self._overlay.set_resolving(False)   # stop pulse while paused
        if paused:
            self._overlay.clear_spotlight()
        else:
            if self._current_step:
                self.render_step(self._current_step)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_step(self, step: Step) -> None:
        """Render a fully-resolved step (coords are known)."""
        self._current_step = step
        self._overlay.set_resolving(False)   # 1.1 — stop pulse

        if step.coords is not None:
            rect = _coords_to_rect(step.coords)
            self._overlay.set_spotlight(rect, 0.55)
        else:
            self._overlay.set_spotlight(None, 0.55)

        self._tooltip.render(step)
        self._tooltip.show()

        # 1.5 — read tooltip aloud
        if self._tts is not None:
            self._tts.speak(step.tooltip)

    def show_locating(self, step: Step) -> None:
        """Show dim + 'Locating…' tooltip + pulse rings while resolving (1.1)."""
        self._overlay.set_spotlight(None, 0.55)
        self._overlay.set_resolving(True)    # 1.1 — start pulse

        locating_step = dataclasses.replace(
            step, tooltip=f"\u201cLocating {step.target}\u2026\u201d"
        )
        self._tooltip.render(locating_step)
        self._tooltip.show()

    def show_resolution_failed(self, target: str) -> None:
        self._overlay.set_resolving(False)   # 1.1 — stop pulse on failure
        self._tooltip.show_message(
            f"\u26a0\ufe0f Couldn\u2019t find \u201c{target}\u201d \u2014 please click it manually"
        )

    # ------------------------------------------------------------------
    # 1.3  Step-complete flash
    # ------------------------------------------------------------------

    def flash_step_complete(self, callback=None) -> None:
        """Show a green ✓ flash on the spotlight, then call *callback*."""
        self._overlay.show_step_complete_flash(callback)

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear_all(self) -> None:
        self._current_step = None
        self._overlay.set_resolving(False)
        self._overlay.clear_spotlight()
        self._tooltip.clear()
        self._tooltip.hide()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @pyqtSlot(object)
    def on_coords_resolved(self, step: Step) -> None:
        self.render_step(step)
