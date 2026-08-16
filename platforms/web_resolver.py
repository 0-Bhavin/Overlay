"""Browser DOM element resolver.

Converts a web step's ``web_element`` descriptor into absolute screen
coordinates ``(L, T, R, B)`` by:

1. Asking the Chrome/Edge extension for live viewport geometry
   (``window.screenX/Y``, toolbar height = ``outerHeight - innerHeight``).
2. Asking the extension to locate the element by the priority chain
   id → name → data-testid → aria-label → xpath (fresh ``getBoundingClientRect()``
   at call-time, not stale snapshot data).
3. Adding the browser window screen offset to produce physical screen pixels,
   then returning ``(L, T, R, B)`` — identical to what :class:`UIAResolver.get_coords`
   returns, so the rest of the overlay stack needs zero changes.

Communication uses the existing :class:`~platforms.browser_connector.BrowserConnector`
WebSocket bridge (already open on ``ws://127.0.0.1:8765``).  No new dependencies.
"""
from __future__ import annotations

import logging
import uuid

from platforms.uia_resolver import ElementNotFoundError

_log = logging.getLogger(__name__)

# How long to wait for each WebSocket round-trip (seconds)
_VIEWPORT_TIMEOUT = 3.0
_RESOLVE_TIMEOUT  = 5.0


class WebResolver:
    """Resolve a web element's screen coordinates via the browser extension.

    Parameters
    ----------
    browser_connector:
        A running :class:`~platforms.browser_connector.BrowserConnector` instance.
    """

    def __init__(self, browser_connector) -> None:
        self._bc = browser_connector

    # ------------------------------------------------------------------
    # Primary public method — same contract as UIAResolver.get_coords
    # ------------------------------------------------------------------

    def resolve(self, step) -> tuple[int, int, int, int] | None:
        """Return ``(L, T, R, B)`` absolute screen coordinates for *step*.

        Parameters
        ----------
        step:
            A :class:`~core.step.Step` with ``target_type == "web"`` and
            a populated ``web_element`` dict.

        Returns
        -------
        tuple[int, int, int, int] | None
            Absolute screen coordinates or ``None`` if the element could
            not be located.

        Raises
        ------
        ElementNotFoundError
            When the extension is not connected or the element cannot be
            found after exhausting all selector strategies.
        """
        if self._bc is None or self._bc.active_socket is None:
            raise ElementNotFoundError(
                "browser", step.target,
                ["BrowserConnector not connected — is the extension loaded?"],
            )

        # 1. Get live viewport geometry from the extension
        vp = self._get_viewport_info()
        if vp is None:
            raise ElementNotFoundError(
                "browser", step.target,
                ["get_viewport_info timed out — is the extension active on a real tab?"],
            )

        screen_x: int  = vp["screenX"]
        screen_y: int  = vp["screenY"]
        # toolbar_h (CSS pixels) = all browser chrome above the viewport
        # (OS title bar + tab strip + address bar + bookmarks bar etc.)
        toolbar_h: int = vp["outerHeight"] - vp["innerHeight"]

        # devicePixelRatio converts CSS pixels → physical screen pixels.
        # Qt (AA_Use96Dpi) works in physical pixels; the browser reports
        # screenX/Y, outerHeight, innerHeight and getBoundingClientRect()
        # all in CSS pixels, so every value must be scaled by DPR.
        dpr: float = max(1.0, float(vp.get("devicePixelRatio", 1.0)))

        def _phys(css: float) -> int:
            """Round a CSS pixel measurement to the nearest physical pixel."""
            return round(float(css) * dpr)

        # content_left/top = physical coordinates of the viewport's top-left corner.
        # Chrome has NO left-side horizontal chrome (scrollbar is on the right),
        # so content_left = screenX × DPR only.
        content_left: int = _phys(screen_x)
        content_top:  int = _phys(screen_y) + _phys(toolbar_h)

        _log.info(
            "WebResolver: dpr=%.2f  screen_css=(%d,%d) toolbar_css=%dpx"
            " → viewport_phys=(%d,%d)",
            dpr, screen_x, screen_y, toolbar_h,
            content_left, content_top,
        )

        # 2. Resolve the element in the live DOM
        elem_info = self._resolve_element(step.web_element or {}, step.target)
        if elem_info is None:
            raise ElementNotFoundError(
                "browser", step.target,
                ["resolve_element returned no match — element may not be visible"],
            )

        rect  = elem_info["rect"]           # viewport-relative CSS pixels from getBoundingClientRect()
        _log.info(
            "WebResolver: DOM rect css=(x=%s y=%s w=%s h=%s) resolved_by=%s",
            rect.get("x"), rect.get("y"), rect.get("width"), rect.get("height"),
            elem_info.get("resolvedBy", "?"),
        )

        # Persist the assigned data-ai-overlay-id so ActionWatcher can
        # filter clicks to this specific element.
        if step.web_element is not None:
            step.web_element["resolved_element_id"] = elem_info.get("elementId")

        # 3. Convert viewport-relative CSS pixels → absolute physical screen pixels.
        #    content_left/top is already in physical pixels.
        #    rect values are CSS pixels → multiply by DPR via _phys().
        l = content_left + _phys(rect.get("x", 0))
        t = content_top  + _phys(rect.get("y", 0))
        r = l + _phys(rect.get("width",  0))
        b = t + _phys(rect.get("height", 0))

        _log.info(
            "WebResolver: resolved %r → physical (%d, %d, %d, %d)",
            step.target, l, t, r, b,
        )
        return (l, t, r, b)

    # ------------------------------------------------------------------
    # WebSocket helpers — request/response pattern via BrowserConnector
    # ------------------------------------------------------------------

    def _send_and_wait(self, payload: dict, timeout: float) -> dict | None:
        """Send *payload* over the WebSocket bridge and wait for the reply.

        Reuses :class:`BrowserConnector`'s internal ``_pending_responses``
        dict and asyncio loop so concurrency is handled correctly.
        """
        import asyncio
        import json

        bc = self._bc
        if bc.active_socket is None or bc._loop is None:
            return None

        req_id = str(uuid.uuid4())
        payload["req_id"] = req_id

        fut: asyncio.Future = bc._loop.create_future()
        bc._pending_responses[req_id] = fut

        asyncio.run_coroutine_threadsafe(
            bc.active_socket.send(json.dumps(payload)), bc._loop
        )

        try:
            result = asyncio.run_coroutine_threadsafe(
                asyncio.wait_for(fut, timeout=timeout), bc._loop
            ).result()
            return result
        except Exception as exc:
            _log.warning("WebResolver._send_and_wait timed out or failed: %s", exc)
            bc._pending_responses.pop(req_id, None)
            return None

    def _get_viewport_info(self) -> dict | None:
        """Ask the extension for live window geometry.

        Expected response:
        ``{screenX, screenY, outerWidth, outerHeight, innerWidth, innerHeight}``
        """
        return self._send_and_wait(
            {"type": "get_viewport_info"},
            timeout=_VIEWPORT_TIMEOUT,
        )

    def _resolve_element(self, selector: dict, target_name: str) -> dict | None:
        """Ask the extension to locate an element and return a fresh bbox.

        Parameters
        ----------
        selector:
            The ``web_element`` descriptor from the :class:`~core.step.Step`.
            May contain any subset of: ``id``, ``tag``, ``text``, ``role``,
            ``aria_label``, ``name``, ``xpath``, ``css_selector``, ``data_testid``.
        target_name:
            Human-readable name for logging.

        Returns
        -------
        dict | None
            ``{"found": True, "elementId": "...", "rect": {...}, "resolvedBy": "..."}``
            or ``None`` on timeout / not-found.
        """
        resp = self._send_and_wait(
            {"type": "resolve_element", "selector": selector, "targetName": target_name},
            timeout=_RESOLVE_TIMEOUT,
        )
        if resp is None:
            return None
        if not resp.get("found", False):
            _log.warning(
                "WebResolver: extension could not find %r (tried: %s)",
                target_name, resp.get("resolvedBy", "none"),
            )
            return None
        return resp
