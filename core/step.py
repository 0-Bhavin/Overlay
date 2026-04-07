from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Step:
    """Represents a single guided step in the AI overlay workflow."""

    id: int
    target: str                          # Human-readable name of the UI element, e.g. "Insert tab"
    tooltip: str                         # Instruction shown to the user
    action: str = "click"               # "click" | "type" | "scroll" | "hover"
    spotlight_shape: str = "rect"       # "rect" | "circle"
    animation: str = "pulse"            # "pulse" | "arrow" | "none"
    coords: Optional[tuple[int, int, int, int]] = None  # (x, y, w, h) — filled at runtime by coord resolver

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: dict) -> "Step":
        """Create a Step from a plain dict (as parsed from JSON).

        Only ``id``, ``target``, and ``tooltip`` are required keys.
        All other fields fall back to their dataclass defaults when absent.
        """
        return cls(
            id=d["id"],
            target=d["target"],
            tooltip=d["tooltip"],
            action=d.get("action", "click"),
            spotlight_shape=d.get("spotlight_shape", "rect"),
            animation=d.get("animation", "pulse"),
            coords=tuple(d["coords"]) if d.get("coords") is not None else None,
        )
