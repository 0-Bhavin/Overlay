"""Common UI Connector interface and node data model.

Provides a unified interface and standard node format for UI hierarchy inspection
across Windows desktop applications and web browsers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Callable


@dataclass
class UINode:
    """Standardized representation of a UI element on any platform."""

    id: int | str
    type: str
    text: str
    role: str
    enabled: bool
    visible: bool
    bounds: dict[str, int]  # {"x": int, "y": int, "width": int, "height": int}

    def to_dict(self) -> dict[str, Any]:
        """Convert UINode to dictionary matching common JSON schema."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UINode:
        """Construct UINode from dictionary."""
        bounds = data.get("bounds") or {"x": 0, "y": 0, "width": 0, "height": 0}
        return cls(
            id=data.get("id", ""),
            type=data.get("type", "unknown"),
            text=data.get("text", ""),
            role=data.get("role", "generic"),
            enabled=bool(data.get("enabled", True)),
            visible=bool(data.get("visible", True)),
            bounds={
                "x": int(bounds.get("x", 0)),
                "y": int(bounds.get("y", 0)),
                "width": int(bounds.get("width", 0)),
                "height": int(bounds.get("height", 0)),
            },
        )


class UIConnector(ABC):
    """Abstract Base Class for platform UI connectors (Windows, Browser, etc.)."""

    @abstractmethod
    def get_tree(self) -> list[dict[str, Any]]:
        """Extract and return current simplified UI tree as list of node dicts."""
        pass

    @abstractmethod
    def highlight(self, element_id: int | str) -> bool:
        """Highlight a target UI element by its identifier."""
        pass

    @abstractmethod
    def wait_for_click(self, element_id: int | str, timeout: float = 10.0) -> bool:
        """Wait until element with specified ID is clicked by user."""
        pass

    @abstractmethod
    def observe_changes(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback to handle incremental tree or state changes."""
        pass
