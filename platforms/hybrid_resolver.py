"""Hybrid coordinate resolver.

Tries Windows UI Automation first (fast, exact).
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


class HybridResolver:
    """Resolve UI element coordinates via UIA.

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

    # ------------------------------------------------------------------
    # Primary public method
    # ------------------------------------------------------------------

    def resolve(
        self,
        app_name: str,
        target_name: str,
        app_exe: str | None = None,
    ) -> tuple[int, int, int, int] | None:
        """Return ``(x, y, w, h)`` screen coordinates for *target_name*.

        Tries UIAutomation first.

        Parameters
        ----------
        app_name:
            Application name fragment used to locate the target window with UIA.
        target_name:
            Human-readable name of the UI element to locate.
        app_exe:
            Optional Windows process exe name (e.g. ``"EXCEL.EXE"``).  When
            provided it is forwarded directly to the UIA backend so the correct
            process is targeted without relying on the static exe map.

        Returns
        -------
        tuple[int, int, int, int] | None
            Screen coordinates ``(x, y, width, height)``, or ``None`` if the
            element could not be found.
        """
        from platforms.uia_resolver import ElementNotFoundError

        if self._uia is not None:
            element = self._uia.find_element_with_retry(app_name, target_name, app_exe=app_exe)
            if element is not None:
                coords = self._uia.get_coords(element)
                if coords is not None:
                    _log.info(
                        "UIA resolved %r -> %s", target_name, coords
                    )
                    return coords
                else:
                    raise ElementNotFoundError(app_name, target_name, ["Element found, but failed to retrieve coordinates"])
            else:
                raise ElementNotFoundError(app_name, target_name, ["find_element_with_retry returned None"])
        else:
            raise ElementNotFoundError(app_name, target_name, ["UIAResolver is unavailable on this platform"])

    # ------------------------------------------------------------------
    # UIAResolver-compatible stub interface
    # ------------------------------------------------------------------

    def find_element(self, app_name: str, target_name: str, app_exe: str | None = None):  # noqa: ANN201
        """Stub — satisfies the resolver interface; always returns ``None``.

        Use :meth:`resolve` for the full lookup.
        """
        return None

    def get_coords(self, element) -> None:  # noqa: ANN001
        """Stub — satisfies the resolver interface; always returns ``None``."""
        return None
