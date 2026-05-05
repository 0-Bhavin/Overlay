"""Task-completion celebration toast (feature 1.4).

A full-screen translucent overlay showing "🎉 Task Complete!" that fades
in, holds for 2.5 s, then fades out and calls the supplied *callback*
(typically ``app.quit``).
"""
from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtProperty,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QWidget


class CompletionToast(QWidget):
    """Full-screen translucent overlay shown when a task finishes."""

    def __init__(self, callback=None, parent=None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        self._alpha: float = 0.0
        self._callback = callback

        # ── Fade-in ──────────────────────────────────────────────────
        self._anim_in = QPropertyAnimation(self, b"toastAlpha", self)
        self._anim_in.setDuration(450)
        self._anim_in.setStartValue(0.0)
        self._anim_in.setEndValue(1.0)
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.show()
        self._anim_in.start()

        # Auto-dismiss after 2.5 s
        QTimer.singleShot(2500, self._fade_out)

    # ------------------------------------------------------------------
    # Qt property (needed for QPropertyAnimation)
    # ------------------------------------------------------------------

    def _get_alpha(self) -> float:
        return self._alpha

    def _set_alpha(self, v: float) -> None:
        self._alpha = v
        self.update()

    toastAlpha = pyqtProperty(float, _get_alpha, _set_alpha)

    # ------------------------------------------------------------------
    # Fade out & cleanup
    # ------------------------------------------------------------------

    def _fade_out(self) -> None:
        self._anim_out = QPropertyAnimation(self, b"toastAlpha", self)
        self._anim_out.setDuration(500)
        self._anim_out.setStartValue(self._alpha)
        self._anim_out.setEndValue(0.0)
        self._anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim_out.finished.connect(self._done)
        self._anim_out.start()

    def _done(self) -> None:
        self.hide()
        self.deleteLater()
        if self._callback:
            self._callback()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if self._alpha <= 0.0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Dim backdrop ─────────────────────────────────────────────
        painter.fillRect(self.rect(), QColor(0, 0, 0, int(self._alpha * 170)))

        # ── Card ─────────────────────────────────────────────────────
        cw, ch = 500, 220
        cx = (self.width()  - cw) // 2
        cy = (self.height() - ch) // 2

        card_path = QPainterPath()
        card_path.addRoundedRect(float(cx), float(cy), float(cw), float(ch), 20.0, 20.0)

        card_color = QColor(30, 30, 46, int(self._alpha * 245))
        painter.fillPath(card_path, card_color)

        border_color = QColor(166, 227, 161, int(self._alpha * 200))
        painter.setPen(QPen(border_color, 2.0))
        painter.drawPath(card_path)

        # ── Emoji ────────────────────────────────────────────────────
        emoji_font = QFont()
        emoji_font.setPointSize(46)
        painter.setFont(emoji_font)
        painter.setPen(QColor(255, 255, 255, int(self._alpha * 255)))
        painter.drawText(cx, cy + 10, cw, 90,
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                         "🎉")

        # ── Title ─────────────────────────────────────────────────────
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setWeight(QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor(205, 214, 244, int(self._alpha * 255)))
        painter.drawText(cx, cy + 105, cw, 55,
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                         "Task Complete!")

        # ── Sub-text ──────────────────────────────────────────────────
        sub_font = QFont()
        sub_font.setPointSize(11)
        painter.setFont(sub_font)
        painter.setPen(QColor(166, 173, 200, int(self._alpha * 190)))
        painter.drawText(cx, cy + 160, cw, 40,
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                         "Great job! The overlay will close now.")

        painter.end()
