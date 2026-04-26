"""Windows UI Automation coordinate resolver using pywinauto.

Connects to an application window using the precise UIA backend strategy:
  Application(backend="uia").connect(path=EXE)
  then child_window(title=..., control_type="Button") or descendant scan.

Coords are returned as (L, T, R, B) — left, top, right, bottom screen pixels.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

try:
    from pywinauto.application import Application
    _PYWINAUTO_AVAILABLE = True
except ImportError:
    _PYWINAUTO_AVAILABLE = False
    _log.warning("pywinauto not installed — UIAResolver will return None for all calls.")

# Map of common app-name fragments → exe path fragments to try in order.
# The resolver will attempt to connect to each until one succeeds.
_APP_EXE_MAP: dict[str, list[str]] = {
    "word":       ["WINWORD.EXE"],
    "excel":      ["EXCEL.EXE"],
    "powerpoint": ["POWERPNT.EXE"],
    "notepad":    ["notepad.exe"],
    "chrome":     ["chrome.exe"],
    "edge":       ["msedge.exe"],
    "firefox":    ["firefox.exe"],
    "explorer":   ["explorer.exe"],
    "paint":      ["mspaint.exe"],
    "calc":       ["calc.exe"],
}


def _exe_candidates(app_name: str) -> list[str]:
    """Return a list of likely exe names for *app_name*."""
    lower = app_name.lower()
    for key, exes in _APP_EXE_MAP.items():
        if key in lower:
            return exes
    # Fallback: use the last word as a best guess exe name
    last = lower.split()[-1] if lower.split() else lower
    return [last + ".exe", last.upper() + ".EXE"]


class UIAResolver:
    """Resolve UI element coordinates via Windows UI Automation (pywinauto UIA backend).

    Coords are returned as ``(L, T, R, B)`` — left, top, right, bottom in
    screen pixels, exactly as returned by pywinauto's ``rectangle()``.
    """

    # ------------------------------------------------------------------
    # Window discovery
    # ------------------------------------------------------------------

    def find_window(self, app_name: str):
        """Connect to the target application and return the top-level window.

        Uses ``Application(backend="uia").connect(path=exe)`` which is the
        most reliable UIA attach strategy. Tries each exe candidate in order.

        Parameters
        ----------
        app_name:
            Human-readable application name, e.g. ``"Microsoft Word"``.

        Returns
        -------
        WindowSpecification | None
        """
        if not _PYWINAUTO_AVAILABLE:
            return None

        for exe in _exe_candidates(app_name):
            try:
                app = Application(backend="uia").connect(path=exe, timeout=5)
                win = app.top_window()
                win.wait("visible", timeout=10)
                _log.info("find_window: connected to %r via exe %r", app_name, exe)
                return win
            except Exception as exc:  # noqa: BLE001
                _log.debug("find_window: exe %r failed — %s", exe, exc)
                continue

        _log.warning("find_window: no window found for %r", app_name)
        return None

    # ------------------------------------------------------------------
    # Element discovery
    # ------------------------------------------------------------------

    def find_element(self, app_name: str, target_name: str):
        """Locate a UI element by name inside the application window.

        Strategies (tried in order):

        1. ``child_window(title=target_name, control_type="Button")``
        2. ``child_window(title=target_name)`` — any control type
        3. Descendant scan: exact text match, then partial
        4. ``child_window(best_match=target_name)``

        Parameters
        ----------
        app_name:
            Identifies the target window (passed to :meth:`find_window`).
        target_name:
            Human-readable name of the element to locate.

        Returns
        -------
        BaseWrapper | None
        """
        if not _PYWINAUTO_AVAILABLE:
            return None

        wrapper = self.find_window(app_name)
        if wrapper is None:
            _log.warning("find_element: window not found for app %r", app_name)
            return None

        target_name = target_name.strip()
        needle = target_name.lower()

        # ── Strategy 1: exact title + Button control type ─────────────
        try:
            el = wrapper.child_window(title=target_name, control_type="Button")
            if el.exists(timeout=1):
                _log.info("find_element [Button]: found %r", target_name)
                return el
        except Exception:  # noqa: BLE001
            _log.debug("find_element [Button]: no match for %r", target_name)

        # ── Strategy 2: exact title, any control type ─────────────────
        try:
            el = wrapper.child_window(title=target_name, found_index=0)
            if el.exists(timeout=1):
                _log.info("find_element [exact-any]: found %r", target_name)
                return el
        except Exception:  # noqa: BLE001
            _log.debug("find_element [exact-any]: no match for %r", target_name)

        # ── Strategy 3: descendant scan (exact text → partial) ────────
        try:
            exact_hit = None
            partial_hit = None
            for desc in wrapper.descendants():
                try:
                    text = desc.window_text()
                    if not text:
                        continue
                    text_lower = text.lower()
                    if text_lower == needle:
                        exact_hit = desc
                        _log.info("find_element [scan-exact]: found %r (%s)",
                                  target_name, desc.friendly_class_name())
                        break
                    if partial_hit is None and needle in text_lower:
                        partial_hit = desc
                        _log.info("find_element [scan-partial]: found %r (%s)",
                                  target_name, desc.friendly_class_name())
                except Exception:  # noqa: BLE001
                    continue
            hit = exact_hit or partial_hit
            if hit is not None:
                return hit
        except Exception as exc:  # noqa: BLE001
            _log.debug("find_element [scan]: failed — %s", exc)

        # ── Strategy 4: best_match fuzzy ──────────────────────────────
        try:
            el = wrapper.child_window(best_match=target_name)
            if el.exists(timeout=1):
                _log.info("find_element [best_match]: found %r", target_name)
                return el
        except Exception:  # noqa: BLE001
            _log.debug("find_element [best_match]: no match for %r", target_name)

        _log.warning(
            "find_element: all strategies failed for %r in %r", target_name, app_name
        )
        return None

    # ------------------------------------------------------------------
    # Coordinate extraction — returns (L, T, R, B)
    # ------------------------------------------------------------------

    def get_coords(self, element) -> tuple[int, int, int, int] | None:
        """Return ``(L, T, R, B)`` screen coordinates.

        The rectangle is taken directly from pywinauto's ``element.rectangle()``
        and represents physical screen pixels (left, top, right, bottom).

        Parameters
        ----------
        element:
            A pywinauto ``BaseWrapper`` as returned by :meth:`find_element`.

        Returns
        -------
        tuple[int, int, int, int] | None
            ``(left, top, right, bottom)`` or ``None`` on error.
        """
        if element is None:
            return None
        try:
            rect = element.rectangle()
            coords = (rect.left, rect.top, rect.right, rect.bottom)
            _log.debug("get_coords: L=%d T=%d R=%d B=%d", *coords)
            return coords
        except Exception as exc:  # noqa: BLE001
            _log.error("get_coords error: %s", exc)
            return None
