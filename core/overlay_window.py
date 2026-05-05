"""Main overlay window — dim layer, spotlight hole, pulse animation, step-complete flash.

Features added:
    1.1  Animated pulsing ring while the resolver is working.
    1.3  Brief green flash confirming a step was completed.
    Z-fix Re-asserts HWND_TOPMOST every 150 ms so Word popups/task-panes
          cannot push the overlay behind them.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import math
import threading

from PyQt6.QtCore import QRect, QTimer, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget

# Windows SetWindowPos constants
_HWND_TOPMOST   = -1
_SWP_NOMOVE     = 0x0002
_SWP_NOSIZE     = 0x0001
_SWP_NOACTIVATE = 0x0010
_SWP_FLAGS      = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE

_DIM_OPACITY: float = 0.55
_CORNER_RADIUS: float = 8.0

# Pulse ring settings
_PULSE_RINGS   = 3
_PULSE_MAX_R   = 80      # px — maximum ring radius
_PULSE_TICK_MS = 30      # repaint interval while resolving

# Step-complete flash settings
_FLASH_DURATION_MS = 600


class OverlayWindow(QWidget):
    """Frameless, always-on-top, fully transparent window that covers the
    primary screen.

    On Windows, only the *top-level* window with ``WA_TranslucentBackground``
    actually achieves real per-pixel alpha compositing against the desktop.
    Child widgets do NOT get true transparency — they paint into an opaque
    child backing store.

    Therefore this window owns the dim-overlay + spotlight-hole rendering
    directly in its ``paintEvent``.  All other layers (tooltip, HUD) are
    child widgets stacked on top and rely purely on their own opaque-white or
    clearly-opaque drawing (no dim needed for them).
    """

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )

        # Real per-pixel alpha — this is what makes the dim transparent.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # The window itself must never steal clicks or hovers from the target app.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Stretch to the full primary screen immediately.
        screen_geometry = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_geometry)

        # ── Dim + spotlight state ──────────────────────────────────────
        self._spotlight_rect: QRect | None = None
        self._dim_opacity: float = 0.0   # 0 = invisible, 0.55 = active

        # ── 1.1  Pulse animation state ─────────────────────────────────
        self._resolving: bool = False
        self._pulse_phase: float = 0.0   # 0.0 → 1.0, cycles continuously
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(_PULSE_TICK_MS)
        self._pulse_timer.timeout.connect(self._tick_pulse)

        # ── 1.3  Step-complete flash state ────────────────────────────
        self._flash_alpha: float = 0.0   # 0 = no flash, 1 = full green
        self._flash_elapsed: int = 0
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(_PULSE_TICK_MS)
        self._flash_timer.timeout.connect(self._tick_flash)
        self._flash_callback = None

        # ── Z-order guard (event-driven, replaces polling timer) ──────
        # Word’s Watermark / Design task-panes are also TOPMOST windows.
        # Created AFTER our overlay they win the Z-order race.
        # We watch EVENT_SYSTEM_FOREGROUND + EVENT_OBJECT_SHOW on a
        # daemon thread so we re-assert HWND_TOPMOST the instant any
        # new window appears — far faster than a 150 ms timer.
        self._zorder_guard_active = False
        self._zorder_proc_ref    = None   # keep WINFUNCTYPE wrapper alive
        self._zorder_hook_handle = None
        self._zorder_thread: threading.Thread | None = None
        self._zorder_thread_id: int = 0
        # Fallback timer (50 ms) catches any events the hook misses
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(50)
        self._topmost_timer.timeout.connect(self._reassert_topmost)

    # ------------------------------------------------------------------
    # Dim / spotlight state API  (called by SpotlightLayer / LayerManager)
    # ------------------------------------------------------------------

    def set_spotlight(self, rect: QRect | None, dim_opacity: float = _DIM_OPACITY) -> None:
        """Set the spotlight hole rect and dim opacity, then repaint."""
        self._spotlight_rect = rect
        self._dim_opacity = max(0.0, min(1.0, dim_opacity))
        self.update()

    def clear_spotlight(self) -> None:
        """Remove the spotlight and make the dim invisible (fully transparent)."""
        self._spotlight_rect = None
        self._dim_opacity = 0.0
        self.update()

    # ------------------------------------------------------------------
    # 1.1  Pulse animation API
    # ------------------------------------------------------------------

    def set_resolving(self, resolving: bool) -> None:
        """Start/stop the pulsing ring animation shown while locating an element."""
        self._resolving = resolving
        if resolving:
            self._pulse_phase = 0.0
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
            self.update()

    def _tick_pulse(self) -> None:
        self._pulse_phase = (self._pulse_phase + 0.022) % 1.0
        self.update()

    # ------------------------------------------------------------------
    # 1.3  Step-complete flash API
    # ------------------------------------------------------------------

    def show_step_complete_flash(self, callback=None) -> None:
        """Flash a green confirmation over the spotlight, then call *callback*."""
        if self._flash_timer.isActive():
            self._flash_timer.stop()
        self._flash_alpha = 0.0
        self._flash_elapsed = 0
        self._flash_callback = callback
        self._flash_timer.start()

    def _tick_flash(self) -> None:
        self._flash_elapsed += _PULSE_TICK_MS
        t = self._flash_elapsed / _FLASH_DURATION_MS  # 0.0 → 1.0
        if t >= 1.0:
            self._flash_timer.stop()
            self._flash_alpha = 0.0
            self.update()
            if self._flash_callback:
                cb = self._flash_callback
                self._flash_callback = None
                cb()
            return
        # Triangle wave: rise then fall
        self._flash_alpha = 1.0 - abs(t * 2.0 - 1.0)
        self.update()

    # ------------------------------------------------------------------
    # Paint: dim overlay + spotlight hole + pulse + flash
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Dim layer
        if self._dim_opacity > 0.0:
            dim_color = QColor(0, 0, 0, int(self._dim_opacity * 255))
            painter.fillRect(self.rect(), dim_color)

        if self._spotlight_rect is not None and self._dim_opacity > 0.0:
            # 2. Punch a clean hole
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self._spotlight_rect, Qt.GlobalColor.transparent)

            # 3. Border around the spotlight hole
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(QColor(255, 255, 255, 200), 2)
            painter.setPen(pen)
            painter.drawRect(self._spotlight_rect)

            # 4. Step-complete green flash (1.3)
            if self._flash_alpha > 0.0:
                flash_color = QColor(166, 227, 161, int(self._flash_alpha * 180))
                painter.fillRect(self._spotlight_rect, flash_color)
                # Draw "✓" text centred on the spotlight
                check_font = painter.font()
                check_font.setPointSize(32)
                check_font.setBold(True)
                painter.setFont(check_font)
                painter.setPen(QColor(255, 255, 255, int(self._flash_alpha * 255)))
                painter.drawText(self._spotlight_rect, Qt.AlignmentFlag.AlignCenter, "✓")

        # 5. Pulse rings while resolving (1.1) — drawn in centre of screen
        if self._resolving:
            cx = self.width()  // 2
            cy = self.height() // 2
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            for i in range(_PULSE_RINGS):
                phase = (self._pulse_phase + i / _PULSE_RINGS) % 1.0
                radius = phase * _PULSE_MAX_R
                alpha  = int((1.0 - phase) * 160)
                ring_color = QColor(137, 180, 250, alpha)   # Catppuccin blue
                pen = QPen(ring_color, 2.5)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(int(cx - radius), int(cy - radius),
                                    int(radius * 2), int(radius * 2))

        painter.end()

    # ------------------------------------------------------------------
    # Z-order: instant re-assertion via WinEvent hook + 50 ms fallback
    # ------------------------------------------------------------------

    # WINFUNCTYPE for the WinEvent hook callback
    _WinEventProc = ctypes.WINFUNCTYPE(
        None,
        ctypes.wintypes.HANDLE,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LONG,
        ctypes.wintypes.LONG,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
    )

    # WinEvent codes we care about
    _EV_FOREGROUND = 0x0003   # EVENT_SYSTEM_FOREGROUND
    _EV_OBJ_SHOW   = 0x8002   # EVENT_OBJECT_SHOW

    def _reassert_topmost(self) -> None:
        """Call SetWindowPos(HWND_TOPMOST) without activating the window."""
        try:
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowPos(
                hwnd, _HWND_TOPMOST,
                0, 0, 0, 0,
                _SWP_FLAGS,
            )
        except Exception:  # noqa: BLE001
            pass

    def _on_zorder_event(
        self,
        h_hook, event: int, hwnd,
        id_object: int, id_child: int,
        id_thread: int, dw_time: int,
    ) -> None:
        """WinEvent callback — fires instantly when any window is shown or
        gains foreground.  Schedules _reassert_topmost() on the Qt main thread
        (QTimer.singleShot is thread-safe in PyQt6).
        """
        if not self._zorder_guard_active:
            return
        if event in (self._EV_FOREGROUND, self._EV_OBJ_SHOW):
            # Only react to top-level windows (idObject == 0 = OBJID_WINDOW)
            if id_object == 0:
                QTimer.singleShot(0, self._reassert_topmost)

    def _start_zorder_guard(self) -> None:
        """Install WinEvent hook on a daemon thread and start the fallback timer."""
        if self._zorder_guard_active:
            return
        self._zorder_guard_active = True

        proc = self._WinEventProc(self._on_zorder_event)
        self._zorder_proc_ref = proc   # prevent GC

        def _loop() -> None:
            self._zorder_thread_id = threading.current_thread().ident  # type: ignore[assignment]
            handle = ctypes.windll.user32.SetWinEventHook(
                self._EV_FOREGROUND,   # event min
                self._EV_OBJ_SHOW,     # event max
                None,
                proc,
                0, 0,                  # all processes / threads
                0x0000,                # WINEVENT_OUTOFCONTEXT
            )
            self._zorder_hook_handle = handle
            msg = ctypes.wintypes.MSG()
            while ctypes.windll.user32.GetMessageW(
                ctypes.byref(msg), None, 0, 0
            ) > 0:
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
            if handle:
                ctypes.windll.user32.UnhookWinEvent(handle)
                self._zorder_hook_handle = None

        self._zorder_thread = threading.Thread(
            target=_loop, daemon=True, name="ZOrderGuard"
        )
        self._zorder_thread.start()
        self._topmost_timer.start()   # 50 ms fallback

    def _stop_zorder_guard(self) -> None:
        """Remove the WinEvent hook and stop the fallback timer."""
        self._zorder_guard_active = False
        self._topmost_timer.stop()
        if self._zorder_thread_id:
            ctypes.windll.user32.PostThreadMessageW(
                self._zorder_thread_id, 0x0012, 0, 0   # WM_QUIT
            )
            self._zorder_thread_id = 0
        self._zorder_proc_ref = None

    # ------------------------------------------------------------------
    # Visibility helpers
    # ------------------------------------------------------------------

    def show_overlay(self) -> None:
        """Make the overlay (and all its child layers) visible."""
        self.show()
        self.raise_()
        self._reassert_topmost()   # immediate assertion
        self._start_zorder_guard() # event-driven guard + 50 ms timer

    def hide_overlay(self) -> None:
        """Hide the overlay and all its child layers."""
        self._stop_zorder_guard()
        self.hide()

    # ------------------------------------------------------------------
    # Layer management
    # ------------------------------------------------------------------

    def set_child_layers(self, layers: list[QWidget]) -> None:
        """Reparent each layer widget to this window."""
        for layer in layers:
            layer.setParent(self)
            layer.show()
