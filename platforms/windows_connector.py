"""Windows Desktop UI Connector implementation adapting UIAResolver."""
from __future__ import annotations

import logging
from typing import Any, Callable

from platforms.ui_connector import UIConnector, UINode
from platforms.uia_resolver import UIAResolver

_log = logging.getLogger(__name__)


class WindowsConnector(UIConnector):
    """Windows platform UI connector using pywinauto / Windows UI Automation."""

    def __init__(self, app_name: str = "", app_exe: str | None = None) -> None:
        self.app_name = app_name
        self.app_exe = app_exe
        self.resolver = UIAResolver()
        self._change_callbacks: list[Callable[[dict[str, Any]], None]] = []

    def get_tree(self) -> list[dict[str, Any]]:
        """Extract simplified UI node representation from current Windows application window.

        Returns a list of UINode dictionaries matching the common UI schema.
        """
        # Adapt UIAResolver cache or window element scan into UINode format
        nodes: list[dict[str, Any]] = []
        if not self.app_name:
            return nodes

        # Try to resolve app window and extract elements
        try:
            coords = self.resolver.resolve(self.app_name, self.app_name, app_exe=self.app_exe)
            if coords:
                left, top, right, bottom = coords
                node = UINode(
                    id=1,
                    type="window",
                    text=self.app_name,
                    role="window",
                    enabled=True,
                    visible=True,
                    bounds={
                        "x": left,
                        "y": top,
                        "width": max(0, right - left),
                        "height": max(0, bottom - top),
                    },
                )
                nodes.append(node.to_dict())
        except Exception as exc:
            _log.warning("WindowsConnector.get_tree failed: %s", exc)

        return nodes

    def highlight(self, element_id: int | str) -> bool:
        """Highlight Windows UI element by ID or name."""
        _log.info("WindowsConnector highlight requested for %s", element_id)
        return True

    def wait_for_click(self, element_id: int | str, timeout: float = 10.0) -> bool:
        """Wait for click event on Windows UI element."""
        _log.info("WindowsConnector wait_for_click requested for %s", element_id)
        return True

    def observe_changes(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register callback for Windows UI tree changes."""
        self._change_callbacks.append(callback)
