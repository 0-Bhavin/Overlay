"""Gemini API task generation for desktop and website workflows."""
from __future__ import annotations

import json
import logging
import time
import textwrap
from dataclasses import dataclass
from typing import Any

genai: Any = None
sdk_types: Any = None
try:
    from google import genai as genai_module  # type: ignore[import]
    from google.genai import types as genai_types
    genai = genai_module
    sdk_types = genai_types
except ImportError:  # Keep importing the application possible for non-generation tests.
    pass

from core.task_plan import TaskPlan

_log = logging.getLogger(__name__)
_API_RETRIES = 1
_RETRY_BACKOFF_SECONDS = 1.0

_APP_SYSTEM_PROMPT = textwrap.dedent("""\
    You are a UI task decomposer. Given a user task and target application,
    return only a JSON object with app_exe and steps. Each step has id, target,
    tooltip, action, spotlight_shape, animation, explanation. Targets are raw
    UI element names without suffixes. Never include coords.
""")

_WEBSITE_SYSTEM_PROMPT = textwrap.dedent("""\
    Decompose the user task into atomic browser interactions. Every step must
    identify an element in the supplied DOM and use exactly this shape:
    {"step_number": 1, "action": "click", "description": "...", "element":
    {"tag": "button", "text": "...", "id": null, "class": null,
    "name": null, "role": "button", "aria_label": null, "xpath": null,
    "css_selector": null, "parent_path": []}}.
    Do not invent elements absent from the DOM. Return only valid JSON.
""")

_PLAN_SYSTEM_PROMPT = textwrap.dedent("""\
    Create a persistent, goal-level milestone plan for the user's browser task.
    Produce 2 to 6 milestones unless the task can be completed on one page, in
    which case produce exactly one. Milestones describe outcomes, never clicks.
    Provide URL/text success hints only when plausible; leave arrays empty when
    unsure. Generate steps ONLY for milestone 0 on the supplied page. Step items
    must follow the existing website step format with step_number, action,
    description, and element containing tag, text, id, class, name, role,
    aria_label, xpath, css_selector, parent_path. Use only supplied DOM nodes.
    Return JSON with milestones and steps.
""")

_VERIFY_SYSTEM_PROMPT = textwrap.dedent("""\
    Continue a browser task from its persistent milestone plan. First decide
    whether the current milestone is met using the current URL and DOM. The
    heuristic hint is evidence only, not a verdict. If milestone_met is true,
    generate steps for the next active milestone; otherwise continue the current
    milestone. Never repeat completed actions or navigate backward. If no
    available element advances the goal, return empty steps and explain why.
    Return revised_remaining_milestones only when the remaining plan clearly
    cannot work from this page. goal_complete may be true with empty steps.
    Step items must use the existing website format: step_number, action,
    description, element with tag, text, id, class, name, role, aria_label, xpath,
    css_selector, parent_path. Use only the supplied DOM. Return JSON only.
""")


def _step_schema() -> dict[str, Any]:
    """JSON response schema for the established website step shape."""
    nullable_string = {"type": "STRING", "nullable": True}
    element = {
        "type": "OBJECT",
        "properties": {
            "tag": {"type": "STRING"},
            "text": nullable_string,
            "id": nullable_string,
            "class": nullable_string,
            "name": nullable_string,
            "role": nullable_string,
            "aria_label": nullable_string,
            "xpath": nullable_string,
            "css_selector": nullable_string,
            "parent_path": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["tag", "text", "id", "class", "name", "role", "aria_label", "xpath", "css_selector", "parent_path"],
    }
    return {
        "type": "OBJECT",
        "properties": {
            "step_number": {"type": "INTEGER"},
            "action": {"type": "STRING"},
            "description": {"type": "STRING"},
            "element": element,
        },
        "required": ["step_number", "action", "description", "element"],
    }


def _steps_array_schema() -> dict[str, Any]:
    return {"type": "ARRAY", "items": _step_schema()}


_PLAN_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "milestones": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "goal": {"type": "STRING"},
                    "success_hint": {
                        "type": "OBJECT",
                        "properties": {
                            "url_contains": {"type": "ARRAY", "items": {"type": "STRING"}},
                            "text_contains": {"type": "ARRAY", "items": {"type": "STRING"}},
                        },
                        "required": ["url_contains", "text_contains"],
                    },
                },
                "required": ["goal", "success_hint"],
            },
        },
        "steps": _steps_array_schema(),
    },
    "required": ["milestones", "steps"],
}

_VERIFY_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "milestone_met": {"type": "BOOLEAN"},
        "goal_complete": {"type": "BOOLEAN"},
        "reason": {"type": "STRING"},
        "revised_remaining_milestones": {
            "type": "ARRAY",
            "nullable": True,
            "items": _PLAN_RESPONSE_SCHEMA["properties"]["milestones"]["items"],
        },
        "steps": _steps_array_schema(),
    },
    "required": ["milestone_met", "goal_complete", "reason", "revised_remaining_milestones", "steps"],
}


@dataclass
class PlanResponse:
    milestones: list[dict[str, Any]]
    steps: list[dict[str, Any]]


@dataclass
class VerifyResponse:
    milestone_met: bool
    goal_complete: bool
    reason: str
    revised_remaining_milestones: list[dict[str, Any]] | None
    steps: list[dict[str, Any]]


class GeminiTaskGenerator:
    """Generate task workflows exclusively through the Gemini API."""

    _GEMINI_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._client: Any = None
        self._app_config: Any = None
        self._website_config: Any = None
        if not api_key:
            return
        if genai is None or sdk_types is None:
            raise RuntimeError("google-genai is not installed; install requirements.txt")
        self._client = genai.Client(api_key=api_key)
        self._app_config = sdk_types.GenerateContentConfig(
            system_instruction=_APP_SYSTEM_PROMPT,
            response_mime_type="application/json",
        )
        self._website_config = sdk_types.GenerateContentConfig(
            system_instruction=_WEBSITE_SYSTEM_PROMPT,
            response_mime_type="application/json",
        )

    def generate(
        self,
        task_description: str,
        app_name: str,
        target_mode: str = "app",
        dom_snapshot: list | None = None,
    ) -> dict:
        """Legacy one-call generator retained for UIA and app-mode workflows."""
        self._require_client()
        is_website = target_mode == "website"
        system_prompt = _WEBSITE_SYSTEM_PROMPT if is_website else _APP_SYSTEM_PROMPT
        user_prompt = (
            self._build_website_user_prompt(task_description, app_name, dom_snapshot)
            if is_website else self._build_app_user_prompt(task_description, app_name)
        )
        validator = self._validate_website_result if is_website else self._validate_app_result
        result = self._generate_json(user_prompt, system_prompt, None, validator)
        if is_website:
            return self._normalize_website_result(result, app_name)
        return self._normalize_app_result(result, app_name)

    def generate_plan_and_steps(self, query: str, url: str, dom: list) -> PlanResponse:
        """Generate milestone overview and first-milestone steps in one API call."""
        self._require_client()
        user_prompt = "\n".join((
            f"Original user goal: {query}",
            f"Current URL: {url}",
            "Current page DOM:",
            json.dumps(dom, ensure_ascii=False),
        ))
        parsed = self._generate_json(
            user_prompt, _PLAN_SYSTEM_PROMPT, _PLAN_RESPONSE_SCHEMA,
            lambda value: self._validate_plan_response(value),
        )
        milestones = parsed.get("milestones")
        if not isinstance(milestones, list) or not milestones:
            raise ValueError("Gemini plan response must contain at least one milestone")
        if len(milestones) > 6:
            milestones = milestones[:6]
        for milestone in milestones:
            if not isinstance(milestone, dict) or not str(milestone.get("goal", "")).strip():
                raise ValueError("Gemini returned a milestone without a goal")
        normalized = self._normalize_website_result({"steps": parsed.get("steps", [])}, query)
        return PlanResponse(milestones=milestones, steps=normalized["steps"])

    def verify_and_generate(
        self,
        plan: TaskPlan,
        last_completed_step: str,
        url: str,
        dom: list,
        heuristic_hint_matched: bool,
    ) -> VerifyResponse:
        """Verify the active milestone and generate its continuation in one call."""
        self._require_client()
        active = plan.current()
        user_payload = {
            "original_goal": plan.original_goal,
            "milestones": plan.milestones,
            "current_milestone": active,
            "last_completed_step": last_completed_step,
            "current_url": url,
            "heuristic_hint_matched": bool(heuristic_hint_matched),
            "current_page_dom": dom,
        }
        parsed = self._generate_json(
            json.dumps(user_payload, ensure_ascii=False),
            _VERIFY_SYSTEM_PROMPT,
            _VERIFY_RESPONSE_SCHEMA,
            self._validate_verify_response,
        )
        if not isinstance(parsed.get("milestone_met"), bool):
            raise ValueError("Gemini verify response is missing boolean milestone_met")
        if not isinstance(parsed.get("goal_complete"), bool):
            raise ValueError("Gemini verify response is missing boolean goal_complete")
        normalized = self._normalize_website_result({"steps": parsed.get("steps", [])}, plan.original_goal)
        revised = parsed.get("revised_remaining_milestones")
        if revised is not None:
            if not isinstance(revised, list) or any(not isinstance(m, dict) or not m.get("goal") for m in revised):
                raise ValueError("Gemini returned invalid revised_remaining_milestones")
        return VerifyResponse(
            milestone_met=parsed["milestone_met"],
            goal_complete=parsed["goal_complete"],
            reason=str(parsed.get("reason", "")),
            revised_remaining_milestones=revised,
            steps=normalized["steps"],
        )

    def _require_client(self) -> None:
        if self._client is None:
            raise RuntimeError("GEMINI_API_KEY is required for task generation")

    def _generate_json(
        self,
        prompt: str,
        system_prompt: str,
        response_schema: dict | None,
        validator,
    ) -> dict:
        last_error: Exception | None = None
        for attempt in range(_API_RETRIES + 1):
            try:
                raw = self._generate_content_once(prompt, system_prompt, response_schema)
                result = self._parse_json(raw)
                validator(result)
                return result
            except Exception as exc:
                last_error = exc
                if attempt >= _API_RETRIES:
                    break
                _log.warning("Gemini generation/validation failed (attempt %d/%d): %s", attempt + 1, _API_RETRIES + 1, exc)
                time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
        raise RuntimeError(f"Gemini generation failed after retry: {last_error}") from last_error

    def _generate_content_once(self, prompt: str, system_prompt: str, response_schema: dict | None) -> str:
        config_kwargs: dict[str, Any] = {
            "system_instruction": system_prompt,
            "response_mime_type": "application/json",
        }
        if response_schema is not None:
            config_kwargs["response_schema"] = response_schema
        if sdk_types is None:
            raise RuntimeError("google-genai is not installed; install requirements.txt")
        config = sdk_types.GenerateContentConfig(**config_kwargs)
        response = self._client.models.generate_content(
            model=self._GEMINI_MODEL,
            contents=prompt,
            config=config,
        )
        text = (response.text or "").strip()
        if not text:
            raise ValueError("Gemini returned an empty response")
        return text

    # ------------------------------------------------------------------
    # Existing step normalization and prompt helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_app_result(result: dict, app_name: str) -> dict:
        steps_raw = result.get("steps") or result.get("workflow") or []
        if isinstance(result, list):
            steps_raw, result = result, {}
        app_exe = result.get("app_exe") or ""
        if not app_exe:
            lower = app_name.lower()
            app_exe = next((exe for needle, exe in (
                ("word", "WINWORD.EXE"), ("excel", "EXCEL.EXE"),
                ("powerpoint", "POWERPNT.EXE"), ("chrome", "chrome.exe"),
                ("edge", "msedge.exe"), ("notepad", "notepad.exe"),
            ) if needle in lower), f"{app_name.split()[0].lower()}.exe" if app_name.split() else "")
        steps = []
        for index, step in enumerate(steps_raw):
            if not isinstance(step, dict):
                continue
            step_id = step.get("id") or step.get("step_number") or step.get("step_id") or index + 1
            target = step.get("target") or step.get("element") or step.get("description") or f"Step {step_id}"
            if isinstance(target, dict):
                target = target.get("text") or target.get("aria_label") or target.get("tag") or str(target)
            steps.append({
                "id": int(step_id), "target": str(target),
                "tooltip": str(step.get("tooltip") or step.get("description") or target),
                "action": str(step.get("action") or "click"),
                "spotlight_shape": str(step.get("spotlight_shape") or "rect"),
                "animation": str(step.get("animation") or "pulse"),
                "explanation": str(step.get("explanation") or step.get("description") or ""),
            })
        return {"app_exe": app_exe, "steps": steps}

    @staticmethod
    def _normalize_website_result(result: dict, app_name: str) -> dict:
        steps_raw = result.get("steps") or []
        if isinstance(result, list):
            steps_raw, result = result, {}
        steps = []
        for index, step in enumerate(steps_raw):
            if not isinstance(step, dict):
                continue
            number = step.get("step_number") or step.get("id") or step.get("step_id") or index + 1
            action = step.get("action") or "click"
            description = step.get("description") or step.get("tooltip") or f"Step {number}"
            element = step.get("element")
            if not isinstance(element, dict):
                element = {"tag": "button", "text": step.get("target") or description, "id": None, "role": "button"}
            steps.append({
                "step_number": int(number),
                "action": str(action),
                "description": str(description),
                "element": element,
            })
        return {"task": result.get("task") or result.get("name") or app_name, "steps": steps}

    @staticmethod
    def _build_app_user_prompt(task_description: str, app_name: str) -> str:
        return f"Application: {app_name}\nTask: {task_description}\n\nReturn the JSON workflow now."

    @staticmethod
    def _build_website_user_prompt(task_description: str, app_name: str, dom_snapshot: list | None = None) -> str:
        parts = [f"Target Webpage/URL: {app_name}", f"Task: {task_description}"]
        if dom_snapshot:
            parts.append("Webpage DOM (use this to map steps to exact elements):\n" + json.dumps(dom_snapshot, ensure_ascii=False))
        parts.append("Return the JSON workflow object now.")
        return "\n".join(parts)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        parsed = json.loads(text.strip())
        if isinstance(parsed, list):
            return {"steps": parsed}
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected a JSON object, got {type(parsed).__name__}")
        return parsed

    @staticmethod
    def _validate_plan_response(result: dict) -> None:
        if not isinstance(result.get("milestones"), list) or not result["milestones"]:
            raise ValueError("Plan response must contain a non-empty milestones list")
        if not isinstance(result.get("steps"), list):
            raise ValueError("Plan response must contain a steps list")
        for milestone in result["milestones"]:
            if not isinstance(milestone, dict) or not str(milestone.get("goal", "")).strip():
                raise ValueError("Every milestone must have a goal")

    @staticmethod
    def _validate_verify_response(result: dict) -> None:
        if not isinstance(result.get("milestone_met"), bool):
            raise ValueError("Verify response must contain boolean milestone_met")
        if not isinstance(result.get("goal_complete"), bool):
            raise ValueError("Verify response must contain boolean goal_complete")
        if not isinstance(result.get("steps"), list):
            raise ValueError("Verify response must contain a steps list")
        revised = result.get("revised_remaining_milestones")
        if revised is not None and not isinstance(revised, list):
            raise ValueError("revised_remaining_milestones must be a list or null")

    @staticmethod
    def _validate_app_result(result: dict) -> None:
        if "app_exe" not in result:
            raise ValueError("Response is missing required top-level key: 'app_exe'")
        if not isinstance(result.get("steps"), list):
            raise ValueError("Response is missing a 'steps' list")

    @staticmethod
    def _validate_website_result(result: dict) -> None:
        if not isinstance(result.get("steps"), list):
            raise ValueError("Response is missing a 'steps' list")
