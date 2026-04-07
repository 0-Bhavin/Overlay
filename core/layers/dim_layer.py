from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget

from core.layers.base_layer import BaseLayer
from core.step import Step

_DEFAULT_OPACITY: float = 0.55


class DimLayer(BaseLayer):
    """Full-screen semi-transparent black overlay.

    Clicks pass straight through — this layer is purely visual.

    Parameters
    ----------
    parent:
        The overlay ``QWidget`` this layer belongs to.
    opacity:
        Initial dim opacity in the range ``[0.0, 1.0]``.
        Defaults to ``0.55``.
    """

    def __init__(self, parent: QWidget, opacity: float = _DEFAULT_OPACITY) -> None:
        super().__init__(parent)
        self._opacity: float = max(0.0, min(1.0, opacity))

        # Clicks must not be swallowed — let them reach the real UI below.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_opacity(self, opacity: float) -> None:
        """Set the dim opacity and schedule a repaint.

        Parameters
        ----------
        opacity:
            Value in ``[0.0, 1.0]``.  Clamped silently if out of range.
        """
        self._opacity = max(0.0, min(1.0, opacity))
        self.update()

    # ------------------------------------------------------------------
    # BaseLayer interface
    # ------------------------------------------------------------------

    def render(self, step: Step) -> None:  # noqa: ARG002
        """Show the dim overlay (step data unused by this layer)."""
        self.update()

    def clear(self) -> None:
        """Hide the dim overlay by setting opacity to 0 and repainting."""
        self._opacity = 0.0
        super().clear()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = QColor(0, 0, 0)
        color.setAlphaF(self._opacity)
        painter.fillRect(self.rect(), color)

        painter.end()
