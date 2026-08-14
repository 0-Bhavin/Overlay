"""Task input dialog.

Features:
    1.6  Microphone button for voice-to-text dictation.
    1.7  Recent tasks history dropdown.
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
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.ai_task_generator import GeminiTaskGenerator
from core.task_history import load_history, save_to_history

# ---------------------------------------------------------------------------
# Optional speech recognition (feature 1.6)
# ---------------------------------------------------------------------------

try:
    import speech_recognition as _sr  # type: ignore[import]
    _SR_AVAILABLE = True
except ImportError:
    _sr = None
    _SR_AVAILABLE = False

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
QPushButton#startBtn:hover   { background: #74c7ec; }
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

QPushButton#micBtn {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    color: #cdd6f4;
    font-size: 14px;
    padding: 4px 8px;
}
QPushButton#micBtn:hover   { background: #45475a; }
QPushButton#micBtn:checked { background: #f38ba8; border-color: #f38ba8; color: #1e1e2e; }

QComboBox#historyBox {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px 10px;
    color: #a6adc8;
    font-size: 11px;
}
QComboBox#historyBox::drop-down { border: none; }
QComboBox#historyBox QAbstractItemView {
    background: #313244;
    color: #cdd6f4;
    selection-background-color: #45475a;
    border: 1px solid #45475a;
}

QComboBox#appBox {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px 10px;
    color: #cdd6f4;
    font-size: 12px;
}
QComboBox#appBox:focus { border-color: #89b4fa; }
QComboBox#appBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: right center;
    width: 20px;
    border: none;
}
QComboBox#appBox QAbstractItemView {
    background: #313244;
    color: #cdd6f4;
    selection-background-color: #45475a;
    border: 1px solid #45475a;
    padding: 2px;
}

QPushButton#refreshBtn {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    color: #a6adc8;
    font-size: 13px;
    padding: 4px 8px;
}
QPushButton#refreshBtn:hover   { background: #45475a; color: #cdd6f4; }
QPushButton#refreshBtn:disabled { color: #585b70; }

QLabel#status {
    color: #89b4fa;
    font-size: 11px;
}

QWidget#modeToggleContainer {
    background: #181825;
    border-radius: 8px;
    border: 1px solid #313244;
}

QPushButton#toggleAppBtn, QPushButton#toggleWebBtn {
    background: transparent;
    border: none;
    border-radius: 6px;
    color: #a6adc8;
    font-size: 12px;
    font-weight: 600;
    padding: 6px 12px;
}
QPushButton#toggleAppBtn:hover, QPushButton#toggleWebBtn:hover {
    color: #cdd6f4;
    background: #313244;
}
QPushButton#toggleAppBtn:checked, QPushButton#toggleWebBtn:checked {
    background: #89b4fa;
    color: #1e1e2e;
    font-weight: 700;
}
"""

_OUTPUT_DIR           = os.path.join(os.path.dirname(__file__), "..", "tasks")
_OUTPUT_FILE          = os.path.join(_OUTPUT_DIR, "generated_task.json")
_DOM_SNAPSHOT_FILE    = os.path.join(_OUTPUT_DIR, "dom_snapshot.json")


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

class _GeneratorWorker(QObject):
    """Runs GeminiTaskGenerator.generate() on a background thread."""

    succeeded = pyqtSignal(dict)
    failed    = pyqtSignal(str)

    def __init__(
        self,
        generator: GeminiTaskGenerator,
        task: str,
        app: str,
        target_mode: str = "app",
        dom_snapshot: list | None = None,
    ) -> None:
        super().__init__()
        self._generator = generator
        self._task = task
        self._app  = app
        self._mode = target_mode
        self._dom_snapshot = dom_snapshot

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self._generator.generate(
                self._task, self._app, target_mode=self._mode, dom_snapshot=self._dom_snapshot
            )
            self.succeeded.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class _DOMFetchWorker(QObject):
    """Fetches the current page's DOM tree from BrowserConnector on a background thread."""

    succeeded = pyqtSignal(list)   # DOM UINode list (may be empty)
    failed    = pyqtSignal(str)    # error message

    def __init__(self, connector: object) -> None:
        super().__init__()
        self._connector = connector

    @pyqtSlot()
    def run(self) -> None:
        try:
            tree = self._connector.get_tree()  # type: ignore[attr-defined]
            self.succeeded.emit(tree if tree else [])
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class _MicWorker(QObject):
    """Records from microphone and transcribes via speech_recognition (1.6)."""

    succeeded = pyqtSignal(str)   # transcribed text
    failed    = pyqtSignal(str)   # error message

    @pyqtSlot()
    def run(self) -> None:
        if not _SR_AVAILABLE or _sr is None:
            self.failed.emit("speech_recognition not installed.\nRun: pip install speechrecognition pyaudio")
            return
        try:
            r = _sr.Recognizer()
            with _sr.Microphone() as source:
                r.adjust_for_ambient_noise(source, duration=0.4)
                audio = r.listen(source, timeout=6, phrase_time_limit=10)
            text = r.recognize_google(audio)
            self.succeeded.emit(text)
        except _sr.WaitTimeoutError:
            self.failed.emit("No speech detected. Please try again.")
        except _sr.UnknownValueError:
            self.failed.emit("Could not understand speech. Please try again.")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class _WindowScanWorker(QObject):
    """Scans open windows via pywinauto on a background thread."""

    succeeded = pyqtSignal(list)   # list[str] of window titles
    failed    = pyqtSignal(str)

    @pyqtSlot()
    def run(self) -> None:
        try:
            from pywinauto import Desktop  # type: ignore[import]
            windows = Desktop(backend="uia").windows()
            titles: list[str] = []
            seen: set[str] = set()
            for w in windows:
                try:
                    title = w.window_text().strip()
                    if title and title not in seen:
                        seen.add(title)
                        titles.append(title)
                except Exception:  # noqa: BLE001
                    pass
            self.succeeded.emit(sorted(titles, key=str.casefold))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class TaskInputDialog(QWidget):
    """Compact floating dialog for task input with history and mic support.

    Signals
    -------
    task_ready(path):
        Emitted with the absolute path to the generated JSON task file once
        the Gemini call succeeds and the file is saved.
    """

    task_ready: pyqtSignal = pyqtSignal(str)

    def __init__(self, api_key: str, parent: QWidget | None = None, browser_connector: object | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setObjectName("TaskInputDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(440, 360)
        self.setStyleSheet(_STYLE)

        self._target_mode = "app"  # "app" or "website"
        self._browser_connector = browser_connector
        self._generator = GeminiTaskGenerator(api_key)
        self._thread: QThread | None = None
        self._worker: _GeneratorWorker | None = None
        self._mic_thread: QThread | None = None
        self._mic_worker: _MicWorker | None = None
        self._scan_thread: QThread | None = None
        self._scan_worker: _WindowScanWorker | None = None
        self._dom_thread: QThread | None = None
        self._dom_worker: _DOMFetchWorker | None = None

        # Animated dots
        self._dot_count = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(450)
        self._dot_timer.timeout.connect(self._tick_dots)

        # Drag support
        self._drag_pos = None

        self._build_ui()
        self._load_history()
        self._centre_on_screen()
        # Auto-scan open windows when the dialog first opens
        QTimer.singleShot(200, self._refresh_windows)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(8)

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

        # ── Mode Toggle Switch (Top) ───────────────────────────────
        mode_container = QWidget()
        mode_container.setObjectName("modeToggleContainer")
        mode_layout = QHBoxLayout(mode_container)
        mode_layout.setContentsMargins(3, 3, 3, 3)
        mode_layout.setSpacing(4)

        self._toggle_app_btn = QPushButton("🖥️ Window Application")
        self._toggle_app_btn.setObjectName("toggleAppBtn")
        self._toggle_app_btn.setCheckable(True)
        self._toggle_app_btn.setChecked(True)
        self._toggle_app_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._toggle_web_btn = QPushButton("🌐 Website")
        self._toggle_web_btn.setObjectName("toggleWebBtn")
        self._toggle_web_btn.setCheckable(True)
        self._toggle_web_btn.setChecked(False)
        self._toggle_web_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._toggle_app_btn.clicked.connect(lambda: self._set_target_mode("app"))
        self._toggle_web_btn.clicked.connect(lambda: self._set_target_mode("website"))

        mode_layout.addWidget(self._toggle_app_btn)
        mode_layout.addWidget(self._toggle_web_btn)
        root.addWidget(mode_container)

        # ── History dropdown (1.7) ────────────────────────────────────
        lbl_hist = QLabel("Recent tasks")
        lbl_hist.setObjectName("fieldLabel")
        root.addWidget(lbl_hist)

        self._history_box = QComboBox()
        self._history_box.setObjectName("historyBox")
        self._history_box.addItem("— select a recent task —")
        self._history_box.currentIndexChanged.connect(self._on_history_selected)
        root.addWidget(self._history_box)

        # ── Task description ─────────────────────────────────────────
        lbl_task = QLabel("Task description")
        lbl_task.setObjectName("fieldLabel")
        root.addWidget(lbl_task)

        task_row = QHBoxLayout()
        task_row.setSpacing(6)
        self._task_edit = QLineEdit()
        self._task_edit.setPlaceholderText('e.g. "Insert an image into the document"')
        task_row.addWidget(self._task_edit)

        # Mic button (1.6)
        self._mic_btn = QPushButton("🎤")
        self._mic_btn.setObjectName("micBtn")
        self._mic_btn.setFixedSize(36, 34)
        self._mic_btn.setToolTip(
            "Click to dictate the task description" if _SR_AVAILABLE
            else "Voice input unavailable\n(pip install speechrecognition pyaudio)"
        )
        self._mic_btn.setCheckable(True)
        self._mic_btn.clicked.connect(self._on_mic_clicked)
        task_row.addWidget(self._mic_btn)
        root.addLayout(task_row)

        # ── App name (editable dropdown of open windows) ──────────────
        self._lbl_app = QLabel("Target application")
        self._lbl_app.setObjectName("fieldLabel")
        root.addWidget(self._lbl_app)

        app_row = QHBoxLayout()
        app_row.setSpacing(6)

        self._app_box = QComboBox()
        self._app_box.setObjectName("appBox")
        self._app_box.setEditable(True)            # allow free-text too
        self._app_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._app_box.lineEdit().setPlaceholderText(
            'Select or type an application name'
        )
        self._app_box.setCursor(Qt.CursorShape.PointingHandCursor)
        app_row.addWidget(self._app_box)

        self._refresh_btn = QPushButton("↺")
        self._refresh_btn.setObjectName("refreshBtn")
        self._refresh_btn.setFixedSize(36, 34)
        self._refresh_btn.setToolTip("Refresh open windows list")
        self._refresh_btn.clicked.connect(self._refresh_windows)
        app_row.addWidget(self._refresh_btn)
        root.addLayout(app_row)

        # ── Footer ───────────────────────────────────────────────────
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
    # 1.7  History
    # ------------------------------------------------------------------

    def _load_history(self) -> None:
        history = load_history()
        for entry in history:
            label = f"{entry['task'][:30]}… | {entry['app']}" if len(entry['task']) > 30 \
                    else f"{entry['task']} | {entry['app']}"
            self._history_box.addItem(label, userData=entry)

    @pyqtSlot(int)
    def _on_history_selected(self, index: int) -> None:
        if index <= 0:
            return
        entry = self._history_box.itemData(index)
        if entry:
            self._task_edit.setText(entry.get("task", ""))
            # Set the app combo text without triggering the index-changed signal
            self._app_box.setCurrentText(entry.get("app", ""))

    # ------------------------------------------------------------------
    # 1.6  Mic voice input
    # ------------------------------------------------------------------

    def _on_mic_clicked(self, checked: bool) -> None:
        if not checked:
            return   # button released mid-recording — ignore

        if not _SR_AVAILABLE:
            QMessageBox.information(
                self, "Voice Input Unavailable",
                "Install the required packages:\n\n"
                "    pip install speechrecognition pyaudio\n\n"
                "Then restart the application."
            )
            self._mic_btn.setChecked(False)
            return

        self._status_label.setText("🎤 Listening…")
        self._set_loading(True)

        self._mic_thread = QThread(self)
        self._mic_worker = _MicWorker()
        self._mic_worker.moveToThread(self._mic_thread)
        self._mic_thread.started.connect(self._mic_worker.run)
        self._mic_worker.succeeded.connect(self._on_mic_success)
        self._mic_worker.failed.connect(self._on_mic_failure)
        self._mic_worker.succeeded.connect(self._mic_thread.quit)
        self._mic_worker.failed.connect(self._mic_thread.quit)
        self._mic_thread.finished.connect(self._mic_thread.deleteLater)
        self._mic_thread.start()

    @pyqtSlot(str)
    def _on_mic_success(self, text: str) -> None:
        self._task_edit.setText(text)
        self._status_label.setText("✓ Transcribed!")
        self._mic_btn.setChecked(False)
        self._set_loading(False)

    @pyqtSlot(str)
    def _on_mic_failure(self, error: str) -> None:
        self._status_label.setText(f"⚠ {error}")
        self._mic_btn.setChecked(False)
        self._set_loading(False)

    # ------------------------------------------------------------------
    # Open-window scanner
    # ------------------------------------------------------------------

    def _refresh_windows(self) -> None:
        """Scan open windows on a background thread and populate _app_box."""
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("⏳")
        self._status_label.setText("Scanning windows…")

        self._scan_thread = QThread(self)
        self._scan_worker = _WindowScanWorker()
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.succeeded.connect(self._on_scan_success)
        self._scan_worker.failed.connect(self._on_scan_failure)
        self._scan_worker.succeeded.connect(self._scan_thread.quit)
        self._scan_worker.failed.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    @pyqtSlot(list)
    def _on_scan_success(self, titles: list) -> None:
        current = self._app_box.currentText()
        self._app_box.clear()
        self._app_box.addItems(titles)
        # Restore whatever the user had typed / selected
        if current:
            self._app_box.setCurrentText(current)
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("↺")
        self._status_label.setText(f"{len(titles)} windows found")
        QTimer.singleShot(2000, lambda: self._status_label.setText(""))

    @pyqtSlot(str)
    def _on_scan_failure(self, error: str) -> None:
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("↺")
        self._status_label.setText(f"⚠ Scan failed: {error[:40]}")

    # ------------------------------------------------------------------
    # Target Mode Switcher
    # ------------------------------------------------------------------

    def _set_target_mode(self, mode: str) -> None:
        self._target_mode = mode
        if mode == "app":
            self._toggle_app_btn.setChecked(True)
            self._toggle_web_btn.setChecked(False)
            self._lbl_app.setText("Target application")
            self._app_box.lineEdit().setPlaceholderText('Select or type an application name')
            self._refresh_windows()
        else:
            self._toggle_app_btn.setChecked(False)
            self._toggle_web_btn.setChecked(True)
            self._lbl_app.setText("Target website / URL")
            self._app_box.lineEdit().setPlaceholderText('Enter URL or select browser (e.g. https://google.com)')
            self._populate_website_presets()

    def _populate_website_presets(self) -> None:
        current = self._app_box.currentText()
        self._app_box.clear()
        presets = [
            "https://google.com",
            "https://github.com",
            "https://youtube.com",
            "https://wikipedia.org",
        ]
        self._app_box.addItems(presets)
        if current and current not in presets:
            self._app_box.insertItem(0, current)
        if current:
            self._app_box.setCurrentText(current)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        task = self._task_edit.text().strip()
        app  = self._app_box.currentText().strip()
        if not task or not app:
            self._status_label.setText("⚠ Both fields are required.")
            return

        self._set_loading(True)

        if self._target_mode == "website" and self._browser_connector is not None:
            # Phase 1: fetch DOM from extension, then generate
            self._status_label.setText("📡 Capturing DOM…")
            self._dom_thread = QThread(self)
            self._dom_worker = _DOMFetchWorker(self._browser_connector)
            self._dom_worker.moveToThread(self._dom_thread)
            self._dom_thread.started.connect(self._dom_worker.run)
            self._dom_worker.succeeded.connect(self._on_dom_fetched)
            self._dom_worker.failed.connect(self._on_dom_fetch_failed)
            self._dom_worker.succeeded.connect(self._dom_thread.quit)
            self._dom_worker.failed.connect(self._dom_thread.quit)
            self._dom_thread.finished.connect(self._dom_thread.deleteLater)
            self._dom_thread.start()
        else:
            # App mode or no connector: generate directly
            self._start_generation(dom_snapshot=None)

    def _start_generation(self, dom_snapshot: list | None) -> None:
        """Kick off the Gemini generation worker with an optional DOM snapshot."""
        task = self._task_edit.text().strip()
        app  = self._app_box.currentText().strip()
        self._thread = QThread(self)
        self._worker = _GeneratorWorker(
            self._generator, task, app,
            target_mode=self._target_mode,
            dom_snapshot=dom_snapshot,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.succeeded.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.succeeded.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @pyqtSlot(list)
    def _on_dom_fetched(self, tree: list) -> None:
        """Called when DOM fetch succeeds. Saves snapshot and starts generation."""
        # Save dom_snapshot.json regardless of whether tree is empty
        os.makedirs(_OUTPUT_DIR, exist_ok=True)
        snapshot_path = os.path.abspath(_DOM_SNAPSHOT_FILE)
        with open(snapshot_path, "w", encoding="utf-8") as fh:
            json.dump(tree, fh, indent=2)

        if tree:
            self._status_label.setText(f"📄 DOM captured ({len(tree)} nodes)")
        else:
            self._status_label.setText("⚠ Extension not connected — generating without DOM")

        self._start_generation(dom_snapshot=tree if tree else None)

    @pyqtSlot(str)
    def _on_dom_fetch_failed(self, error: str) -> None:
        """Called when DOM fetch errors out. Falls back to generation without DOM."""
        self._status_label.setText(f"⚠ DOM fetch failed: {error[:40]}")
        self._start_generation(dom_snapshot=None)

    @pyqtSlot(dict)
    def _on_success(self, result: dict) -> None:
        self._set_loading(False)
        task = self._task_edit.text().strip()
        app  = self._app_box.currentText().strip()

        # Save to history (1.7)
        save_to_history(task, app)

        task_dict = {
            "name":    task,
            "app":     app,
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
            self, "Generation Failed",
            f"Could not generate task steps:\n\n{error}",
        )

    # ------------------------------------------------------------------
    # Loading state
    # ------------------------------------------------------------------

    def _set_loading(self, loading: bool) -> None:
        self._start_btn.setEnabled(not loading)
        self._task_edit.setEnabled(not loading)
        self._app_box.setEnabled(not loading)
        self._refresh_btn.setEnabled(not loading)
        self._mic_btn.setEnabled(not loading)
        self._history_box.setEnabled(not loading)
        if loading:
            self._dot_count = 0
            if "🎤" not in self._status_label.text():
                self._status_label.setText("Generating…")
            self._dot_timer.start()
        else:
            self._dot_timer.stop()

    def _tick_dots(self) -> None:
        self._dot_count = (self._dot_count + 1) % 4
        dots = "." * self._dot_count
        if "🎤" not in self._status_label.text():
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
