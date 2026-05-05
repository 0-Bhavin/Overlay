"""Optional Windows SAPI text-to-speech engine (feature 1.5).

Silently disabled when *pywin32* is not installed.

COM THREADING — why we do NOT import pythoncom / win32com at module level
-------------------------------------------------------------------------
``import pythoncom`` calls ``CoInitialize()`` on the importing thread as a
side-effect of the C-extension being loaded.  If that thread is the main
thread, it locks the main-thread COM apartment before ``UIAResolver``
(via pywinauto / comtypes) has a chance to set *its* preferred apartment
model, causing the ``RPC_E_CHANGED_MODE`` / WinError -2147417850 crash.

We avoid this by:
  1. Using ``importlib.util.find_spec`` to detect pywin32 — no import,
     no COM touch.
  2. Importing ``pythoncom`` and ``win32com.client`` only inside
     ``_TTSWorker.initialize()``, which Qt routes onto the background
     worker thread after ``moveToThread`` completes.

This ensures the main thread is NEVER touched by COM from this module,
so pywinauto can initialise UIAResolver freely.
"""
from __future__ import annotations

import importlib.util
import logging

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

_log = logging.getLogger(__name__)

# Detect availability WITHOUT importing (avoids CoInitialize on main thread)
_SAPI_AVAILABLE: bool = (
    importlib.util.find_spec("win32com")  is not None and
    importlib.util.find_spec("pythoncom") is not None
)
if not _SAPI_AVAILABLE:
    _log.info("TTS: pywin32 not found — TTS disabled.")


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

class _TTSWorker(QObject):
    """Owns the SAPI COM object.  All COM work happens on this object's thread."""

    def __init__(self) -> None:
        super().__init__()
        self._speaker = None   # created in initialize(), never on the main thread

    @pyqtSlot()
    def initialize(self) -> None:
        """Called when the worker thread starts (connected to thread.started).

        Importing pythoncom and creating the SpVoice object here means COM
        is initialised only on the background thread, not the main thread.
        """
        if not _SAPI_AVAILABLE:
            return
        try:
            # Local imports — keeps COM completely off the main thread
            import pythoncom          # type: ignore[import]
            import win32com.client    # type: ignore[import]

            pythoncom.CoInitialize()
            self._speaker = win32com.client.Dispatch("SAPI.SpVoice")
            _log.info("TTS: SAPI initialised on worker thread.")
        except Exception as exc:  # noqa: BLE001
            _log.warning("TTS: SAPI init failed: %s", exc)

    @pyqtSlot(str)
    def speak(self, text: str) -> None:
        if self._speaker is None:
            return
        try:
            self._speaker.Speak(text, 1)   # SVSFlagsAsync = 1
        except Exception as exc:  # noqa: BLE001
            _log.warning("TTS speak error: %s", exc)

    @pyqtSlot()
    def stop(self) -> None:
        if self._speaker is None:
            return
        try:
            self._speaker.Speak("", 3)   # SVSFPurgeBeforeSpeak | SVSFlagsAsync
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class TTSEngine(QObject):
    """Thread-safe TTS facade.  Create once; call :meth:`speak` freely."""

    _speak_requested = pyqtSignal(str)
    _stop_requested  = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._enabled: bool = _SAPI_AVAILABLE

        self._worker = _TTSWorker()
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        # initialize() runs on the worker thread — COM stays off the main thread
        self._thread.started.connect(self._worker.initialize)
        self._speak_requested.connect(self._worker.speak)
        self._stop_requested.connect(self._worker.stop)
        self._thread.start()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True when pywin32 is installed."""
        return _SAPI_AVAILABLE

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = bool(value)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def speak(self, text: str) -> None:
        """Speak *text* asynchronously.  No-op when disabled or unavailable."""
        if self._enabled and text.strip():
            self._speak_requested.emit(text)

    def stop(self) -> None:
        """Interrupt any currently-playing speech."""
        self._stop_requested.emit()

    def shutdown(self) -> None:
        """Stop the background thread gracefully before app exit."""
        self.stop()
        self._thread.quit()
        self._thread.wait()
