"""Layer orchestrator with smooth step-to-step transition animations.

Transition sequence for render_step():
  Phase 1 (parallel, 150 ms): fade-out spotlight + tooltip
  Phase 2 (parallel, 300 ms): move spotlight rect + fade-in dim at new position
  Phase 3 (parallel, 150 ms): fade-in tooltip at new position
After transition: start per-step animation (pulse / arrow / none)
"""
from __future__ import annotations

import dataclasses

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QRect,
    QSequentialAnimationGroup,
    QVariantAnimation,
    pyqtSlot,
)

from animations.arrow_pointer import ArrowPointer
from animations.spotlight_pulse import SpotlightPulse
from core.layers.animation_layer import AnimationLayer
from core.layers.dim_layer import DimLayer
from core.layers.hud_layer import HUDLayer
from core.layers.spotlight_layer import SpotlightLayer
from core.layers.tooltip_layer import TooltipLayer
from core.step import Step

# Animation durations (ms)
_FADE_OUT_MS  = 150
_MOVE_MS      = 300
_FADE_IN_MS   = 150


def _coords_to_rect(coords: tuple[int, int, int, int], padding: int = 0) -> QRect:
    left, top, right, bottom = coords
    w = right - left
    h = bottom - top
    return QRect(left - padding, top - padding, w + padding * 2, h + padding * 2)


class LayerManager(QObject):
    """Owns and orchestrates all overlay layers with animated step transitions.

    Transition sequence (``render_step`` when a previous step exists):

    ┌─ Phase 1 : 150 ms ────────────────────────────────────────────────┐
    │  PARALLEL: spotlight opacity 1→0   │  tooltip opacity 1→0        │
    └───────────────────────────────────────────────────────────────────┘
    ┌─ Phase 2 : 300 ms ────────────────────────────────────────────────┐
    │  spotlight rect lerp old→new  (ease-in-out)                      │
    └───────────────────────────────────────────────────────────────────┘
    ┌─ Phase 3 : 150 ms ────────────────────────────────────────────────┐
    │  spotlight opacity 0→1   │  tooltip opacity 0→1                  │
    └───────────────────────────────────────────────────────────────────┘
    → per-step animation started (pulse / arrow / none)

    Parameters
    ----------
    overlay:
        The :class:`~core.overlay_window.OverlayWindow` parent widget.
    """

    def __init__(self, overlay) -> None:
        super().__init__()
        # ── Layers ────────────────────────────────────────────────────
        self._dim        = DimLayer(overlay)
        self._spotlight  = SpotlightLayer(overlay)
        self._tooltip    = TooltipLayer(overlay)
        self._anim_layer = AnimationLayer(overlay)
        self._hud        = HUDLayer(overlay)

        # ── Animators ─────────────────────────────────────────────────
        self._pulse = SpotlightPulse(self._spotlight)
        self._spotlight.attach_pulse(self._pulse)
        self._arrow = ArrowPointer(self._anim_layer)

        overlay.set_child_layers([
            self._dim, self._spotlight, self._anim_layer, self._tooltip, self._hud
        ])
        self._dim.hide()  # Redundant; SpotlightLayer draws its own dim
        # screen_rect = overlay.rect()
        # for layer in [self._dim, self._spotlight, self._anim_layer, self._tooltip, self._hud]:
        #     layer.setGeometry(screen_rect)
        #     layer.show()

        # Z-order: dim → spotlight → anim → tooltip (interactive on top)
        self._dim.raise_()
        self._spotlight.raise_()
        self._anim_layer.raise_()
        self._tooltip.raise_()
        self._hud.raise_()

        # ── Internal state ────────────────────────────────────────────
        self._current_step: Step | None = None
        self._transition: QSequentialAnimationGroup | None = None

        # Cached opacity values driven by animations (0.0 – 1.0)
        self._spotlight_opacity: float = 1.0
        self._tooltip_opacity:   float = 1.0

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def tooltip_layer(self) -> TooltipLayer:
        """The tooltip card layer (read-only, no navigation buttons)."""
        return self._tooltip

    @property
    def hud_layer(self) -> HUDLayer:
        """The HUD control bar layer."""
        return self._hud

    # ------------------------------------------------------------------
    # Pause / resume
    # ------------------------------------------------------------------

    def set_paused(self, paused: bool) -> None:
        """Pause (hide dim/spotlight/tooltip) or resume (re-show and re-render).

        The HUD stays visible at all times.

        Parameters
        ----------
        paused:
            ``True`` to hide the overlay content; ``False`` to restore it.
        """
        self._dim.setVisible(not paused)
        self._spotlight.setVisible(not paused)
        self._tooltip.setVisible(not paused)
        self._anim_layer.setVisible(not paused)

        if not paused and self._current_step is not None:
            # Re-render current step content on resume
            self._render_immediate(self._current_step)
            self._start_step_animation(self._current_step)

    # ------------------------------------------------------------------
    # TaskController interface
    # ------------------------------------------------------------------

    def render_step(self, step: Step) -> None:
        """Render *step*, animating the transition from the previous step.

        If no previous step exists the layers are shown immediately.
        """
        old_step = self._current_step
        self._current_step = step

        # Stop any running per-step animation
        self._pulse.stop()
        self._arrow.stop()

        if old_step is None or old_step.coords is None or step.coords is None:
            # No previous coords — skip transition, render directly
            self._render_immediate(step)
            self._start_step_animation(step)
            return

        self._animate_transition(old_step, step)

    def show_locating(self, step: Step) -> None:
        """Show dim + placeholder tooltip while coords are being resolved."""
        self._stop_transition()
        self._pulse.stop()
        self._arrow.stop()

        self._dim.set_opacity(0.55)
        # self._dim.render(step)  # disabled
        self._spotlight.clear()

        locating_step = dataclasses.replace(
            step, tooltip=f"\u201cLocating {step.target}\u2026\u201d"
        )
        self._tooltip.render(locating_step)
        self._set_spotlight_opacity(1.0)
        self._set_tooltip_opacity(1.0)

        # self._dim.show()  # disabled: SpotlightLayer draws its own dim
        self._spotlight.show()
        self._tooltip.show()

    def show_resolution_failed(self, target: str) -> None:
        """Show the manual-click fallback message."""
        self._tooltip.show_message(
            f"\u26a0\ufe0f Couldn\u2019t find \u201c{target}\u201d \u2014 please click it manually"
        )

    def clear_all(self) -> None:
        """Reset every layer and stop all animations."""
        self._stop_transition()
        self._pulse.stop()
        self._arrow.stop()
        self._current_step = None

        self._dim.clear()
        self._spotlight.clear()
        self._tooltip.clear()
        self._anim_layer.clear()

        self._dim.hide()
        self._spotlight.hide()
        self._tooltip.hide()
        self._anim_layer.hide()

    # ------------------------------------------------------------------
    # Slot — wired to TaskController.coords_resolved in main.py
    # ------------------------------------------------------------------

    @pyqtSlot(object)
    def on_coords_resolved(self, step: Step) -> None:
        """Re-render with real coords once background resolution completes."""
        self.render_step(step)

    # ------------------------------------------------------------------
    # Transition orchestration
    # ------------------------------------------------------------------

    def _animate_transition(self, old_step: Step, new_step: Step) -> None:
        """Build and run the three-phase transition animation group."""
        self._stop_transition()

        old_rect = _coords_to_rect(old_step.coords)   # type: ignore[arg-type]
        new_rect = _coords_to_rect(new_step.coords)   # type: ignore[arg-type]

        # ── Prepare new tooltip content (hidden at first) ─────────────
        self._tooltip.render(new_step)
        self._set_tooltip_opacity(1.0)   # will be driven by animation

        # ── Phase 1: parallel fade-out (150 ms) ───────────────────────
        fade_out = QParallelAnimationGroup()

        spot_out = self._make_opacity_anim(
            1.0, 0.0, _FADE_OUT_MS, self._set_spotlight_opacity
        )
        tip_out = self._make_opacity_anim(
            1.0, 0.0, _FADE_OUT_MS, self._set_tooltip_opacity
        )
        fade_out.addAnimation(spot_out)
        fade_out.addAnimation(tip_out)

        # ── Phase 2: spotlight rect move (300 ms, ease-in-out) ────────
        move = self._make_rect_anim(old_rect, new_rect, _MOVE_MS)

        # ── Phase 3: parallel fade-in (150 ms) ───────────────────────
        fade_in = QParallelAnimationGroup()

        spot_in = self._make_opacity_anim(
            0.0, 1.0, _FADE_IN_MS, self._set_spotlight_opacity
        )
        tip_in = self._make_opacity_anim(
            0.0, 1.0, _FADE_IN_MS, self._set_tooltip_opacity
        )
        fade_in.addAnimation(spot_in)
        fade_in.addAnimation(tip_in)

        # ── Sequence ──────────────────────────────────────────────────
        seq = QSequentialAnimationGroup()
        seq.addAnimation(fade_out)
        seq.addAnimation(move)
        seq.addAnimation(fade_in)

        # Kick off per-step animation after everything finishes
        seq.finished.connect(lambda: self._start_step_animation(new_step))

        self._transition = seq
        seq.start()

        # Make sure layers are visible
        # self._dim.show()  # disabled: SpotlightLayer draws its own dim
        self._spotlight.show()
        self._tooltip.show()

    # ------------------------------------------------------------------
    # Animation factories
    # ------------------------------------------------------------------

    @staticmethod
    def _make_opacity_anim(
        start: float,
        end: float,
        duration_ms: int,
        setter,
    ) -> QVariantAnimation:
        anim = QVariantAnimation()
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setDuration(duration_ms)
        anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        anim.valueChanged.connect(lambda v: setter(float(v)))
        return anim

    def _make_rect_anim(
        self,
        start_rect: QRect,
        end_rect: QRect,
        duration_ms: int,
    ) -> QVariantAnimation:
        """Animate the spotlight rect from *start_rect* to *end_rect*."""
        anim = QVariantAnimation()
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(duration_ms)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        def _lerp_rect(t: float) -> None:
            """Linearly interpolate between start and end QRects."""
            lerp = lambda a, b: int(a + (b - a) * t)  # noqa: E731
            rect = QRect(
                lerp(start_rect.x(),      end_rect.x()),
                lerp(start_rect.y(),      end_rect.y()),
                lerp(start_rect.width(),  end_rect.width()),
                lerp(start_rect.height(), end_rect.height()),
            )
            # Update spotlight rect directly (bypasses set_spotlight padding — rect is pre-padded)
            self._spotlight._spotlight_rect = rect  # noqa: SLF001
            self._spotlight.update()

        anim.valueChanged.connect(lambda v: _lerp_rect(float(v)))
        return anim

    # ------------------------------------------------------------------
    # Per-step animation dispatch
    # ------------------------------------------------------------------

    def _start_step_animation(self, step: Step) -> None:
        """Start pulse, arrow, or nothing based on ``step.animation``."""
        anim_type = (step.animation or "none").lower()

        if anim_type == "pulse":
            # Pulse is attached to SpotlightLayer; start it if coords present
            if step.coords is not None and self._pulse is not None:
                from PyQt6.QtCore import QRect as _QR
                sr = _coords_to_rect(step.coords)
                self._pulse.start(sr)

        elif anim_type == "arrow":
            self._anim_layer.show()
            self._arrow.start(step)

        # "none" or unknown → do nothing

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _render_immediate(self, step: Step) -> None:
        """Render without any transition animation."""
        self._dim.set_opacity(0.55)
        # self._dim.render(step)  # disabled
        self._spotlight.render(step)
        self._tooltip.render(step)
        self._set_spotlight_opacity(1.0)
        self._set_tooltip_opacity(1.0)

        # self._dim.show()  # disabled: SpotlightLayer draws its own dim
        self._spotlight.show()
        self._tooltip.show()

    def _stop_transition(self) -> None:
        """Abort any running transition animation."""
        if self._transition is not None:
            self._transition.stop()
            self._transition = None

    def _set_spotlight_opacity(self, opacity: float) -> None:
        """Drive spotlight + dim opacity together (they fade as a unit)."""
        self._spotlight_opacity = opacity
        # SpotlightLayer internal _opacity is the dim's alpha.
        # Scale it so 1.0 driving value = 0.55 actual alpha.
        self._spotlight.set_opacity(opacity * 0.55)

    def _set_tooltip_opacity(self, opacity: float) -> None:
        self._tooltip_opacity = opacity
        self._tooltip.set_opacity(opacity)

