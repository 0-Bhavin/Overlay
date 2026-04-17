import ctypes
import ctypes.wintypes

from PyQt6.QtWidgets import QWidget, QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter

# Win32 extended-style flags needed for OS-level click-through
_GWL_EXSTYLE    = -20
_WS_EX_LAYERED  = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020


class OverlayWindow(QWidget):
    """Frameless, always-on-top, fully transparent window that covers the
    primary screen.  The window itself passes all mouse events through to
    whatever application sits beneath it; only its child layers capture input.
    """

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )

        # Transparent background — the OS composites child widgets on top.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # The window itself must never steal clicks or hovers from the target app.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Stretch to the full primary screen immediately.
        screen_geometry = QApplication.primaryScreen().geometry()
        self.setGeometry(screen_geometry)

    # ------------------------------------------------------------------
    # Paint: nothing — the window is purely a transparent container.
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.end()

    # ------------------------------------------------------------------
    # Win32 click-through
    # ------------------------------------------------------------------

    def _make_click_through(self) -> None:
        """Set WS_EX_LAYERED | WS_EX_TRANSPARENT on the HWND.

        This makes the window invisible to Windows hit-testing so that mouse
        clicks fall through to whatever application is below the overlay.
        Qt's ``WA_TransparentForMouseEvents`` only affects Qt's own event
        dispatch; this call handles the OS level.
        """
        hwnd = int(self.winId())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, _GWL_EXSTYLE, style | _WS_EX_LAYERED | _WS_EX_TRANSPARENT
        )

    def showEvent(self, event) -> None:  # noqa: N802
        """Apply Win32 click-through flags as soon as the HWND exists."""
        super().showEvent(event)
        self._make_click_through()

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
