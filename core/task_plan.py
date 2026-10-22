"""Persistent milestone state for website task orchestration."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, cast

MAX_ATTEMPTS_PER_MILESTONE = 3
MAX_REPLANS = 2
DOM_TEXT_MAX_CHARS = 30_000


@dataclass
class PlanUpdate:
    goal_complete: bool
    milestone_advanced: bool
    replan_applied: bool


def apply_verification(plan: TaskPlan, response: Any) -> PlanUpdate:
    """Apply one combined verify/generate response to orchestrator-owned state."""
    revised = getattr(response, "revised_remaining_milestones", None)
    replan_applied = isinstance(revised, list) and plan.replans < MAX_REPLANS
    if replan_applied:
        plan.replace_remaining(cast(list[dict[str, Any] | str], revised))
    milestone_advanced = bool(getattr(response, "milestone_met", False))
    if milestone_advanced:
        plan.advance()
    return PlanUpdate(
        goal_complete=bool(getattr(response, "goal_complete", False)),
        milestone_advanced=milestone_advanced,
        replan_applied=replan_applied,
    )


@dataclass
class TaskPlan:
    original_goal: str
    milestones: list[dict[str, Any]]
    current_index: int = 0
    replans: int = 0

    def __post_init__(self) -> None:
        normalized = []
        for index, milestone in enumerate(self.milestones):
            normalized.append({
                "id": index,
                "goal": str(milestone.get("goal", "")).strip(),
                "success_hint": {
                    "url_contains": list((milestone.get("success_hint") or {}).get("url_contains", [])),
                    "text_contains": list((milestone.get("success_hint") or {}).get("text_contains", [])),
                },
                "status": milestone.get("status", "pending"),
                "attempts": int(milestone.get("attempts", 0)),
            })
        self.milestones = normalized
        if (
            self.milestones
            and 0 <= self.current_index < len(self.milestones)
            and self.milestones[self.current_index]["status"] != "done"
        ):
            self.milestones[self.current_index]["status"] = "active"

    @classmethod
    def single_milestone(cls, goal: str) -> TaskPlan:
        """Build the implicit plan used when no model overview is available."""
        return cls(goal, [{"goal": goal, "success_hint": {"url_contains": [], "text_contains": []}}])

    def current(self) -> dict[str, Any] | None:
        if 0 <= self.current_index < len(self.milestones):
            return self.milestones[self.current_index]
        return None

    def is_last(self) -> bool:
        return bool(self.milestones) and self.current_index == len(self.milestones) - 1

    def advance(self) -> None:
        current = self.current()
        if current is None:
            return
        current["status"] = "done"
        current["attempts"] = 0
        self.current_index += 1
        next_milestone = self.current()
        if next_milestone is not None:
            next_milestone["status"] = "active"
            next_milestone["attempts"] = 0

    def mark_attempt(self) -> int:
        current = self.current()
        if current is None:
            return 0
        current["attempts"] += 1
        return current["attempts"]

    def replace_remaining(self, new_milestones: list[dict[str, Any] | str]) -> None:
        """Keep completed milestones and replace the current and future plan."""
        completed = [m for m in self.milestones[:self.current_index] if m["status"] == "done"]
        replacements = []
        for milestone in new_milestones:
            if isinstance(milestone, str):
                milestone = {"goal": milestone}
            replacements.append({
                "goal": milestone.get("goal", ""),
                "success_hint": milestone.get("success_hint") or {},
                "status": "pending",
                "attempts": 0,
            })
        self.milestones = completed + replacements
        self.current_index = len(completed)
        self.replans += 1
        current = self.current()
        if current is not None:
            current["status"] = "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_goal": self.original_goal,
            "milestones": self.milestones,
            "current_index": self.current_index,
            "replans": self.replans,
        }

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as output:
            json.dump(self.to_dict(), output, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str) -> TaskPlan:
        with open(path, encoding="utf-8") as source:
            data = json.load(source)
        return cls(
            original_goal=data["original_goal"],
            milestones=data["milestones"],
            current_index=int(data.get("current_index", 0)),
            replans=int(data.get("replans", 0)),
        )


def dom_text(dom: list[dict[str, Any]]) -> str:
    """Build bounded text evidence from a simplified DOM tree."""
    return " ".join(str(node.get("text", "")) for node in dom if node.get("text"))[:DOM_TEXT_MAX_CHARS]


def tier1_match(success_hint: dict[str, Any] | None, url: str, page_text: str) -> bool:
    """Match any URL or visible-text hint; empty hints never match."""
    if not success_hint:
        return False
    url_lower = (url or "").casefold()
    text_lower = (page_text or "")[:DOM_TEXT_MAX_CHARS].casefold()
    urls = success_hint.get("url_contains") or []
    texts = success_hint.get("text_contains") or []
    return any(str(hint).casefold() in url_lower for hint in urls if str(hint)) or any(
        str(hint).casefold() in text_lower for hint in texts if str(hint)
    )
