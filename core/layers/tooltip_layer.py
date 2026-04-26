from __future__ import annotations

from PyQt6.QtCore import (
    QPoint,
    QRect,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.step import Step

# ── Layout constants ──────────────────────────────────────────────────────────
_CARD_MAX_WIDTH: int = 320
_CARD_PADDING: int = 16          # inner padding (px)
_GAP: int = 5                    # vertical gap: tooltip starts 5px below element bottom
_CORNER_RADIUS: float = 12.0
_SHADOW_BLUR: int = 8            # approximate shadow spread (px)
_BORDER_COLOR = QColor(220, 220, 220)
_SHADOW_COLOR = QColor(0, 0, 0, 45)
_BG_COLOR = QColor(255, 255, 255)

# ── Action label text map ─────────────────────────────────────────────────────
_ACTION_LABELS: dict[str, str] = {
    "click": "Click here",
    "type": "Type here",
    "scroll": "Scroll here",
    "hover": "Hover here",
}


class _Card(QWidget):
    """Inner card widget — shows action label + tooltip text only.

    Navigation is handled by the HUD; this card is read-only.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMaximumWidth(_CARD_MAX_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._opacity: float = 1.0
        self._build_ui()

    def set_opacity(self, opacity: float) -> None:
        """Set the card opacity [0.0, 1.0] and update."""
        self._opacity = max(0.0, min(1.0, opacity))
        # Modulate child label styles to reflect opacity
        alpha = int(self._opacity * 255)
        self._action_label.setStyleSheet(f"color: rgba(136, 136, 136, {alpha});")
        self._tooltip_label.setStyleSheet(f"color: rgba(26, 26, 26, {alpha});")
        self.update()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            _CARD_PADDING + _SHADOW_BLUR,
            _CARD_PADDING + _SHADOW_BLUR,
            _CARD_PADDING + _SHADOW_BLUR,
            _CARD_PADDING + _SHADOW_BLUR,
        )
        outer.setSpacing(8)

        # ── Action label ──────────────────────────────────────────────
        self._action_label = QLabel()
        action_font = QFont()
        action_font.setPointSize(9)
        self._action_label.setFont(action_font)
        self._action_label.setStyleSheet("color: #888888;")
        self._action_label.setWordWrap(False)
        outer.addWidget(self._action_label)

        # ── Tooltip / body text ───────────────────────────────────────
        self._tooltip_label = QLabel()
        body_font = QFont()
        body_font.setPointSize(11)
        self._tooltip_label.setFont(body_font)
        self._tooltip_label.setStyleSheet("color: #1a1a1a;")
        self._tooltip_label.setWordWrap(True)
        self._tooltip_label.setMaximumWidth(_CARD_MAX_WIDTH - _CARD_PADDING * 2 - _SHADOW_BLUR * 2)
        outer.addWidget(self._tooltip_label)

    # ------------------------------------------------------------------
    # Public setters
    # ------------------------------------------------------------------

    def set_content(self, tooltip: str, action: str) -> None:
        self._tooltip_label.setText(tooltip)
        self._action_label.setText(_ACTION_LABELS.get(action, action.capitalize()))
        self.adjustSize()

    # ------------------------------------------------------------------
    # Painting — shadow + rounded card background
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Inner rect (inside the shadow bleed area)
        inner = self.rect().adjusted(
            _SHADOW_BLUR, _SHADOW_BLUR, -_SHADOW_BLUR, -_SHADOW_BLUR
        )

        # ── Drop shadow (layered offset fills) ────────────────────────
        for i in range(_SHADOW_BLUR, 0, -1):
            alpha = max(0, int(_SHADOW_COLOR.alpha() * (1 - i / _SHADOW_BLUR) * 0.6))
            shadow_color = QColor(0, 0, 0, alpha)
            shadow_rect = inner.adjusted(i // 2, i, -(i // 2), i // 2)
            path = QPainterPath()
            path.addRoundedRect(
                float(shadow_rect.x()),
                float(shadow_rect.y()),
                float(shadow_rect.width()),
                float(shadow_rect.height()),
                _CORNER_RADIUS,
                _CORNER_RADIUS,
            )
            painter.fillPath(path, shadow_color)

        # ── Card background ───────────────────────────────────────────
        bg_color = QColor(_BG_COLOR)
        bg_color.setAlphaF(self._opacity)

        card_path = QPainterPath()
        card_path.addRoundedRect(
            float(inner.x()),
            float(inner.y()),
            float(inner.width()),
            float(inner.height()),
            _CORNER_RADIUS,
            _CORNER_RADIUS,
        )
        painter.fillPath(card_path, bg_color)

        # ── Card border ───────────────────────────────────────────────
        border_color = QColor(_BORDER_COLOR)
        border_color.setAlphaF(self._opacity)
        painter.setPen(QPen(border_color, 1.0))
        painter.drawPath(card_path)

        painter.end()


class TooltipLayer(QWidget):
    """Overlay layer that displays a floating tooltip card near the spotlight.

    Navigation buttons have been removed — the HUD bar handles all navigation.
    This layer is read-only: it shows the instruction text and action label only.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Mirror parent geometry
        if parent:
            self.setGeometry(parent.rect())
        self._card = _Card(self)
        self._card.hide()

    def set_opacity(self, opacity: float) -> None:
        """Set the layer opacity and update the card."""
        self._card.set_opacity(opacity)

    # ------------------------------------------------------------------
    # BaseLayer interface
    # ------------------------------------------------------------------

    def render(self, step: Step) -> None:
        """Show the tooltip card positioned relative to *step*.coords."""
        self._card.set_content(step.tooltip, step.action)
        self._card.adjustSize()
        self._position_card(step.coords)
        self._card.show()
        self._card.raise_()

    def clear(self) -> None:
        """Hide the tooltip card."""
        self._card.hide()
        self.update()

    def show_message(self, message: str) -> None:
        """Display *message* as the card body with no action label.

        Used for transient status strings such as "Locating…" or the
        resolution-failed fallback — no ``Step`` object needed.

        Parameters
        ----------
        message:
            Plain text to show in the card body.
        """
        self._card._action_label.setText("")
        self._card._tooltip_label.setText(message)
        self._card.adjustSize()
        self._position_card(None)   # centred — no spotlight coords available
        self._card.show()
        self._card.raise_()

    # ------------------------------------------------------------------
    # Positioning logic
    # ------------------------------------------------------------------

    def _position_card(self, coords: tuple[int, int, int, int] | None) -> None:
        """Place the card 5 px below (or above) the element rect, within screen bounds.

        Parameters
        ----------
        coords:
            ``(L, T, R, B)`` screen-pixel rect of the target element, or
            ``None`` to centre the card on screen.
        """
        screen_rect: QRect = self.rect()
        card_size: QSize = self._card.sizeHint()

        if coords is None:
            # Fallback: centre of the screen
            x = (screen_rect.width() - card_size.width()) // 2
            y = (screen_rect.height() - card_size.height()) // 2
            self._card.move(QPoint(x, y))
            return

        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        dpr = 1.0
        if app is not None and app.primaryScreen() is not None:
            dpr = app.primaryScreen().devicePixelRatio()

        sl = int(coords[0] / dpr)
        st = int(coords[1] / dpr)
        sr = int(coords[2] / dpr)
        sb = int(coords[3] / dpr)
        sw = sr - sl   # logical element width
        sh = sb - st   # logical element height

        # Centre the card horizontally over the element
        x = sl + (sw - card_size.width()) // 2
        # Prefer placing 5px below the element bottom
        y_below = sb + _GAP
        y_above = st - card_size.height() - _GAP

        if y_below + card_size.height() <= screen_rect.height():
            y = y_below
        else:
            y = max(0, y_above)

        # Clamp horizontally so the card stays on screen
        x = max(0, min(x, screen_rect.width() - card_size.width()))

        self._card.move(QPoint(x, y))

    # ------------------------------------------------------------------
    # Keep card visible after resize
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())
        # Re-clamp position if the card is currently visible
        if self._card.isVisible():
            pos = self._card.pos()
            sr = self.rect()
            cs = self._card.size()
            x = max(0, min(pos.x(), sr.width() - cs.width()))
            y = max(0, min(pos.y(), sr.height() - cs.height()))
            self._card.move(QPoint(x, y))
