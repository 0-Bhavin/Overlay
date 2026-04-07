"""Windows UI Automation coordinate resolver using pywinauto.

Uses multiple element-finding strategies in order, logging which one
succeeded.  Implements the same interface as ATSpiResolver.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

try:
    from pywinauto import Desktop
    from pywinauto.application import Application
    _PYWINAUTO_AVAILABLE = True
except ImportError:
    _PYWINAUTO_AVAILABLE = False
    _log.warning("pywinauto not installed — UIAResolver will return None for all calls.")


class UIAResolver:
    """Resolve UI element coordinates via Windows UI Automation (pywinauto UIA backend).

    Strategies tried in order for :meth:`find_element`:

    1. Exact ``child_window(title=...)`` match
    2. Partial substring scan of all descendants
    3. ``child_window(best_match=...)`` fuzzy match
    """

    # ------------------------------------------------------------------
    # Window discovery
    # ------------------------------------------------------------------

    def find_window(self, app_name: str):
        """Return a pywinauto window wrapper whose title matches *app_name*.

        Three-pass matching (first hit wins):

        1. Full phrase substring — ``"microsoft word"`` in title
        2. Any significant word (≥ 4 chars) from ``app_name`` in title
        3. Last word of ``app_name`` — e.g. ``"word"`` from ``"Microsoft Word"``

        This handles titles like ``"Document1 - Word"`` for ``"Microsoft Word"``.

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
        try:
            desktop   = Desktop(backend="uia")
            windows   = desktop.windows()
            needle    = app_name.lower().strip()
            words     = [w for w in needle.split() if len(w) >= 4]
            last_word = needle.split()[-1] if needle.split() else needle

            pass1, pass2, pass3 = [], [], []
            for win in windows:
                try:
                    title = win.window_text().lower()
                    if not title:
                        continue
                    if needle in title:
                        pass1.append((win, win.window_text()))
                    elif any(w in title for w in words):
                        pass2.append((win, win.window_text()))
                    elif last_word in title:
                        pass3.append((win, win.window_text()))
                except Exception:  # noqa: BLE001
                    continue

            for candidates, label in ((pass1, "full-phrase"), (pass2, "word"), (pass3, "last-word")):
                if candidates:
                    win, title = candidates[0]
                    _log.info("find_window [%s]: %r → %r", label, app_name, title)
                    return win

        except Exception as exc:  # noqa: BLE001
            _log.error("find_window error: %s", exc)

        _log.warning("find_window: no window found for %r", app_name)
        return None

    # ------------------------------------------------------------------
    # Element discovery — three strategies
    # ------------------------------------------------------------------

    def find_element(self, app_name: str, target_name: str):
        """Locate a UI element by name inside the application window.

        Strategies (tried in order):

        1. Exact ``child_window(title=target_name)``
        2. Partial substring match over all descendants
        3. Fuzzy ``child_window(best_match=target_name)``

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

        # Strip common suffixes Gemini adds that UIA does not use
        import re
        clean = re.sub(
            r"(?i)\s*(menu|button|option|tab|box|field|input|bar|item|link|text|area)\s*$",
            "", target_name
        ).strip()
        if clean != target_name:
            _log.info("find_element: stripped %r -> %r", target_name, clean)
        target_name = clean
        needle = target_name.lower()

        def _size_ok(el) -> bool:
            """Return True if the element's rect is a plausible interactive size."""
            try:
                r = el.rectangle()
                w, h = r.width(), r.height()
                if w > 400 or h > 200:
                    _log.warning(
                        "Discarding oversized element: %r at (%d, %d, %d, %d)",
                        target_name, r.left, r.top, w, h,
                    )
                    return False
                return True
            except Exception:  # noqa: BLE001
                return True   # unknown size → let it through

        # ── Strategy 1: exact title match ─────────────────────────────
        try:
            el = wrapper.child_window(title=target_name, found_index=0)
            el.wait("exists", timeout=1)
            if _size_ok(el):
                _log.info("find_element [exact]: found %r", target_name)
                return el
        except Exception:  # noqa: BLE001
            _log.debug("find_element [exact]: no match for %r", target_name)

        # ── Strategy 2: substring scan — exact sub-pass first ─────────
        try:
            exact_hit = None
            partial_hit = None
            for desc in wrapper.descendants():
                try:
                    text = desc.window_text().lower()
                    if not text:
                        continue
                    if text == needle and _size_ok(desc):
                        exact_hit = desc
                        break                          # perfect match — stop immediately
                    if partial_hit is None and needle in text and _size_ok(desc):
                        partial_hit = desc             # keep scanning for exact
                except Exception:  # noqa: BLE001
                    continue
            hit = exact_hit or partial_hit
            if hit is not None:
                _log.info(
                    "find_element [scan-%s]: found %r",
                    "exact" if hit is exact_hit else "partial",
                    target_name,
                )
                return hit
        except Exception as exc:  # noqa: BLE001
            _log.debug("find_element [scan]: failed — %s", exc)

        # ── Strategy 3: best_match fuzzy find ─────────────────────────
        try:
            el = wrapper.child_window(best_match=target_name)
            el.wait("exists", timeout=1)
            if _size_ok(el):
                _log.info("find_element [best_match]: found %r", target_name)
                return el
        except Exception:  # noqa: BLE001
            _log.debug("find_element [best_match]: no match for %r", target_name)

        # ── Strategy 4: control-type filtered scan ────────────────────
        _INTERACTIVE = {"Button", "MenuItem", "Edit", "ComboBox",
                        "CheckBox", "RadioButton", "ListItem"}
        try:
            for desc in wrapper.descendants():
                try:
                    ct = desc.element_info.control_type
                    if ct not in _INTERACTIVE:
                        continue
                    text = desc.window_text().lower()
                    if needle in text and _size_ok(desc):
                        _log.info(
                            "find_element [ctrl-type %s]: found %r", ct, target_name
                        )
                        return desc
                except Exception:  # noqa: BLE001
                    continue
        except Exception as exc:  # noqa: BLE001
            _log.debug("find_element [ctrl-type]: failed — %s", exc)

        _log.warning(
            "find_element: all strategies failed for %r in %r", target_name, app_name
        )
        return None

    # ------------------------------------------------------------------
    # Coordinate extraction
    # ------------------------------------------------------------------

    def get_coords(self, element) -> tuple[int, int, int, int] | None:
        """Return ``(x, y, width, height)`` in screen coordinates.

        Parameters
        ----------
        element:
            A pywinauto ``BaseWrapper`` as returned by :meth:`find_element`.

        Returns
        -------
        tuple[int, int, int, int] | None
        """
        if element is None:
            return None
        try:
            rect   = element.rectangle()
            w, h   = rect.width(), rect.height()
            coords = (rect.left, rect.top, w, h)
            _log.debug("get_coords: %s", coords)
            return coords
        except Exception as exc:  # noqa: BLE001
            _log.error("get_coords error: %s", exc)
            return None


