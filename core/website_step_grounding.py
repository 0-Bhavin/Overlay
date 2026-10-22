"""Ground website generator steps to the exact interactive nodes in a DOM snapshot."""
from __future__ import annotations

import logging
import re

_log = logging.getLogger(__name__)


def _interactive(node: dict) -> bool:
    node_type = str(node.get("type") or "").casefold()
    return node_type in ("button", "link", "select", "option", "textarea") or node_type.startswith("input:") or str(node.get("role") or "").casefold() in ("switch", "menuitem", "option")


def filter_steps_to_dom(steps: list[dict], dom: list[dict]) -> list[dict]:
    """Resolve generated IDs/text against this snapshot; stop at unopened menus."""
    nodes_by_id = {str(node.get("id")): node for node in dom if node.get("id") is not None}
    filtered = []
    for step in steps:
        element = step.get("element") if isinstance(step, dict) else None
        if not isinstance(element, dict):
            _log.warning("Dropping generated step without element mapping: %r", step)
            continue
        raw_text = element.get("text") or element.get("aria_label") or element.get("name") or ""
        needle = " ".join(str(raw_text).casefold().split())
        tag = str(element.get("tag") or "").casefold()
        expected_type = "link" if tag in ("a", "link") else tag

        def type_matches(node: dict, expected_type: str = expected_type) -> bool:
            node_type = str(node.get("type") or "").casefold()
            return not expected_type or node_type == expected_type or (
                expected_type == "input" and node_type.startswith("input:")
            )

        def text_matches(node: dict, needle: str = needle) -> bool:
            text = " ".join(str(node.get("text") or "").casefold().split())
            return not needle or text == needle or (len(needle) >= 3 and needle in text)

        matched = nodes_by_id.get(str(element.get("id")))
        if matched is not None and not (type_matches(matched) and text_matches(matched)):
            matched = None
        if matched is None and needle:
            candidates = [node for node in dom if type_matches(node) and text_matches(node)]
            candidates.sort(key=lambda node: (
                " ".join(str(node.get("text") or "").casefold().split()) != needle,
                not _interactive(node),
                len(str(node.get("text") or "")),
            ))
            matched = candidates[0] if candidates else None
        if matched is None:
            _log.warning("Dropping generated step not grounded in current DOM: %r", raw_text or step.get("description"))
            continue

        # When a model references a label or wrapper instead of its control,
        # prefer a control with the exact same accessible name.
        if not _interactive(matched) and str(step.get("action") or "click").casefold() == "click":
            matching_controls = [node for node in dom if _interactive(node) and
                                 str(node.get("text") or "").casefold().removesuffix(" (opens menu)") == str(matched.get("text") or "").casefold()]
            if matching_controls:
                matched = matching_controls[0]

        grounded = {**step, "element": {
            **element, "id": str(matched["id"]), "text": matched.get("text") or element.get("text"),
        }}
        filtered.append(grounded)
        description = str(step.get("description") or "")
        current_label = str(matched.get("text") or "").casefold()
        instruction = description.casefold()
        # Some custom selectors omit ARIA disclosure attributes. A click on a
        # control displaying the opposite state is not proof of selection.
        changes_state = str(matched.get("type") or "").casefold() == "button" and (
            ("public" in current_label and "private" in instruction)
            or ("private" in current_label and "public" in instruction)
            or (current_label == "off" and "enable" in instruction)
            or (current_label.startswith("no ") and re.search(r"\b(select|choose|add)\b", instruction))
        )
        if ("(opens menu)" in current_label or changes_state or
                re.search(r"\b(open|expand|show)\b.{0,100}\b(dropdown|menu|picker|dialog|options)\b", description, re.IGNORECASE)):
            # The options do not exist in this DOM yet. Fetch it after this click.
            break
    return filtered
