"""Windows UI Automation coordinate resolver using pywinauto.

Uses the Application.connect(path=...) pattern for reliable window finding,
then searches descendants for UI elements.
"""
from __future__ import annotations

import concurrent.futures
import logging
import re

_log = logging.getLogger(__name__)

try:
    from pywinauto import Desktop
    from pywinauto.application import Application
    _PYWINAUTO_AVAILABLE = True
except ImportError:
    _PYWINAUTO_AVAILABLE = False
    _log.warning("pywinauto not installed — UIAResolver will return None for all calls.")

# Mapping from human-readable app names to executable names
_APP_EXE_MAP: dict[str, str] = {
    "microsoft word": "WINWORD.EXE",
    "word": "WINWORD.EXE",
    "microsoft excel": "EXCEL.EXE",
    "excel": "EXCEL.EXE",
    "microsoft powerpoint": "POWERPNT.EXE",
    "powerpoint": "POWERPNT.EXE",
    "notepad": "notepad.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
}


class UIAResolver:
    """Resolve UI element coordinates via Windows UI Automation (pywinauto UIA backend)."""

    def find_window(self, app_name: str):
        """Return a pywinauto window wrapper for *app_name*.

        Strategy 1: connect by exe path using _APP_EXE_MAP (most reliable).
        Strategy 2: fallback to Desktop windows title matching.
        """
        if not _PYWINAUTO_AVAILABLE:
            return None

        needle = app_name.lower().strip()

        # ── Strategy 1: connect by exe path ───────────────────────────
        exe = _APP_EXE_MAP.get(needle)
        if exe:
            try:
                app = Application(backend="uia").connect(path=exe)
                top = app.top_window()
                top.wait("visible", timeout=5)
                _log.info("find_window [exe]: connected to %r via %s", app_name, exe)
                return top
            except Exception as exc:
                _log.debug("find_window [exe]: failed for %s: %s", exe, exc)

        # ── Strategy 2: Desktop windows title matching (fallback) ─────
        try:
            desktop = Desktop(backend="uia")
            windows = desktop.windows()
            words = [w for w in needle.split() if len(w) >= 4]
            last_word = needle.split()[-1] if needle.split() else needle

            pass1, pass2, pass3 = [], [], []
            for win in windows:
                try:
                    title = win.window_text()
                    if not title:
                        continue
                    title_lower = title.lower()

                    if needle in title_lower:
                        pass1.append(win)
                    elif any(w in title_lower for w in words):
                        pass2.append(win)
                    elif last_word in title_lower:
                        pass3.append(win)
                except Exception:
                    continue

            for candidates, label in ((pass1, "full-phrase"), (pass2, "word"), (pass3, "last-word")):
                if candidates:
                    win = candidates[0]
                    try:
                        app = Application(backend="uia").connect(handle=win.handle)
                        top = app.top_window()
                        _log.info("find_window [%s]: found %r -> %r", label, app_name, top.window_text())
                        return top
                    except Exception as exc:
                        _log.debug("Failed to connect to window: %s", exc)
                        continue

        except Exception as exc:
            _log.error("find_window error: %s", exc)

        _log.warning("find_window: no window found for %r", app_name)
        return None

    def find_element(self, app_name: str, target_name: str):
        """Locate a UI element by name inside the application window.

        Strategy 1: child_window(title=..., control_type="Button")
        Strategy 2: three-pass descendants scan (exact → partial → fallback)
        """
        if not _PYWINAUTO_AVAILABLE:
            return None

        try:
            wrapper = self.find_window(app_name)
            if wrapper is None:
                _log.warning("find_element: window not found for app %r", app_name)
                return None

            # Strip common suffixes Gemini adds that UIA does not use
            clean = re.sub(
                r"(?i)\s*(menu|button|option|tab|box|field|input|bar|item|link|text|area)\s*$",
                "", target_name
            ).strip()

            # ── Strategy 1: child_window with control_type ────────────
            for ctrl_type in ("Button", "MenuItem", "TabItem", "ListItem"):
                try:
                    el = wrapper.child_window(title=clean, control_type=ctrl_type)
                    if el.exists(timeout=1):
                        rect = el.rectangle()
                        # Reject oversized containers (e.g. File ListBox spans full menu)
                        if rect.width() < 300 and rect.height() < 100:
                            _log.info("find_element [child_window %s]: found %r at (%d,%d,%d,%d)",
                                      ctrl_type, target_name, rect.left, rect.top, rect.right, rect.bottom)
                            return el
                        else:
                            _log.debug("find_element [child_window %s]: rejected oversized %r (%dx%d)",
                                       ctrl_type, target_name, rect.width(), rect.height())
                except Exception:
                    continue

            # ── Strategy 2: descendants scan ──────────────────────────
            def _get_descendants():
                return wrapper.descendants()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_get_descendants)
                try:
                    elements = future.result(timeout=5)
                except concurrent.futures.TimeoutError:
                    _log.warning("find_element: descendants() timed out after 5 seconds")
                    elements = []

            # Pass 1 — exact match with size filter
            for el in elements:
                try:
                    text = el.window_text()
                    if text and text.lower() == clean.lower():
                        rect = el.rectangle()
                        if rect.width() < 300 and rect.height() < 100:
                            _log.info("find_element: pass 1 (exact match) found %r at (%d,%d,%d,%d)",
                                      target_name, rect.left, rect.top, rect.right, rect.bottom)
                            return el
                except Exception:
                    continue

            # Pass 2 — partial match with size filter
            for el in elements:
                try:
                    text = el.window_text()
                    if text and clean.lower() in text.lower():
                        rect = el.rectangle()
                        if rect.width() < 300 and rect.height() < 100:
                            _log.info("find_element: pass 2 (partial match) found %r at (%d,%d,%d,%d)",
                                      target_name, rect.left, rect.top, rect.right, rect.bottom)
                            return el
                except Exception:
                    continue

            # Pass 3 — partial match with no size restriction (fallback)
            for el in elements:
                try:
                    text = el.window_text()
                    if text and clean.lower() in text.lower():
                        _log.info("find_element: pass 3 (partial match, no size restriction) found %r", target_name)
                        return el
                except Exception:
                    continue

        except Exception as exc:
            _log.error("find_element error: %s", exc)

        _log.warning("find_element: element not found for %r", target_name)
        return None

    def get_coords(self, element) -> tuple[int, int, int, int] | None:
        """Return ``(left, top, right, bottom)`` in Qt logical screen coordinates."""
        if element is None:
            return None
        try:
            rect = element.rectangle()
            w, h = rect.width(), rect.height()

            if w > 960 or h > 600:
                _log.warning("oversized element discarded: %dx%d", w, h)
                return None

            # PyWinauto returns PHYSICAL pixels; Qt6 uses LOGICAL pixels.
            # Divide by device pixel ratio to correct for DPI scaling (e.g. 125% = 1.25).
            try:
                from PyQt6.QtWidgets import QApplication
                dpr = QApplication.primaryScreen().devicePixelRatio()
            except Exception:
                dpr = 1.0

            _log.debug("get_coords: physical=(%d,%d,%d,%d) dpr=%.2f",
                       rect.left, rect.top, rect.right, rect.bottom, dpr)

            return (
                int(rect.left  / dpr),
                int(rect.top   / dpr),
                int(rect.right / dpr),
                int(rect.bottom/ dpr),
            )
        except Exception as exc:
            _log.error("get_coords error: %s", exc)
            return None
