"""Hybrid coordinate resolver.

Routes each step to the correct backend:

* ``step.target_type == "web"``     → :class:`~platforms.web_resolver.WebResolver`
  (browser DOM via WebSocket bridge)
* ``step.target_type == "desktop"`` → :class:`~platforms.uia_resolver.UIAResolver`
  (Windows UI Automation via pywinauto)

Backward-compatible: callers that don't pass a ``step`` argument continue to
use the UIA path (existing behaviour unchanged).
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


class HybridResolver:
    """Resolve UI element coordinates via UIA (desktop) or WebResolver (web).

    Parameters
    ----------
    api_key:
        Ignored. Gemini fallback has been removed.
    """

    def __init__(self, api_key: str = "") -> None:
        # Try to instantiate UIAResolver; gracefully degrade if unavailable.
        try:
            from platforms.uia_resolver import UIAResolver  # type: ignore[import]
            self._uia = UIAResolver()
            _log.info("HybridResolver: UIAResolver initialised successfully.")
        except Exception as exc:  # noqa: BLE001
            _log.warning("HybridResolver: UIAResolver unavailable (%s).", exc)
            self._uia = None

        # WebResolver is instantiated lazily when first needed, with the
        # BrowserConnector injected at call time.
        self._web: object | None = None

    # ------------------------------------------------------------------
    # Primary public method
    # ------------------------------------------------------------------

    def resolve(
        self,
        app_name: str,
        target_name: str,
        app_exe: str | None = None,
        *,
        step=None,
        browser_connector=None,
    ) -> tuple[int, int, int, int] | None:
        """Return ``(L, T, R, B)`` screen coordinates for *target_name*.

        Routing:

        * When *step* is supplied and ``step.target_type == "web"``,
          delegates to :class:`~platforms.web_resolver.WebResolver` using the
          live browser DOM.  *browser_connector* must also be provided.
        * Otherwise delegates to :class:`~platforms.uia_resolver.UIAResolver`
          (existing desktop UIA path — identical to previous behaviour).

        Parameters
        ----------
        app_name:
            Application name fragment (used for UIA path).
        target_name:
            Human-readable name of the UI element.
        app_exe:
            Optional Windows process exe name (UIA path only).
        step:
            Optional :class:`~core.step.Step` instance.  When provided,
            ``step.target_type`` is used to select the resolver backend.
        browser_connector:
            Optional :class:`~platforms.browser_connector.BrowserConnector`.
            Required when routing to the web backend.

        Returns
        -------
        tuple[int, int, int, int] | None
            ``(L, T, R, B)`` screen coordinates, or ``None``.
        """
        from platforms.uia_resolver import ElementNotFoundError

        # ── Web path ─────────────────────────────────────────────────
        if step is not None and getattr(step, "target_type", "desktop") == "web":
            return self._resolve_web(step, browser_connector)

        # ── Desktop / UIA path (unchanged) ───────────────────────────
        if self._uia is not None:
            element = self._uia.find_element_with_retry(app_name, target_name, app_exe=app_exe)
            if element is not None:
                coords = self._uia.get_coords(element)
                if coords is not None:
                    _log.info("UIA resolved %r -> %s", target_name, coords)
                    return coords
                else:
                    raise ElementNotFoundError(
                        app_name, target_name,
                        ["Element found, but failed to retrieve coordinates"],
                    )
            else:
                raise ElementNotFoundError(
                    app_name, target_name,
                    ["find_element_with_retry returned None"],
                )
        else:
            raise ElementNotFoundError(
                app_name, target_name,
                ["UIAResolver is unavailable on this platform"],
            )

    # ------------------------------------------------------------------
    # Web routing helper
    # ------------------------------------------------------------------

    def _resolve_web(
        self,
        step,
        browser_connector,
    ) -> tuple[int, int, int, int] | None:
        """Delegate to :class:`~platforms.web_resolver.WebResolver`."""
        from platforms.uia_resolver import ElementNotFoundError

        if browser_connector is None:
            raise ElementNotFoundError(
                "browser", step.target,
                ["browser_connector is None — cannot resolve web step"],
            )

        try:
            from platforms.web_resolver import WebResolver  # local import avoids circular deps
        except ImportError as exc:
            raise ElementNotFoundError(
                "browser", step.target,
                [f"WebResolver import failed: {exc}"],
            ) from exc

        # Re-use cached instance if connector is the same object
        if self._web is None or getattr(self._web, "_bc", None) is not browser_connector:
            self._web = WebResolver(browser_connector)

        coords = self._web.resolve(step)   # raises ElementNotFoundError on failure
        _log.info("Web resolved %r -> %s", step.target, coords)
        return coords

    # ------------------------------------------------------------------
    # UIAResolver-compatible stub interface (unchanged)
    # ------------------------------------------------------------------

    def find_element(self, app_name: str, target_name: str, app_exe: str | None = None):  # noqa: ANN201
        """Stub — satisfies the resolver interface; always returns ``None``.

        Use :meth:`resolve` for the full lookup.
        """
        return None

    def get_coords(self, element) -> None:  # noqa: ANN001
        """Stub — satisfies the resolver interface; always returns ``None``."""
        return None
