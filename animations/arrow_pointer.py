"""Animated arrow pointer that bounces toward the spotlight target.

The arrow eases in from off-screen (or from outside the spotlight), then
pulses gently in a continuous loop to hold the user's attention.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    QSequentialAnimationGroup,
    Qt,
    QVariantAnimation,
    pyqtProperty,
    pyqtSlot,
    QObject,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPen,
    QPolygonF,
    QTransform,
)

from core.step import Step

# ---------------------------------------------------------------------------
# Visual constants
# ---------------------------------------------------------------------------

_ARROW_COLOR      = QColor("#FFD700")          # golden yellow fill
_OUTLINE_COLOR    = QColor("#3A2A00")          # dark brownish outline
_OUTLINE_WIDTH    = 3.0

_HEAD_W: float    = 40.0   # arrowhead base width
_HEAD_H: float    = 44.0   # arrowhead height
_SHAFT_W: float   = 16.0   # shaft width
_SHAFT_H: float   = 30.0   # shaft length

# Distance from spotlight edge at which the arrow rests after bouncing in
_REST_GAP: int    = 28

# Bounce animation
_BOUNCE_DURATION_MS: int = 480
_BOUNCE_START_OFFSET: int = 80   # how far outside the rest position the arrow starts

# Pulse animation (scale)
_PULSE_DURATION_MS: int = 600
_PULSE_SCALE_MAX: float = 1.06


# ---------------------------------------------------------------------------
# Arrow geometry helpers
# ---------------------------------------------------------------------------

def _arrow_polygon(head_w: float, head_h: float, shaft_w: float, shaft_h: float) -> QPolygonF:
    """Return an upward-pointing arrow centred on the origin.

    The tip is at (0, 0).  The shaft extends downward.

        (0, 0)  ← tip
          /▲\\
         / | \\   ← head
        /__|__\\
           |       ← shaft
           |
          ---     ← base
    """
    hw = head_w / 2
    sw = shaft_w / 2

    points = [
        QPointF(0,         0),           # tip
        QPointF( hw,       head_h),      # head right
        QPointF( sw,       head_h),      # shaft top-right
        QPointF( sw,       head_h + shaft_h),  # shaft bottom-right
        QPointF(-sw,       head_h + shaft_h),  # shaft bottom-left
        QPointF(-sw,       head_h),      # shaft top-left
        QPointF(-hw,       head_h),      # head left
    ]
    return QPolygonF(points)


def _direction_angle(spotlight_rect: QRect, screen_rect: QRect) -> float:
    """Return the angle (degrees) the arrow should point, i.e. toward the target.

    Chooses the incoming direction based on available space:
    - If spotlight centre is in the right half of the screen → arrow comes from
      the left, pointing right (90°).
    - Otherwise → from the right, pointing left (270°).
    """
    cx = spotlight_rect.center().x()
    screen_mid = screen_rect.width() // 2
    # Angle is the direction the arrow TIP points (toward the target centre).
    # We rotate the upward-pointing arrow polygon to face this angle.
    return 90.0 if cx > screen_mid else 270.0


def _rest_position(spotlight_rect: QRect, angle_deg: float) -> QPointF:
    """Centre point of the arrow when it has finished bouncing in."""
    sr = spotlight_rect
    arrow_total_h = _HEAD_H + _SHAFT_H
    half = arrow_total_h / 2

    if abs(angle_deg - 90.0) < 1:
        # Arrow points right → comes from the left of the spotlight
        x = float(sr.left() - _REST_GAP - half)
        y = float(sr.center().y())
    else:
        # Arrow points left → comes from the right
        x = float(sr.right() + _REST_GAP + half)
        y = float(sr.center().y())
    return QPointF(x, y)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ArrowPointer(QObject):
    """Bouncing, pulsing arrow animation rendered on an :class:`~core.layers.animation_layer.AnimationLayer`.

    Parameters
    ----------
    layer:
        The ``AnimationLayer`` instance to paint onto.
    """

    def __init__(self, layer) -> None:  # layer: AnimationLayer
        super().__init__(layer)
        self._layer = layer

        # Internal animation state
        self._offset: float = 0.0   # bounce offset in pixels along the approach axis
        self._scale:  float = 1.0   # pulse scale multiplier
        self._angle:  float = 90.0  # rotation of the arrow (degrees)
        self._rest:   QPointF = QPointF(0.0, 0.0)
        self._active: bool = False

        # ── Bounce-in animation ───────────────────────────────────────
        self._bounce_anim = QVariantAnimation(self)
        self._bounce_anim.setDuration(_BOUNCE_DURATION_MS)
        self._bounce_anim.setEasingCurve(QEasingCurve.Type.OutBounce)
        self._bounce_anim.valueChanged.connect(lambda v: self._on_offset_changed(v))
        self._bounce_anim.finished.connect(self._start_pulse)

        # ── Pulse animation group ─────────────────────────────────────
        scale_up = QVariantAnimation(self)
        scale_up.setDuration(_PULSE_DURATION_MS)
        scale_up.setStartValue(1.0)
        scale_up.setEndValue(_PULSE_SCALE_MAX)
        scale_up.setEasingCurve(QEasingCurve.Type.InOutSine)
        scale_up.valueChanged.connect(lambda v: self._on_scale_changed(v))

        scale_down = QVariantAnimation(self)
        scale_down.setDuration(_PULSE_DURATION_MS)
        scale_down.setStartValue(_PULSE_SCALE_MAX)
        scale_down.setEndValue(1.0)
        scale_down.setEasingCurve(QEasingCurve.Type.InOutSine)
        scale_down.valueChanged.connect(lambda v: self._on_scale_changed(v))

        self._pulse_group = QSequentialAnimationGroup(self)
        self._pulse_group.addAnimation(scale_up)
        self._pulse_group.addAnimation(scale_down)
        self._pulse_group.setLoopCount(-1)   # loop forever

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, step: Step) -> None:
        """Start the arrow animation for *step*.

        Parameters
        ----------
        step:
            The step whose ``coords`` defines where the arrow should point.
            If ``coords`` is ``None`` the animation is a no-op.
        """
        if step.coords is None:
            return

        x, y, w, h = step.coords
        spotlight = QRect(x, y, w, h)
        screen = self._layer.rect()

        self._angle = _direction_angle(spotlight, screen)
        self._rest  = _rest_position(spotlight, self._angle)
        self._active = True

        # Bounce from `_BOUNCE_START_OFFSET` pixels away → 0 (rest position)
        self._bounce_anim.stop()
        self._pulse_group.stop()
        self._bounce_anim.setStartValue(float(_BOUNCE_START_OFFSET))
        self._bounce_anim.setEndValue(0.0)
        self._bounce_anim.start()

        self._layer.set_paint_callback(self._paint)

    def stop(self) -> None:
        """Stop all animations and clear the layer."""
        self._active = False
        self._bounce_anim.stop()
        self._pulse_group.stop()
        self._layer.set_paint_callback(None)

    # ------------------------------------------------------------------
    # Animation value slots
    # ------------------------------------------------------------------

    @pyqtSlot(object)
    def _on_offset_changed(self, value: object) -> None:
        self._offset = float(value)  # type: ignore[arg-type]
        self._layer.update()

    @pyqtSlot(object)
    def _on_scale_changed(self, value: object) -> None:
        self._scale = float(value)  # type: ignore[arg-type]
        self._layer.update()

    @pyqtSlot()
    def _start_pulse(self) -> None:
        if self._active:
            self._offset = 0.0
            self._pulse_group.start()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def _paint(self, painter: QPainter) -> None:
        """Draw the arrow onto *painter* (called by AnimationLayer.paintEvent)."""
        if not self._active:
            return

        # Compute current arrow centre: start at rest, apply offset along
        # the approach axis (opposite direction of the arrow tip).
        angle_rad = math.radians(self._angle)
        # approach direction is anti-parallel to where the tip points
        dx = -math.cos(angle_rad) * self._offset
        dy = -math.sin(angle_rad) * self._offset
        centre = QPointF(self._rest.x() + dx, self._rest.y() + dy)

        painter.save()
        painter.translate(centre)
        painter.rotate(self._angle - 90.0)   # upward polygon → rotate to face angle
        painter.scale(self._scale, self._scale)

        polygon = _arrow_polygon(_HEAD_W, _HEAD_H, _SHAFT_W, _SHAFT_H)

        # Dark outline
        painter.setPen(QPen(_OUTLINE_COLOR, _OUTLINE_WIDTH, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QBrush(_ARROW_COLOR))
        painter.drawPolygon(polygon)

        painter.restore()

