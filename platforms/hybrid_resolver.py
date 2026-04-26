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
    ) -> tuple[int, int, int, int] | None:
        """Return ``(x, y, w, h)`` screen coordinates for *target_name*.

        Tries UIAutomation first.

        Parameters
        ----------
        app_name:
            Application name fragment used to locate the target window with UIA.
        target_name:
            Human-readable name of the UI element to locate.

        Returns
        -------
        tuple[int, int, int, int] | None
            Screen coordinates ``(x, y, width, height)``, or ``None`` if the
            element could not be found.
        """
        if self._uia is not None:
            try:
                element = self._uia.find_element(app_name, target_name)
                if element is not None:
                    coords = self._uia.get_coords(element)
                    if coords is not None:
                        _log.info(
                            "UIA resolved %r → %s", target_name, coords
                        )
                        return coords
            except Exception as exc:  # noqa: BLE001
                _log.warning("UIA lookup failed for %r: %s", target_name, exc)

        _log.warning(
            "UIA could not locate %r.", target_name
        )
        return None

    # ------------------------------------------------------------------
    # UIAResolver-compatible stub interface
    # ------------------------------------------------------------------

    def find_element(self, app_name: str, target_name: str):  # noqa: ANN201
        """Stub — satisfies the resolver interface; always returns ``None``.

        Use :meth:`resolve` for the full lookup.
        """
        return None

    def get_coords(self, element) -> None:  # noqa: ANN001
        """Stub — satisfies the resolver interface; always returns ``None``."""
        return None
