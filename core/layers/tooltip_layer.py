"""Tooltip layer — floating instruction card near the spotlight.

Features:
    1.9   Draggable card (user can move it away from the spotlight).
    1.10  Collapsible "More info" section showing the step explanation.
"""
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
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.step import Step

# ── Layout constants ──────────────────────────────────────────────────────────
_CARD_MAX_WIDTH: int  = 340
_CARD_PADDING: int    = 16
_GAP: int             = 8     # vertical gap between element and card
_CORNER_RADIUS: float = 12.0
_SHADOW_BLUR: int     = 8
_BORDER_COLOR  = QColor(220, 220, 220)
_SHADOW_COLOR  = QColor(0, 0, 0, 45)
_BG_COLOR      = QColor(255, 255, 255)

# ── Action label text map ─────────────────────────────────────────────────────
_ACTION_LABELS: dict[str, str] = {
    "click":  "Click here",
    "type":   "Type here",
    "scroll": "Scroll here",
    "hover":  "Hover here",
}

# ── Action accent colours (top border) ────────────────────────────────────────
_ACTION_ACCENT: dict[str, QColor] = {
    "click":  QColor(137, 180, 250),   # blue
    "type":   QColor(166, 227, 161),   # green
    "scroll": QColor(203, 166, 247),   # purple
    "hover":  QColor(249, 226, 175),   # yellow
}


# ---------------------------------------------------------------------------
# Inner card widget
# ---------------------------------------------------------------------------

class _Card(QWidget):
    """Rounded card widget — shows action label, tooltip text, and expandable
    'More info' section.  Draggable via mouse press/move on the body (1.9).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMaximumWidth(_CARD_MAX_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._opacity: float = 1.0
        self._action: str = "click"
        self._expanded: bool = False     # 1.10 — More info visibility
        self._drag_pos: QPoint | None = None   # 1.9 — drag tracking
        self._build_ui()

    # ------------------------------------------------------------------
    # Opacity helper
    # ------------------------------------------------------------------

    def set_opacity(self, opacity: float) -> None:
        self._opacity = max(0.0, min(1.0, opacity))
        alpha = int(self._opacity * 255)
        self._action_label.setStyleSheet(f"color: rgba(136, 136, 136, {alpha});")
        self._tooltip_label.setStyleSheet(f"color: rgba(26, 26, 26, {alpha});")
        self._more_label.setStyleSheet(f"color: rgba(80, 80, 100, {alpha});")
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
        outer.setSpacing(6)

        # ── Action label ──────────────────────────────────────────────
        self._action_label = QLabel()
        af = QFont()
        af.setPointSize(9)
        self._action_label.setFont(af)
        self._action_label.setStyleSheet("color: #888888;")
        self._action_label.setWordWrap(False)
        outer.addWidget(self._action_label)

        # ── Tooltip body ──────────────────────────────────────────────
        self._tooltip_label = QLabel()
        bf = QFont()
        bf.setPointSize(11)
        self._tooltip_label.setFont(bf)
        self._tooltip_label.setStyleSheet("color: #1a1a1a;")
        self._tooltip_label.setWordWrap(True)
        self._tooltip_label.setMaximumWidth(
            _CARD_MAX_WIDTH - _CARD_PADDING * 2 - _SHADOW_BLUR * 2
        )
        outer.addWidget(self._tooltip_label)

        # ── "More info" toggle row (1.10) ─────────────────────────────
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 2, 0, 0)
        self._toggle_btn = QPushButton("ⓘ More info")
        self._toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            "color: #89b4fa; font-size: 10px; padding: 0; text-align: left; } "
            "QPushButton:hover { color: #74c7ec; }"
        )
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._toggle_btn.clicked.connect(self._on_toggle_more)
        toggle_row.addWidget(self._toggle_btn)
        toggle_row.addStretch()
        outer.addLayout(toggle_row)

        # ── Explanation text (1.10) — hidden by default ───────────────
        self._more_label = QLabel()
        mf = QFont()
        mf.setPointSize(9)
        mf.setItalic(True)
        self._more_label.setFont(mf)
        self._more_label.setStyleSheet("color: rgba(80, 80, 100, 220);")
        self._more_label.setWordWrap(True)
        self._more_label.setMaximumWidth(
            _CARD_MAX_WIDTH - _CARD_PADDING * 2 - _SHADOW_BLUR * 2
        )
        self._more_label.hide()
        outer.addWidget(self._more_label)

        # ── Drag hint label ───────────────────────────────────────────
        drag_hint = QLabel("⠿ drag")
        drag_hint.setStyleSheet(
            "color: rgba(160,160,180,120); font-size: 9px; padding: 0;"
        )
        drag_hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        outer.addWidget(drag_hint)

    # ------------------------------------------------------------------
    # Public setters
    # ------------------------------------------------------------------

    def set_content(self, tooltip: str, action: str, explanation: str = "") -> None:
        self._action = action
        self._tooltip_label.setText(tooltip)
        self._action_label.setText(_ACTION_LABELS.get(action, action.capitalize()))

        # 1.10 — update explanation and toggle button visibility
        has_explanation = bool(explanation.strip())
        self._more_label.setText(explanation)
        self._toggle_btn.setVisible(has_explanation)
        if not has_explanation:
            self._more_label.hide()
            self._expanded = False

        self.adjustSize()

    # ------------------------------------------------------------------
    # 1.10  Collapsible "More info" toggle
    # ------------------------------------------------------------------

    def _on_toggle_more(self) -> None:
        self._expanded = not self._expanded
        self._more_label.setVisible(self._expanded)
        self._toggle_btn.setText("▲ Less info" if self._expanded else "ⓘ More info")
        self.adjustSize()
        # Notify parent to re-clamp position
        parent = self.parent()
        if parent and hasattr(parent, "_on_card_resized"):
            parent._on_card_resized()

    # ------------------------------------------------------------------
    # 1.9  Drag-to-move
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_pos = None

    # ------------------------------------------------------------------
    # Painting — shadow + rounded card background + action accent bar
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        inner = self.rect().adjusted(
            _SHADOW_BLUR, _SHADOW_BLUR, -_SHADOW_BLUR, -_SHADOW_BLUR
        )

        # Drop shadow
        for i in range(_SHADOW_BLUR, 0, -1):
            alpha = max(0, int(_SHADOW_COLOR.alpha() * (1 - i / _SHADOW_BLUR) * 0.6))
            shadow_color = QColor(0, 0, 0, alpha)
            shadow_rect  = inner.adjusted(i // 2, i, -(i // 2), i // 2)
            path = QPainterPath()
            path.addRoundedRect(
                float(shadow_rect.x()), float(shadow_rect.y()),
                float(shadow_rect.width()), float(shadow_rect.height()),
                _CORNER_RADIUS, _CORNER_RADIUS,
            )
            painter.fillPath(path, shadow_color)

        # Card background
        bg_color = QColor(_BG_COLOR)
        bg_color.setAlphaF(self._opacity)
        card_path = QPainterPath()
        card_path.addRoundedRect(
            float(inner.x()), float(inner.y()),
            float(inner.width()), float(inner.height()),
            _CORNER_RADIUS, _CORNER_RADIUS,
        )
        painter.fillPath(card_path, bg_color)

        # Card border
        border_color = QColor(_BORDER_COLOR)
        border_color.setAlphaF(self._opacity)
        painter.setPen(QPen(border_color, 1.0))
        painter.drawPath(card_path)

        # Accent top bar (3 px, coloured by action type)
        accent = _ACTION_ACCENT.get(self._action, QColor(137, 180, 250))
        accent.setAlphaF(self._opacity)
        accent_rect = QPainterPath()
        # Clip to top half so rounded corners look correct
        top_r = QRect(inner.x(), inner.y(), inner.width(), 6)
        accent_rect.addRoundedRect(
            float(top_r.x()), float(top_r.y()),
            float(top_r.width()), float(top_r.height()),
            _CORNER_RADIUS, _CORNER_RADIUS,
        )
        # Fill bottom part of accent straight (avoid double-round at bottom)
        accent_rect.addRect(
            float(top_r.x()), float(top_r.y() + 3),
            float(top_r.width()), 3.0,
        )
        painter.fillPath(accent_rect, accent)

        painter.end()


# ---------------------------------------------------------------------------
# TooltipLayer
# ---------------------------------------------------------------------------

class TooltipLayer(QWidget):
    """Overlay layer that displays a floating tooltip card near the spotlight."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if parent:
            self.setGeometry(parent.rect())
        self._card = _Card(self)
        self._card.hide()
        self._last_coords: tuple[int, int, int, int] | None = None

    def set_opacity(self, opacity: float) -> None:
        self._card.set_opacity(opacity)

    # ------------------------------------------------------------------
    # BaseLayer interface
    # ------------------------------------------------------------------

    def render(self, step: Step) -> None:
        """Show the tooltip card positioned relative to *step*.coords."""
        self._card.set_content(step.tooltip, step.action, step.explanation)
        self._card.adjustSize()
        self._last_coords = step.coords
        self._position_card(step.coords)
        self._card.show()
        self._card.raise_()

    def clear(self) -> None:
        self._card.hide()
        self.update()

    def show_message(self, message: str) -> None:
        """Display *message* as a card body with no action label."""
        self._card._action_label.setText("")
        self._card._tooltip_label.setText(message)
        self._card._toggle_btn.hide()
        self._card._more_label.hide()
        self._card.adjustSize()
        self._position_card(None)
        self._card.show()
        self._card.raise_()

    # ------------------------------------------------------------------
    # Called by the card when it resizes after expand/collapse (1.10)
    # ------------------------------------------------------------------

    def _on_card_resized(self) -> None:
        """Re-clamp the card's position so it stays on screen after resize."""
        pos = self._card.pos()
        sr  = self.rect()
        cs  = self._card.sizeHint()
        x = max(0, min(pos.x(), sr.width()  - cs.width()))
        y = max(0, min(pos.y(), sr.height() - cs.height()))
        self._card.move(QPoint(x, y))

    # ------------------------------------------------------------------
    # Positioning logic
    # ------------------------------------------------------------------

    def _position_card(self, coords: tuple[int, int, int, int] | None) -> None:
        """Place the card near the element rect, staying on screen."""
        screen_rect: QRect = self.rect()
        card_size:   QSize = self._card.sizeHint()

        if coords is None:
            x = (screen_rect.width()  - card_size.width())  // 2
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
        sw = sr - sl
        sh = sb - st

        # Centre horizontally over the element
        x = sl + (sw - card_size.width()) // 2
        # Prefer below; fall back to above
        y_below = sb + _GAP
        y_above = st - card_size.height() - _GAP
        y = y_below if y_below + card_size.height() <= screen_rect.height() else max(0, y_above)
        # Clamp to screen
        x = max(0, min(x, screen_rect.width() - card_size.width()))

        self._card.move(QPoint(x, y))

    # ------------------------------------------------------------------
    # Keep card visible after resize
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())
        if self._card.isVisible():
            pos = self._card.pos()
            sr  = self.rect()
            cs  = self._card.size()
            x = max(0, min(pos.x(), sr.width()  - cs.width()))
            y = max(0, min(pos.y(), sr.height() - cs.height()))
            self._card.move(QPoint(x, y))
