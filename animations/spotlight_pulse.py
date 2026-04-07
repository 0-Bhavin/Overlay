"""Pulsing ring animation drawn on top of the spotlight hole.

:class:`SpotlightPulse` drives a looping animation that expands a rounded
ring outward from the spotlight boundary while fading to transparent, giving
the user a clear visual cue about where to look / click.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, QRect, QTimer
from PyQt6.QtWidgets import QWidget

# ---------------------------------------------------------------------------
# Animation constants (all tuneable)
# ---------------------------------------------------------------------------

_FPS: int = 60                  # target frame rate
_INTERVAL_MS: int = 1000 // _FPS

_MAX_EXPANSION_PX: int = 20     # ring expands this many px outward
_START_ALPHA: float = 0.60      # opacity at the spotlight boundary (0–1)
_END_ALPHA: float = 0.0         # opacity at full expansion
_LOOP_DURATION_MS: int = 1000   # one full pulse takes this long (ms)

_TOTAL_FRAMES: int = (_LOOP_DURATION_MS * _FPS) // 1000


class SpotlightPulse(QObject):
    """Looping pulse-ring animation rendered onto a :class:`~core.layers.spotlight_layer.SpotlightLayer`.

    The ring expands from the spotlight boundary outward by
    :data:`_MAX_EXPANSION_PX` pixels while fading from
    :data:`_START_ALPHA` to :data:`_END_ALPHA` opacity, then restarts.

    Parameters
    ----------
    layer:
        The ``SpotlightLayer`` instance to draw onto.  The pulse calls
        ``layer.update()`` on every frame, triggering a ``paintEvent`` in
        which the layer calls :meth:`draw_pulse`.
    color:
        RGB tuple ``(r, g, b)`` for the ring.  Defaults to white.
    """

    def __init__(
        self,
        layer: QWidget,
        color: tuple[int, int, int] = (255, 255, 255),
    ) -> None:
        super().__init__(layer)   # parent = layer, cleaned up automatically
        self._layer = layer
        self._color = color
        self._rect: QRect | None = None
        self._frame: int = 0

        self._timer = QTimer(self)
        self._timer.setInterval(_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, rect: QRect) -> None:
        """Start (or restart) the pulse animation around *rect*.

        Parameters
        ----------
        rect:
            The spotlight area (already padded) in layer-local coordinates.
        """
        self._rect = rect
        self._frame = 0
        self._timer.start()

    def stop(self) -> None:
        """Stop the animation and request one final repaint to clear the ring."""
        self._timer.stop()
        self._rect = None
        self._layer.update()

    # ------------------------------------------------------------------
    # Current animation state (read by SpotlightLayer.draw_pulse)
    # ------------------------------------------------------------------

    @property
    def rect(self) -> QRect | None:
        """The spotlight rect being animated, or ``None`` when inactive."""
        return self._rect

    @property
    def expansion(self) -> float:
        """Current outward expansion in pixels (0 … _MAX_EXPANSION_PX)."""
        if _TOTAL_FRAMES == 0:
            return 0.0
        progress = self._frame / _TOTAL_FRAMES   # 0.0 → 1.0
        return progress * _MAX_EXPANSION_PX

    @property
    def alpha(self) -> float:
        """Current ring opacity (0.0 … _START_ALPHA)."""
        if _TOTAL_FRAMES == 0:
            return 0.0
        progress = self._frame / _TOTAL_FRAMES
        return _START_ALPHA * (1.0 - progress)   # linear fade

    @property
    def color(self) -> tuple[int, int, int]:
        """Ring colour as ``(r, g, b)``."""
        return self._color

    @property
    def is_active(self) -> bool:
        """``True`` while the animation timer is running."""
        return self._timer.isActive()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """Advance one frame and request a repaint on the layer."""
        self._frame += 1
        if self._frame > _TOTAL_FRAMES:
            self._frame = 0   # loop
        self._layer.update()
