from __future__ import annotations

import dataclasses
from PyQt6.QtCore import QObject, QRect, pyqtSlot

from core.layers.hud_layer import HUDLayer
from core.layers.tooltip_layer import TooltipLayer
from core.step import Step

def _coords_to_rect(coords: tuple[int, int, int, int], padding: int = 0) -> QRect:
    l, t, r, b = coords
    
    # Scale physical pywinauto coordinates down to Qt logical coordinates
    # to counteract Qt 6's automatic High-DPI scaling.
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    dpr = 1.0
    if app is not None and app.primaryScreen() is not None:
        dpr = app.primaryScreen().devicePixelRatio()

    return QRect(
        int((l - padding) / dpr),
        int((t - padding) / dpr),
        int(((r - l) + padding * 2) / dpr),
        int(((b - t) + padding * 2) / dpr)
    )


class LayerManager(QObject):
    """Simplified orchestrator with no animations/transitions."""

    def __init__(self, overlay) -> None:
        super().__init__()
        self._overlay = overlay
        
        self._tooltip = TooltipLayer(overlay)
        self._hud = HUDLayer(overlay)

        overlay.set_child_layers([self._tooltip, self._hud])

        self._tooltip.raise_()
        self._hud.raise_()

        self._current_step: Step | None = None

    @property
    def tooltip_layer(self) -> TooltipLayer:
        return self._tooltip

    @property
    def hud_layer(self) -> HUDLayer:
        return self._hud

    def set_paused(self, paused: bool) -> None:
        self._tooltip.setVisible(not paused)
        if paused:
            self._overlay.clear_spotlight()
        else:
            if self._current_step:
                self.render_step(self._current_step)

    def render_step(self, step: Step) -> None:
        self._current_step = step
        
        if step.coords is not None:
            rect = _coords_to_rect(step.coords)
            self._overlay.set_spotlight(rect, 0.55)
        else:
            self._overlay.set_spotlight(None, 0.55)

        self._tooltip.render(step)
        self._tooltip.show()

    def show_locating(self, step: Step) -> None:
        self._overlay.set_spotlight(None, 0.55)

        locating_step = dataclasses.replace(
            step, tooltip=f"\u201cLocating {step.target}\u2026\u201d"
        )
        self._tooltip.render(locating_step)
        self._tooltip.show()

    def show_resolution_failed(self, target: str) -> None:
        self._tooltip.show_message(
            f"\u26a0\ufe0f Couldn\u2019t find \u201c{target}\u201d \u2014 please click it manually"
        )

    def clear_all(self) -> None:
        self._current_step = None
        self._overlay.clear_spotlight()
        self._tooltip.clear()
        self._tooltip.hide()

    @pyqtSlot(object)
    def on_coords_resolved(self, step: Step) -> None:
        self.render_step(step)
