"""Floating HUD control bar.

A pill-shaped toolbar that sits at the bottom-centre of the screen,
always above all other overlay layers.  It handles step navigation,
pause/resume, and exit.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from core.layers.base_layer import BaseLayer
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
    QPushButton:hover  {{ background: rgba(255,255,255,0.15); }}
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

# Pill background
_BG_COLOR   = QColor(0, 0, 0, 191)   # rgba(0,0,0,0.75)
_PILL_H     = 56
_PILL_RADIUS = 28.0


class HUDLayer(BaseLayer):
    """Pill-shaped HUD control bar rendered at the bottom-centre of the screen.

    Signals
    -------
    next_clicked:  User pressed the → button.
    back_clicked:  User pressed the ← button.
    paused(bool):  ``True`` when paused, ``False`` when resumed.
    exit_clicked:  User pressed the ✕ button.
    """

    next_clicked: pyqtSignal = pyqtSignal()
    back_clicked: pyqtSignal = pyqtSignal()
    paused:       pyqtSignal = pyqtSignal(bool)
    exit_clicked: pyqtSignal = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)

        # HUD receives mouse events — do NOT set WA_TransparentForMouseEvents.
        self._is_paused = False
        self._build_ui()
        self._reposition()

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
        """Update the step-counter label.

        Parameters
        ----------
        current:
            0-based index of the active step.
        total:
            Total number of steps in the task.
        """
        self._counter.setText(f"Step {current + 1} of {total}")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedHeight(_PILL_H)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(2)

        # ── Back ─────────────────────────────────────────────────────
        self._back_btn = self._make_btn("←", size=18, pad=12)
        self._back_btn.setToolTip("Previous step")
        self._back_btn.clicked.connect(self.back_clicked)
        layout.addWidget(self._back_btn)

        # ── Step counter ─────────────────────────────────────────────
        self._counter = QLabel("Step — of —")
        self._counter.setStyleSheet(_LABEL_STYLE)
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._counter)

        # ── Next ─────────────────────────────────────────────────────
        self._next_btn = self._make_btn("→", size=18, pad=12)
        self._next_btn.setToolTip("Next step")
        self._next_btn.clicked.connect(self.next_clicked)
        layout.addWidget(self._next_btn)

        # ── Divider ──────────────────────────────────────────────────
        divider = QLabel("│")
        divider.setStyleSheet(_DIVIDER_STYLE)
        layout.addWidget(divider)

        # ── Pause ────────────────────────────────────────────────────
        self._pause_btn = self._make_btn("⏸", size=15, pad=10)
        self._pause_btn.setToolTip("Pause overlay")
        self._pause_btn.setCheckable(True)
        self._pause_btn.clicked.connect(self._on_pause_toggle)
        layout.addWidget(self._pause_btn)

        # ── Exit ─────────────────────────────────────────────────────
        self._exit_btn = self._make_btn("✕", size=13, pad=10)
        self._exit_btn.setToolTip("Exit walkthrough")
        self._exit_btn.clicked.connect(self.exit_clicked)
        layout.addWidget(self._exit_btn)

        self.adjustSize()

    @staticmethod
    def _make_btn(text: str, *, size: int, pad: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(_PILL_H - 8)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            _BTN_BASE.format(size=size, weight=600, pad=pad)
        )
        return btn

    # ------------------------------------------------------------------
    # Pause toggle
    # ------------------------------------------------------------------

    def _on_pause_toggle(self, checked: bool) -> None:
        self._is_paused = checked
        self._pause_btn.setText("▶" if checked else "⏸")
        self._pause_btn.setToolTip("Resume overlay" if checked else "Pause overlay")

        # Style the pause button differently while paused
        accent = "rgba(255,200,0,0.25)" if checked else "rgba(255,255,255,0.15)"
        self._pause_btn.setStyleSheet(
            _BTN_BASE.format(size=15, weight=600, pad=10).replace(
                "QPushButton:hover  { background: rgba(255,255,255,0.15); }",
                f"QPushButton:hover  {{ background: {accent}; }}",
            )
        )
        self.paused.emit(checked)

    # ------------------------------------------------------------------
    # Painting — pill background
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        pill = QPainterPath()
        pill.addRoundedRect(
            float(self.rect().x()),
            float(self.rect().y()),
            float(self.rect().width()),
            float(self.rect().height()),
            _PILL_RADIUS,
            _PILL_RADIUS,
        )
        painter.fillPath(pill, _BG_COLOR)
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
        self.move((pw - w) // 2, ph - _PILL_H - 24)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._reposition()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._reposition()
