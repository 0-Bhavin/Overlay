from __future__ import annotations

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from core.layers.base_layer import BaseLayer
from core.step import Step

_DEFAULT_OPACITY: float = 0.55
_CORNER_RADIUS: float = 8.0
_PULSE_PEN_WIDTH: float = 2.5


class SpotlightLayer(BaseLayer):
    """Dim overlay with a rounded, transparent 'hole' cut out at a target rect.

    The hole is carved using ``CompositionMode_DestinationOut`` so the
    composited result is genuinely transparent — the real UI shows through
    regardless of what is drawn beneath this layer.

    A :class:`~animations.spotlight_pulse.SpotlightPulse` can be attached
    after construction; when active it will call ``self.update()`` on each
    frame and the pulse ring is drawn during :meth:`paintEvent` via
    :meth:`draw_pulse`.

    Clicks pass straight through — this layer is purely visual.

    Parameters
    ----------
    parent:
        The overlay ``QWidget`` this layer belongs to.
    opacity:
        Dim opacity in ``[0.0, 1.0]``.  Defaults to ``0.55``.
    """

    def __init__(self, parent: QWidget, opacity: float = _DEFAULT_OPACITY) -> None:
        super().__init__(parent)
        self._opacity: float = max(0.0, min(1.0, opacity))
        self._spotlight_rect: QRect | None = None

        # Pulse animator — set via attach_pulse(); may be None
        self._pulse = None   # type: ignore[assignment]

        # Clicks must not be swallowed — let them reach the real UI below.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    # ------------------------------------------------------------------
    # Pulse attachment
    # ------------------------------------------------------------------

    def attach_pulse(self, pulse) -> None:  # type: ignore[type-arg]
        """Attach a :class:`~animations.spotlight_pulse.SpotlightPulse` instance.

        The pulse is started/stopped automatically when the spotlight rect
        changes.  Pass ``None`` to detach.

        Parameters
        ----------
        pulse:
            A ``SpotlightPulse`` instance, or ``None``.
        """
        if self._pulse is not None:
            self._pulse.stop()
        self._pulse = pulse
        # Immediately start if a spotlight rect is already active
        if self._pulse is not None and self._spotlight_rect is not None:
            self._pulse.start(self._spotlight_rect)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_opacity(self, opacity: float) -> None:
        """Set the dim opacity and schedule a repaint."""
        self._opacity = max(0.0, min(1.0, opacity))
        self.update()

    def set_spotlight(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        padding: int = 16,
    ) -> None:
        """Define the transparent hole position and trigger a repaint."""
        self._spotlight_rect = QRect(
            x - padding,
            y - padding,
            w + padding * 2,
            h + padding * 2,
        )
        if self._pulse is not None:
            self._pulse.start(self._spotlight_rect)
        self.update()

    # ------------------------------------------------------------------
    # BaseLayer interface
    # ------------------------------------------------------------------

    def render(self, step: Step) -> None:
        """Update the spotlight from *step*.coords and schedule a repaint."""
        if step.coords is not None:
            x, y, w, h = step.coords
            self.set_spotlight(x, y, w, h)
        else:
            self._spotlight_rect = None
            if self._pulse is not None:
                self._pulse.stop()
            self.update()

    def clear(self) -> None:
        """Remove the spotlight hole and repaint as a plain dim."""
        self._spotlight_rect = None
        if self._pulse is not None:
            self._pulse.stop()
        super().clear()

    # ------------------------------------------------------------------
    # Pulse drawing helper (called from paintEvent)
    # ------------------------------------------------------------------

    def draw_pulse(
        self,
        painter: QPainter,
        rect: QRect,
        alpha: float,
        expansion: float,
        color: tuple[int, int, int] = (255, 255, 255),
    ) -> None:
        """Draw a single expanding, fading ring frame.

        Called by :meth:`paintEvent` when the pulse animator is active.
        Uses ``CompositionMode_SourceOver`` so the ring composites on top
        of the dim without further erasing it.

        Parameters
        ----------
        painter:
            An active ``QPainter`` on this widget.
        rect:
            The spotlight rect (hole boundary) in local coordinates.
        alpha:
            Opacity of the ring in ``[0.0, 1.0]``.
        expansion:
            How many pixels the ring has expanded beyond *rect*.
        color:
            RGB tuple for the ring stroke.
        """
        if alpha <= 0 or expansion < 0:
            return

        # Restore normal compositing — ring sits on top of the dim
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceOver
        )

        ring_color = QColor(*color)
        ring_color.setAlphaF(max(0.0, min(1.0, alpha)))

        pen = QPen(ring_color, _PULSE_PEN_WIDTH)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Expand the rect symmetrically by `expansion` pixels
        exp = int(expansion)
        expanded = rect.adjusted(-exp, -exp, exp, exp)

        ring_path = QPainterPath()
        ring_path.addRoundedRect(
            expanded.toRectF()
            if hasattr(expanded, "toRectF")
            else expanded,
            _CORNER_RADIUS + expansion,
            _CORNER_RADIUS + expansion,
        )
        painter.drawPath(ring_path)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── 1. Draw the dimmed background with a hole ─────────────────
        # Use path subtraction for the most robust "hole" rendering across
        # different systems/compositors.
        dim_color = QColor(0, 0, 0)
        dim_color.setAlphaF(self._opacity)

        if self._spotlight_rect is not None:
            # Create a path for the full screen
            full_path = QPainterPath()
            full_path.addRect(self.rect().toRectF())

            # Create a path for the rounded hole
            hole_path = QPainterPath()
            hole_path.addRoundedRect(
                self._spotlight_rect.toRectF()
                if hasattr(self._spotlight_rect, "toRectF")
                else self._spotlight_rect,
                _CORNER_RADIUS,
                _CORNER_RADIUS,
            )

            # The background is the screen MINUS the hole
            dim_path = full_path.subtracted(hole_path)
            painter.fillPath(dim_path, dim_color)
        else:
            # No spotlight: just fill the whole screen
            painter.fillRect(self.rect(), dim_color)

        # ── 2. Draw pulse ring (if active) ────────────────────────────
        if (
            self._pulse is not None
            and self._pulse.is_active
            and self._pulse.rect is not None
        ):
            # Modulate pulse alpha by global layer opacity so it fades too
            pulse_alpha = self._pulse.alpha * (self._opacity / _DEFAULT_OPACITY if self._opacity < _DEFAULT_OPACITY else 1.0)
            self.draw_pulse(
                painter,
                self._pulse.rect,
                pulse_alpha,
                self._pulse.expansion,
                self._pulse.color,
            )

        painter.end()
