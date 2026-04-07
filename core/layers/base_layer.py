from __future__ import annotations

from abc import ABCMeta, abstractmethod

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QWidget

from core.step import Step


# PyQt6's internal metaclass (sip.wrappertype) and ABCMeta both want to be
# the metaclass of BaseLayer, which causes a "metaclass conflict" TypeError.
# The fix is a trivial combined metaclass that subclasses both.
class _BaseLayerMeta(type(QWidget), ABCMeta):
    pass


class BaseLayer(QWidget, metaclass=_BaseLayerMeta):
    """Abstract base for every composited overlay layer.

    Each concrete layer must implement :meth:`render` to draw itself for a
    given :class:`~core.step.Step`.  All shared setup (transparency,
    full-screen geometry, mouse-event policy) lives here so that subclasses
    stay focused on their own drawing logic.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)

        # ── Transparency ──────────────────────────────────────────────────
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # ── Full-screen geometry ──────────────────────────────────────────
        # Mirror the parent's geometry so this layer always covers the
        # entire overlay window, even before the first resizeEvent fires.
        self.setGeometry(parent.rect())

        # ── Ensure the layer is stacked above the parent's base surface ───
        self.raise_()

    # ------------------------------------------------------------------
    # Geometry tracking
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Keep the layer flush with its parent whenever the window resizes."""
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())  # type: ignore[union-attr]
        super().resizeEvent(event)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def render(self, step: Step) -> None:  # type: ignore[override]
        """Draw the layer content for *step*.

        Subclasses **must** override this method.  After updating internal
        state they should call ``self.update()`` to schedule a repaint.

        Parameters
        ----------
        step:
            The :class:`~core.step.Step` that describes what to display.
        """

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Reset the layer to a fully transparent, empty state.

        Clears any state the subclass may hold and schedules a repaint so
        the layer visually disappears without needing to hide/show it.
        Subclasses may call ``super().clear()`` and then reset their own
        fields.
        """
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """Default paint: fill with a fully transparent colour.

        Subclasses that do custom painting should call ``super().paintEvent(event)``
        first (or manually clear the region) to avoid ghost rendering from
        previous frames.
        """
        painter = QPainter(self)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_Clear
        )
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.end()

    # ------------------------------------------------------------------
    # Mouse events — accept by default; subclasses can pass through
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        event.accept()
