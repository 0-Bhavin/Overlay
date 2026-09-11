from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Step:
    """Represents a single guided step in the AI overlay workflow."""

    id: int
    target: str                          # Human-readable name of the UI element, e.g. "Insert tab"
    tooltip: str                         # Short instruction shown to the user (≤ 20 words)
    action: str = "click"               # "click" | "type" | "scroll" | "hover"
    spotlight_shape: str = "rect"       # "rect" | "circle"
    animation: str = "pulse"            # "pulse" | "arrow" | "none"
    coords: Optional[tuple[int, int, int, int]] = None  # (L, T, R, B) screen pixels — filled at runtime
    explanation: str = ""              # Longer why/how explanation for "More info" panel (1.10)
    cache_hit: bool = False             # True if coordinates were resolved from local cache
    element_id: Optional[int] = None    # DOM element ID for website-mode highlighting

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(
        cls, d: dict, default_id: int = 1,
        dom_lookup: dict | None = None,
        dom_text_lookup: dict | None = None,
    ) -> "Step":
        """Create a Step from a plain dict (as parsed from JSON).

        Supports standard step dicts as well as website mode step dicts
        (e.g., step_number, element dict, description).

        Parameters
        ----------
        d:
            The step dict from JSON.
        default_id:
            Fallback step number if neither ``id`` nor ``step_number`` is present.
        dom_lookup:
            Optional mapping of UINode IDs (int) to node dicts. When provided
            and the step has an ``element.id``, coords are resolved from the
            matching UINode's ``bounds`` field. Used for website-mode tasks.
        """
        step_id = d.get("id")
        if step_id is None:
            step_id = d.get("step_number", default_id)

        target = d.get("target")
        if not target and isinstance(d.get("element"), dict):
            elem = d["element"]
            target = (
                elem.get("text")
                or elem.get("aria_label")
                or elem.get("placeholder")
                or elem.get("id")
                or elem.get("name")
                or elem.get("tag")
                or ""
            )
        if not target:
            target = d.get("description", "Element")

        tooltip = d.get("tooltip") or d.get("description") or str(target)
        explanation = d.get("explanation") or (d.get("description") if d.get("tooltip") else "")

        # Resolve coords and element_id from DOM snapshot for website mode
        coords: tuple[int, int, int, int] | None = None
        element_id: int | None = None
        if d.get("coords") is not None:
            coords = tuple(d["coords"])
            print(f"[Step.from_dict #{step_id}] Using explicit coords from JSON: {coords}")
        elif dom_lookup:
            elem = d.get("element")
            if isinstance(elem, dict):
                elem_id = elem.get("id")
                if elem_id is not None:
                    try:
                        node = dom_lookup[int(elem_id)]
                        b = node.get("bounds") or {}
                        x = int(b.get("x", 0))
                        y = int(b.get("y", 0))
                        w = int(b.get("width", 0))
                        h = int(b.get("height", 0))
                        coords = (x, y, x + w, y + h)
                        element_id = int(elem_id)
                        print(f"[Step.from_dict #{step_id}] Resolved by element.id={elem_id}: {coords}")
                    except (KeyError, ValueError, TypeError):
                        print(f"[Step.from_dict #{step_id}] element.id={elem_id} NOT in dom_lookup (snapshot may be empty)")
                else:
                    # Fallback: match by element text (for steps without numeric id)
                    elem_text = (elem.get("text") or elem.get("aria_label") or "").strip().lower()
                    if elem_text and dom_text_lookup:
                        if elem_text in dom_text_lookup:
                            node = dom_text_lookup[elem_text]
                            b = node.get("bounds") or {}
                            x = int(b.get("x", 0))
                            y = int(b.get("y", 0))
                            w = int(b.get("width", 0))
                            h = int(b.get("height", 0))
                            coords = (x, y, x + w, y + h)
                            element_id = node.get("id")
                            if isinstance(element_id, int):
                                pass  # already set
                            else:
                                element_id = None
                            print(f"[Step.from_dict #{step_id}] Resolved by text={elem_text!r}: {coords}")
                        else:
                            print(f"[Step.from_dict #{step_id}] element text={elem_text!r} NOT in text lookup")
                    else:
                        print(f"[Step.from_dict #{step_id}] No element.id, no text to match, no text_lookup")

        return cls(
            id=int(step_id),
            target=str(target),
            tooltip=str(tooltip),
            action=d.get("action", "click"),
            spotlight_shape=d.get("spotlight_shape", "rect"),
            animation=d.get("animation", "pulse"),
            coords=coords,
            explanation=str(explanation),
            cache_hit=d.get("cache_hit", False),
            element_id=element_id,
        )

