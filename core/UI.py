"""Task input dialog.

A compact, frameless, always-on-top window that lets the user describe a task
and target application, then calls :class:`~core.ai_task_generator.GeminiTaskGenerator`
to produce a structured step file.
"""
from __future__ import annotations

import json
import os

from PyQt6.QtCore import (
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
    pyqtSlot,
    QObject,
)
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.ai_task_generator import GeminiTaskGenerator

# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

_STYLE = """
QWidget#TaskInputDialog {
    background: #1e1e2e;
    border-radius: 12px;
    border: 1px solid #313244;
}

QLabel#title {
    color: #cdd6f4;
    font-size: 15px;
    font-weight: 600;
}

QLabel#fieldLabel {
    color: #a6adc8;
    font-size: 11px;
    font-weight: 500;
}

QLineEdit {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
    color: #cdd6f4;
    font-size: 12px;
    selection-background-color: #89b4fa;
}
QLineEdit:focus {
    border-color: #89b4fa;
}

QPushButton#startBtn {
    background: #89b4fa;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    color: #1e1e2e;
    font-size: 12px;
    font-weight: 700;
}
QPushButton#startBtn:hover  { background: #74c7ec; }
QPushButton#startBtn:pressed { background: #89dceb; }
QPushButton#startBtn:disabled {
    background: #45475a;
    color: #6c7086;
}

QPushButton#closeBtn {
    background: transparent;
    border: none;
    color: #6c7086;
    font-size: 14px;
    padding: 2px 6px;
}
QPushButton#closeBtn:hover { color: #f38ba8; }

QLabel#status {
    color: #89b4fa;
    font-size: 11px;
}
"""

# Output directory relative to this file's location
_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "tasks")
_OUTPUT_FILE = os.path.join(_OUTPUT_DIR, "generated_task.json")


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class _GeneratorWorker(QObject):
    """Runs GeminiTaskGenerator.generate() on a background thread."""

    succeeded = pyqtSignal(dict)    # {app_exe, steps}
    failed    = pyqtSignal(str)     # error message

    def __init__(self, generator: GeminiTaskGenerator, task: str, app: str) -> None:
        super().__init__()
        self._generator = generator
        self._task = task
        self._app  = app

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self._generator.generate(self._task, self._app)
            self.succeeded.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class TaskInputDialog(QWidget):
    """Compact floating dialog for task input.

    Signals
    -------
    task_ready(path):
        Emitted with the absolute path to the generated JSON task file once
        the Gemini call succeeds and the file is saved.
    """

    task_ready: pyqtSignal = pyqtSignal(str)

    def __init__(self, api_key: str, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setObjectName("TaskInputDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(420, 210)
        self.setStyleSheet(_STYLE)

        self._generator = GeminiTaskGenerator(api_key)
        self._thread: QThread | None = None
        self._worker: _GeneratorWorker | None = None

        # ── Animated dots state ──────────────────────────────────────
        self._dot_count = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(450)
        self._dot_timer.timeout.connect(self._tick_dots)

        # ── Allow dragging ───────────────────────────────────────────
        self._drag_pos = None

        self._build_ui()
        self._centre_on_screen()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        # ── Title row ────────────────────────────────────────────────
        title_row = QHBoxLayout()

        title = QLabel("AI Overlay — New Task")
        title.setObjectName("title")
        title_row.addWidget(title)
        title_row.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(24, 24)
        close_btn.clicked.connect(self.close)
        title_row.addWidget(close_btn)

        root.addLayout(title_row)

        # ── Task description ─────────────────────────────────────────
        lbl_task = QLabel("Task description")
        lbl_task.setObjectName("fieldLabel")
        root.addWidget(lbl_task)

        self._task_edit = QLineEdit()
        self._task_edit.setPlaceholderText('e.g. "Insert an image into the document"')
        root.addWidget(self._task_edit)

        # ── App name ─────────────────────────────────────────────────
        lbl_app = QLabel("Target application")
        lbl_app.setObjectName("fieldLabel")
        root.addWidget(lbl_app)

        self._app_edit = QLineEdit()
        self._app_edit.setPlaceholderText('e.g. "Microsoft Word"')
        root.addWidget(self._app_edit)

        # ── Footer row ───────────────────────────────────────────────
        footer = QHBoxLayout()
        footer.setSpacing(10)

        self._status_label = QLabel("")
        self._status_label.setObjectName("status")
        footer.addWidget(self._status_label)
        footer.addStretch()

        self._start_btn = QPushButton("Start")
        self._start_btn.setObjectName("startBtn")
        self._start_btn.setFixedHeight(34)
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.clicked.connect(self._on_start)
        footer.addWidget(self._start_btn)

        root.addLayout(footer)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        task = self._task_edit.text().strip()
        app  = self._app_edit.text().strip()

        if not task or not app:
            self._status_label.setText("⚠ Both fields are required.")
            return

        self._set_loading(True)

        # Run generator on a background thread
        self._thread = QThread(self)
        self._worker = _GeneratorWorker(self._generator, task, app)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.succeeded.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.succeeded.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    @pyqtSlot(dict)
    def _on_success(self, result: dict) -> None:
        self._set_loading(False)

        # Wrap in a full task dict and save
        task_dict = {
            "name":    self._task_edit.text().strip(),
            "app":     self._app_edit.text().strip(),
            "app_exe": result.get("app_exe", ""),
            "steps":   result.get("steps", []),
        }
        os.makedirs(_OUTPUT_DIR, exist_ok=True)
        out_path = os.path.abspath(_OUTPUT_FILE)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(task_dict, fh, indent=2)

        self._status_label.setText("✓ Task generated!")
        self.task_ready.emit(out_path)

    @pyqtSlot(str)
    def _on_failure(self, error: str) -> None:
        self._set_loading(False)
        self._status_label.setText("")
        QMessageBox.critical(
            self,
            "Generation Failed",
            f"Could not generate task steps:\n\n{error}",
        )

    # ------------------------------------------------------------------
    # Loading state
    # ------------------------------------------------------------------

    def _set_loading(self, loading: bool) -> None:
        self._start_btn.setEnabled(not loading)
        self._task_edit.setEnabled(not loading)
        self._app_edit.setEnabled(not loading)
        if loading:
            self._dot_count = 0
            self._status_label.setText("Generating…")
            self._dot_timer.start()
        else:
            self._dot_timer.stop()

    def _tick_dots(self) -> None:
        self._dot_count = (self._dot_count + 1) % 4
        dots = "." * self._dot_count
        self._status_label.setText(f"Generating{dots}")

    # ------------------------------------------------------------------
    # Drag to move (frameless window)
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
    # Helpers
    # ------------------------------------------------------------------

    def _centre_on_screen(self) -> None:
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width()  - self.width())  // 2,
            (screen.height() - self.height()) // 2,
        )
