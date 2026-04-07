"""Transparent animation layer.

A full-screen :class:`~core.layers.base_layer.BaseLayer` that animations can
paint onto.  It has no content of its own — subclasses or external painters
(such as :class:`~animations.arrow_pointer.ArrowPointer`) drive repaints by
calling ``layer.update()``.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from core.layers.base_layer import BaseLayer
from core.step import Step


class AnimationLayer(BaseLayer):
    """Full-screen transparent layer dedicated to animations.

    * Mouse events pass through (``WA_TransparentForMouseEvents``).
    * ``paintEvent`` is a no-op by default — animations register a
      *paint callback* via :meth:`set_paint_callback` and are called from
      ``paintEvent`` with an active ``QPainter``.

    Parameters
    ----------
    parent:
        The overlay ``QWidget`` this layer belongs to.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._paint_callback = None   # callable(painter) | None

    # ------------------------------------------------------------------
    # Paint callback registration
    # ------------------------------------------------------------------

    def set_paint_callback(self, callback) -> None:
        """Register *callback* to be called during every ``paintEvent``.

        Parameters
        ----------
        callback:
            ``callable(QPainter) -> None``, or ``None`` to detach.
        """
        self._paint_callback = callback
        self.update()

    # ------------------------------------------------------------------
    # BaseLayer interface
    # ------------------------------------------------------------------

    def render(self, step: Step) -> None:  # noqa: ARG002
        """Trigger a repaint (actual drawing is done by the registered callback)."""
        self.update()

    def clear(self) -> None:
        """Detach the paint callback and repaint to transparent."""
        self._paint_callback = None
        super().clear()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        # First clear the layer to transparent.
        super().paintEvent(event)

        if self._paint_callback is None:
            return

        from PyQt6.QtGui import QPainter  # local import avoids circular issues
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self._paint_callback(painter)
        finally:
            painter.end()
