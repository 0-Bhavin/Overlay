from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Step:
    """Represents a single guided step in the AI overlay workflow.

    Supports both **desktop** (Windows UIA) and **web** (DOM) targets via the
    ``target_type`` discriminator field.  All web-specific data is stored in
    ``web_element`` so downstream resolvers have what they need without further
    Gemini calls.
    """

    id: int
    target: str                          # Human-readable name of the UI element, e.g. "Insert tab"
    tooltip: str                         # Short instruction shown to the user (≤ 20 words)
    action: str = "click"               # "click" | "type" | "scroll" | "hover"
    spotlight_shape: str = "rect"       # "rect" | "circle"
    animation: str = "pulse"            # "pulse" | "arrow" | "none"
    coords: Optional[tuple[int, int, int, int]] = None  # (L, T, R, B) screen pixels — filled at runtime
    explanation: str = ""              # Longer why/how explanation for "More info" panel (1.10)
    cache_hit: bool = False             # True if coordinates were resolved from local cache

    # ------------------------------------------------------------------
    # Web target fields (ignored for desktop steps)
    # ------------------------------------------------------------------

    target_type: str = "desktop"
    """``"desktop"`` → resolve via Windows UIA (UIAResolver).
    ``"web"``     → resolve via browser DOM (WebResolver).
    A single Task can mix both types across its steps.
    """

    web_element: Optional[dict] = None
    """Raw element descriptor produced by Gemini's website prompt.

    Expected keys (all optional — WebResolver tolerates missing ones):
        ``id``           – DOM id attribute (most reliable lookup key)
        ``tag``          – HTML tag name  (e.g. ``"button"``)
        ``text``         – Visible text / aria-label
        ``role``         – ARIA role
        ``aria_label``   – aria-label attribute
        ``name``         – name attribute (inputs)
        ``xpath``        – XPath fallback
        ``css_selector`` – CSS selector fallback
        ``data_testid``  – data-testid attribute
        ``parent_path``  – list[str] ancestor tag names (informational)

    ``None`` for desktop steps.
    """

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: dict) -> "Step":
        """Create a Step from a plain dict (as parsed from JSON).

        Handles **two schemas**:

        Desktop schema (existing)::

            {
                "id": 1,
                "target": "Insert tab",
                "tooltip": "Click the Insert tab.",
                ...
            }

        Website schema (Gemini website-mode output, normalised by
        :meth:`GeminiTaskGenerator._normalize_website_result`)::

            {
                "id": 1,
                "target_type": "web",
                "target": "Sign in",
                "tooltip": "Click the Sign in link.",
                "web_element": {
                    "tag": "a",
                    "text": "Sign in",
                    "id": 29,
                    ...
                }
            }

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
            explanation=d.get("explanation", ""),   # graceful fallback for old JSON
            cache_hit=d.get("cache_hit", False),
            target_type=d.get("target_type", "desktop"),
            web_element=d.get("web_element"),
        )
