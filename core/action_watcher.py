"""Windows UIA accessibility event watcher.

Listens for WinEvent notifications (menu open, dialog open, focus change)
to detect when the user has interacted with the target element, then emits
``action_detected`` so the overlay can auto-advance to the next step.

No polling. No mouse hooks. Uses ``SetWinEventHook`` with
``WINEVENT_OUTOFCONTEXT`` so the callback runs in-process.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import threading
import time

from PyQt6.QtCore import QObject, QRect, QTimer, pyqtSignal

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WinEvent constants
# ---------------------------------------------------------------------------

WINEVENT_OUTOFCONTEXT      = 0x0000
EVENT_SYSTEM_MENUSTART     = 0x0004
EVENT_SYSTEM_MENUPOPUPSTART = 0x0006
EVENT_SYSTEM_DIALOGSTART   = 0x0010
EVENT_OBJECT_FOCUS         = 0x8005
EVENT_OBJECT_STATECHANGE   = 0x800A
EVENT_OBJECT_NAMECHANGE    = 0x800C

# Range covering all events we care about in one SetWinEventHook call
_EVENT_MIN = EVENT_SYSTEM_MENUSTART      # 0x0004
_EVENT_MAX = EVENT_OBJECT_NAMECHANGE     # 0x800C

# ---------------------------------------------------------------------------
# WINFUNCTYPE for the WinEvent callback
# ---------------------------------------------------------------------------

WinEventProc = ctypes.WINFUNCTYPE(
    None,
    ctypes.wintypes.HANDLE,   # hWinEventHook
    ctypes.wintypes.DWORD,    # event
    ctypes.wintypes.HWND,     # hwnd
    ctypes.wintypes.LONG,     # idObject
    ctypes.wintypes.LONG,     # idChild
    ctypes.wintypes.DWORD,    # idEventThread
    ctypes.wintypes.DWORD,    # dwmsEventTime
)


class ActionWatcher(QObject):
    """Emit :attr:`action_detected` when the user interacts with the target.

    Works by hooking Windows accessibility events — the most reliable and
    lowest-overhead method on Windows; no polling, no mouse hooks needed.

    Signals
    -------
    action_detected:
        Emitted (on the Qt main thread, after a 400 ms settle delay) when
        a menu, popup, or dialog opens, or focus moves near the spotlight.
    """

    action_detected: pyqtSignal = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rect: QRect = QRect()
        self._active: bool = False
        self._hook_handle = None
        self._loop_thread: threading.Thread | None = None
        self._loop_thread_id: int = 0
        self._install_time: float = 0.0   # monotonic time when hook was installed

        # Keep a persistent reference so the WINFUNCTYPE wrapper isn't GC'd
        self._proc_ref = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start_watching(self, spotlight_rect: QRect) -> None:
        """Begin watching for interaction events near *spotlight_rect*.

        Safe to call multiple times — stops any existing watch first.

        Parameters
        ----------
        spotlight_rect:
            Current spotlight area in screen coordinates. Used by the focus
            handler to filter events outside the target region.
        """
        self.stop_watching()
        self._rect = spotlight_rect
        self._active = True
        self._install_hook()
        _log.info("ActionWatcher: watching started for rect %s", spotlight_rect)

    def stop_watching(self) -> None:
        """Remove the WinEvent hook and stop the message loop thread."""
        self._active = False
        self._remove_hook()

    def update_rect(self, rect: QRect) -> None:
        """Update the spotlight rect without restarting the hook.

        Parameters
        ----------
        rect:
            New spotlight area.
        """
        self._rect = rect

    def shutdown(self) -> None:
        """Alias for :meth:`stop_watching` — called on application exit."""
        self.stop_watching()

    # ------------------------------------------------------------------
    # Hook install / remove
    # ------------------------------------------------------------------

    def _install_hook(self) -> None:
        """Register the WinEvent hook and start the message-pump thread."""

        # Build callback — must store reference or GC will collect it
        proc = WinEventProc(self._on_win_event)
        self._proc_ref = proc

        self._install_time = time.monotonic()
        handle = ctypes.windll.user32.SetWinEventHook(
            _EVENT_MIN,
            _EVENT_MAX,
            None,          # hmodWinEventProc: None = out-of-context
            proc,
            0,             # idProcess: 0 = all processes
            0,             # idThread:  0 = all threads
            WINEVENT_OUTOFCONTEXT,
        )

        if not handle:
            _log.error("ActionWatcher: SetWinEventHook failed")
            self._proc_ref = None
            return

        self._hook_handle = handle
        _log.debug("ActionWatcher: hook installed (handle=%s)", handle)

        # Run a Windows message loop on a daemon thread so WinEvent
        # callbacks are delivered (WINEVENT_OUTOFCONTEXT requires a loop).
        self._loop_thread = threading.Thread(
            target=self._run_message_loop, daemon=True, name="ActionWatcherLoop"
        )
        self._loop_thread.start()

    def _remove_hook(self) -> None:
        """Unhook and signal the message loop to exit."""
        if self._hook_handle:
            ctypes.windll.user32.UnhookWinEvent(self._hook_handle)
            self._hook_handle = None
            _log.debug("ActionWatcher: hook removed")

        # Post WM_QUIT (0x0012) to the pump thread so GetMessage() returns 0
        if self._loop_thread_id:
            ctypes.windll.user32.PostThreadMessageW(
                self._loop_thread_id, 0x0012, 0, 0
            )
            self._loop_thread_id = 0

        self._proc_ref = None

    # ------------------------------------------------------------------
    # Message loop (runs on daemon thread)
    # ------------------------------------------------------------------

    def _run_message_loop(self) -> None:
        """Pump Windows messages until WM_QUIT is posted."""
        self._loop_thread_id = threading.current_thread().ident  # type: ignore[assignment]
        msg = ctypes.wintypes.MSG()
        _log.debug("ActionWatcher: message loop started (tid=%d)", self._loop_thread_id)
        while ctypes.windll.user32.GetMessageW(
            ctypes.byref(msg), None, 0, 0
        ) > 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        _log.debug("ActionWatcher: message loop exited")

    # ------------------------------------------------------------------
    # WinEvent callback
    # ------------------------------------------------------------------

    def _on_win_event(
        self,
        h_hook,
        event: int,
        hwnd,
        id_object: int,
        id_child: int,
        id_event_thread: int,
        dw_event_time: int,
    ) -> None:
        """Invoked by Windows for every accessibility event in the watched range."""
        if not self._active:
            return

        # Grace period: ignore events fired within 1.5 s of hook installation.
        # This filters false positives from pywinauto COM init and app startup.
        if time.monotonic() - self._install_time < 1.5:
            return

        try:
            if event in (
                EVENT_SYSTEM_MENUSTART,
                EVENT_SYSTEM_MENUPOPUPSTART,
            ):
                # Any menu opening is unambiguous user interaction.
                _log.info("ActionWatcher: menu event 0x%04X — advancing", event)
                self._fire()

            elif event == EVENT_SYSTEM_DIALOGSTART:
                # A dialog opened (e.g. Save As) — action is complete.
                _log.info("ActionWatcher: dialog event — advancing")
                self._fire()

            elif event == EVENT_OBJECT_FOCUS:
                # Focus changed — check if near the spotlight rect.
                self._check_focus_near_rect(hwnd, id_object, id_child)

        except Exception as exc:  # noqa: BLE001
            # Never raise from a WinEvent callback.
            _log.debug("ActionWatcher: exception in callback: %s", exc)

    def _check_focus_near_rect(self, hwnd, id_object: int, id_child: int) -> None:
        """Advance if the newly-focused element overlaps the spotlight rect."""
        if not self._rect.isValid():
            return
        try:
            acc = ctypes.POINTER(ctypes.c_void_p)()
            child_id = ctypes.wintypes.VARIANT()
            hr = ctypes.windll.oleacc.AccessibleObjectFromEvent(
                hwnd, id_object, id_child,
                ctypes.byref(acc),
                ctypes.byref(child_id),
            )
            if hr != 0 or not acc:
                return

            # IAccessible::accLocation — vtable slot 22 (0-indexed from IUnknown)
            # Signature: accLocation(pxLeft, pyTop, pcxWidth, pcyHeight, varChild)
            left = ctypes.c_long(0)
            top  = ctypes.c_long(0)
            w    = ctypes.c_long(0)
            h    = ctypes.c_long(0)
            variant_self = ctypes.wintypes.VARIANT()
            variant_self.vt = 3  # VT_I4
            variant_self.lVal = id_child if id_child else 0

            # Call through the vtable at index 22
            vtable = ctypes.cast(acc, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
            fn_ptr = vtable[0][22]
            acc_location = ctypes.WINFUNCTYPE(
                ctypes.HRESULT,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_long),
                ctypes.POINTER(ctypes.c_long),
                ctypes.POINTER(ctypes.c_long),
                ctypes.POINTER(ctypes.c_long),
                ctypes.wintypes.VARIANT,
            )(fn_ptr)
            hr2 = acc_location(
                acc, ctypes.byref(left), ctypes.byref(top),
                ctypes.byref(w), ctypes.byref(h), variant_self,
            )
            if hr2 != 0:
                return

            el_rect = QRect(left.value, top.value, w.value, h.value)
            if el_rect.intersects(self._rect.adjusted(-32, -32, 32, 32)):
                _log.info(
                    "ActionWatcher: focused element %s overlaps spotlight — advancing",
                    el_rect,
                )
                self._fire()

        except Exception as exc:  # noqa: BLE001
            _log.debug("ActionWatcher: focus check failed: %s", exc)

    # ------------------------------------------------------------------
    # Fire — emit signal on Qt main thread after settle delay
    # ------------------------------------------------------------------

    def _fire(self) -> None:
        """Deactivate, clean up, and emit :attr:`action_detected` after 400 ms."""
        if not self._active:
            return           # guard against duplicate events
        self._active = False
        self._remove_hook()
        # QTimer.singleShot is thread-safe in PyQt6; schedules on the main thread.
        QTimer.singleShot(400, self.action_detected)
        _log.info("ActionWatcher: action_detected will fire in 400 ms")
