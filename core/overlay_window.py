from __future__ import annotations

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QApplication, QWidget

_DIM_OPACITY: float = 0.55
_CORNER_RADIUS: float = 8.0


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
        # Set by SpotlightLayer; painted here in paintEvent.
        self._spotlight_rect: QRect | None = None
        self._dim_opacity: float = 0.0   # 0 = invisible, 0.55 = active

    # ------------------------------------------------------------------
    # Dim / spotlight state API  (called by SpotlightLayer / LayerManager)
    # ------------------------------------------------------------------

    def set_spotlight(self, rect: QRect | None, dim_opacity: float = _DIM_OPACITY) -> None:
        """Set the spotlight hole rect and dim opacity, then repaint.

        Parameters
        ----------
        rect:
            Pre-padded ``QRect`` of the transparent hole in screen coords,
            or ``None`` to paint a full dim with no hole.
        dim_opacity:
            Alpha of the black dim layer (0.0 – 1.0).
        """
        self._spotlight_rect = rect
        self._dim_opacity = max(0.0, min(1.0, dim_opacity))
        self.update()

    def clear_spotlight(self) -> None:
        """Remove the spotlight and make the dim invisible (fully transparent)."""
        self._spotlight_rect = None
        self._dim_opacity = 0.0
        self.update()

    # ------------------------------------------------------------------
    # Paint: dim overlay + spotlight hole
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._dim_opacity <= 0.0:
            return

        painter = QPainter(self)
        
        # 1. Draw full screen dim
        dim_color = QColor(0, 0, 0, int(self._dim_opacity * 255))
        painter.fillRect(self.rect(), dim_color)

        if self._spotlight_rect is not None:
            # 2. Punch a clean hole
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self._spotlight_rect, Qt.GlobalColor.transparent)
            
            # 3. Draw a border so the element is clearly highlighted
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            from PyQt6.QtGui import QPen
            pen = QPen(QColor(255, 255, 255, 200), 2)
            painter.setPen(pen)
            painter.drawRect(self._spotlight_rect)

        painter.end()

    # ------------------------------------------------------------------
    # Visibility helpers
    # ------------------------------------------------------------------

    def show_overlay(self) -> None:
        """Make the overlay (and all its child layers) visible."""
        self.show()
        self.raise_()

    def hide_overlay(self) -> None:
        """Hide the overlay and all its child layers."""
        self.hide()

    # ------------------------------------------------------------------
    # Layer management
    # ------------------------------------------------------------------

    def set_child_layers(self, layers: list[QWidget]) -> None:
        """Reparent each layer widget to this window.

        Layers are responsible for their own geometry and transparency;
        this method only establishes the parent–child relationship so that
        layers are painted inside the overlay and hidden/shown with it.
        """
        for layer in layers:
            layer.setParent(self)
            layer.show()
