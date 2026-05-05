"""Floating HUD control bar.

Features:
    1.2  Animated progress bar beneath the pill.
    1.8  Clickable step-dot indicator row above the pill for random-access nav.
"""
from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.step import Step

# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

_BTN_BASE = """
    QPushButton {{
        background: transparent;
        border: none;
        color: #ffffff;
        font-size: {size}px;
        font-weight: {weight};
        padding: 0 {pad}px;
        border-radius: 8px;
    }}
    QPushButton:hover   {{ background: rgba(255,255,255,0.15); }}
    QPushButton:pressed {{ background: rgba(255,255,255,0.08); }}
    QPushButton:disabled {{ color: rgba(255,255,255,0.35); }}
"""

_LABEL_STYLE = """
    color: rgba(255,255,255,0.85);
    font-size: 13px;
    font-weight: 500;
    padding: 0 6px;
"""

_DIVIDER_STYLE = """
    color: rgba(255,255,255,0.25);
    font-size: 18px;
    padding: 0;
"""

# Pill
_BG_COLOR    = QColor(0, 0, 0, 191)   # rgba(0,0,0,0.75)
_PILL_H      = 56
_PILL_RADIUS = 28.0

# Step dots (1.8)
_DOT_SIZE    = 8    # px diameter
_DOT_GAP     = 6   # px between dots
_DOT_ROW_H   = 22  # px reserved for the dot row

# Progress bar (1.2)
_BAR_H         = 4     # px height
_BAR_COLOR_FG  = QColor(137, 180, 250)   # Catppuccin blue
_BAR_COLOR_BG  = QColor(255, 255, 255, 30)

# Total widget height
_TOTAL_H = _DOT_ROW_H + _PILL_H + _BAR_H + 8   # dots + pill + bar + gap


class HUDLayer(QWidget):
    """Pill-shaped HUD control bar at the bottom-centre of the screen.

    Signals
    -------
    next_clicked:          User pressed the → button.
    back_clicked:          User pressed the ← button.
    paused(bool):          True when paused, False when resumed.
    exit_clicked:          User pressed the ✕ button.
    step_dot_clicked(int): User clicked the Nth step dot (0-based).
    """

    next_clicked:      pyqtSignal = pyqtSignal()
    back_clicked:      pyqtSignal = pyqtSignal()
    paused:            pyqtSignal = pyqtSignal(bool)
    exit_clicked:      pyqtSignal = pyqtSignal()
    step_dot_clicked:  pyqtSignal = pyqtSignal(int)  # 1.8

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._is_paused = False
        self._total_steps: int = 0
        self._current_step: int = 0   # 0-based

        # ── 1.2 Progress bar animation value (0.0 – 1.0) ──────────────
        self._progress: float = 0.0
        self._bar_anim = QPropertyAnimation(self, b"hudProgress", self)
        self._bar_anim.setDuration(400)
        self._bar_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._build_ui()
        self._reposition()

    # ------------------------------------------------------------------
    # Qt property for progress bar animation
    # ------------------------------------------------------------------

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, v: float) -> None:
        self._progress = max(0.0, min(1.0, v))
        self.update()

    hudProgress = pyqtProperty(float, _get_progress, _set_progress)

    # ------------------------------------------------------------------
    # BaseLayer interface
    # ------------------------------------------------------------------

    def render(self, step: Step) -> None:  # noqa: ARG002
        """Satisfy the BaseLayer contract — HUD doesn't render step content."""
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_progress(self, current: int, total: int) -> None:
        """Update the step-counter label, progress bar, and step dots.

        Parameters
        ----------
        current : 0-based index of the active step.
        total   : Total number of steps in the task.
        """
        self._current_step = current
        self._total_steps  = total
        self._counter.setText(f"Step {current + 1} of {total}")

        # Animate progress bar (1.2)
        target = (current + 1) / max(total, 1)
        self._bar_anim.stop()
        self._bar_anim.setStartValue(self._progress)
        self._bar_anim.setEndValue(target)
        self._bar_anim.start()

        # Rebuild dot row (1.8)
        self._rebuild_dots(total, current)
        self._reposition()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # ── Step dots row (1.8) ───────────────────────────────────────
        self._dots_container = QWidget(self)
        self._dots_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._dots_container.setFixedHeight(_DOT_ROW_H)
        self._dots_layout = QHBoxLayout(self._dots_container)
        self._dots_layout.setContentsMargins(16, 0, 16, 0)
        self._dots_layout.setSpacing(_DOT_GAP)
        self._dots_layout.addStretch()
        self._dots_layout.addStretch()
        outer.addWidget(self._dots_container, alignment=Qt.AlignmentFlag.AlignHCenter)

        # ── Pill row ──────────────────────────────────────────────────
        self._pill = QWidget(self)
        self._pill.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._pill.setFixedHeight(_PILL_H)

        pill_layout = QHBoxLayout(self._pill)
        pill_layout.setContentsMargins(16, 0, 16, 0)
        pill_layout.setSpacing(2)

        self._back_btn = self._make_btn("←", size=18, pad=12)
        self._back_btn.setToolTip("Previous step")
        self._back_btn.clicked.connect(self.back_clicked)
        pill_layout.addWidget(self._back_btn)

        self._counter = QLabel("Step — of —")
        self._counter.setStyleSheet(_LABEL_STYLE)
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill_layout.addWidget(self._counter)

        self._next_btn = self._make_btn("→", size=18, pad=12)
        self._next_btn.setToolTip("Next step")
        self._next_btn.clicked.connect(self.next_clicked)
        pill_layout.addWidget(self._next_btn)

        divider = QLabel("│")
        divider.setStyleSheet(_DIVIDER_STYLE)
        pill_layout.addWidget(divider)

        self._pause_btn = self._make_btn("⏸", size=15, pad=10)
        self._pause_btn.setToolTip("Pause overlay")
        self._pause_btn.setCheckable(True)
        self._pause_btn.clicked.connect(self._on_pause_toggle)
        pill_layout.addWidget(self._pause_btn)

        self._exit_btn = self._make_btn("✕", size=13, pad=10)
        self._exit_btn.setToolTip("Exit walkthrough")
        self._exit_btn.clicked.connect(self.exit_clicked)
        pill_layout.addWidget(self._exit_btn)

        self._pill.adjustSize()
        outer.addWidget(self._pill)

        # ── Progress bar placeholder (painted in paintEvent) (1.2) ───
        self._bar_widget = QWidget(self)
        self._bar_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._bar_widget.setFixedHeight(_BAR_H + 4)
        outer.addWidget(self._bar_widget)

        self.adjustSize()

    # ------------------------------------------------------------------
    # 1.8  Step dots
    # ------------------------------------------------------------------

    def _rebuild_dots(self, total: int, current: int) -> None:
        """Recreate the dot indicator row for *total* steps."""
        # Clear existing dots
        while self._dots_layout.count() > 2:   # keep the two stretches
            item = self._dots_layout.takeAt(1)
            if item and item.widget():
                item.widget().deleteLater()

        # Insert dots between the two stretches
        for i in range(total):
            dot = _StepDot(i, active=(i == current), parent=self._dots_container)
            dot.clicked_index.connect(self.step_dot_clicked)
            self._dots_layout.insertWidget(self._dots_layout.count() - 1, dot)

        self._dots_container.adjustSize()

    @staticmethod
    def _make_btn(text: str, *, size: int, pad: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(_PILL_H - 8)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(_BTN_BASE.format(size=size, weight=600, pad=pad))
        return btn

    # ------------------------------------------------------------------
    # Pause toggle
    # ------------------------------------------------------------------

    def _on_pause_toggle(self, checked: bool) -> None:
        self._is_paused = checked
        self._pause_btn.setText("▶" if checked else "⏸")
        self._pause_btn.setToolTip("Resume overlay" if checked else "Pause overlay")
        accent = "rgba(255,200,0,0.25)" if checked else "rgba(255,255,255,0.15)"
        self._pause_btn.setStyleSheet(
            _BTN_BASE.format(size=15, weight=600, pad=10).replace(
                "QPushButton:hover   { background: rgba(255,255,255,0.15); }",
                f"QPushButton:hover   {{ background: {accent}; }}",
            )
        )
        self.paused.emit(checked)

    # ------------------------------------------------------------------
    # Painting — pill background + progress bar
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── Pill background ───────────────────────────────────────────
        pill_rect = self._pill.geometry()
        pill_path = QPainterPath()
        pill_path.addRoundedRect(
            float(pill_rect.x()), float(pill_rect.y()),
            float(pill_rect.width()), float(pill_rect.height()),
            _PILL_RADIUS, _PILL_RADIUS,
        )
        painter.fillPath(pill_path, _BG_COLOR)

        # ── Progress bar (1.2) ────────────────────────────────────────
        bar_rect = self._bar_widget.geometry()
        bar_y    = bar_rect.y() + 2
        bar_x    = pill_rect.x()
        bar_w    = pill_rect.width()

        # Background track
        track_path = QPainterPath()
        track_path.addRoundedRect(float(bar_x), float(bar_y),
                                   float(bar_w), float(_BAR_H), 2.0, 2.0)
        painter.fillPath(track_path, _BAR_COLOR_BG)

        # Filled portion
        filled_w = int(bar_w * self._progress)
        if filled_w > 0:
            fill_path = QPainterPath()
            fill_path.addRoundedRect(float(bar_x), float(bar_y),
                                     float(filled_w), float(_BAR_H), 2.0, 2.0)
            painter.fillPath(fill_path, _BAR_COLOR_FG)

        painter.end()

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------

    def _reposition(self) -> None:
        """Place the HUD at the bottom-centre of the parent."""
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        pw = parent.width()
        ph = parent.height()
        w  = self.width()
        h  = self.height()
        self.move((pw - w) // 2, ph - h - 20)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._reposition()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._reposition()


# ---------------------------------------------------------------------------
# Step-dot widget  (1.8)
# ---------------------------------------------------------------------------

class _StepDot(QWidget):
    """A small clickable circle representing one step."""

    clicked_index: pyqtSignal = pyqtSignal(int)

    _ACTIVE_COLOR   = QColor(137, 180, 250)        # blue
    _INACTIVE_COLOR = QColor(255, 255, 255, 80)
    _HOVER_COLOR    = QColor(255, 255, 255, 160)

    def __init__(self, index: int, active: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index  = index
        self._active = active
        self._hover  = False
        size = _DOT_SIZE + (4 if active else 0)   # active dot slightly larger
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setToolTip(f"Jump to step {index + 1}")

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._active:
            color = self._ACTIVE_COLOR
        elif self._hover:
            color = self._HOVER_COLOR
        else:
            color = self._INACTIVE_COLOR
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, self.width(), self.height())
        painter.end()

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked_index.emit(self._index)
