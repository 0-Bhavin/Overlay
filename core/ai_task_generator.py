"""Gemini-powered task generator.

Converts a plain-text task description into a structured list of step dicts
that can be passed directly to :class:`~core.task.Task` or serialised to JSON.
"""
from __future__ import annotations

import json
import logging
import textwrap

try:
    import google.genai as genai  # type: ignore[import]
    from google.genai import types 
    _GENAI_AVAILABLE = True
except Exception:
    _GENAI_AVAILABLE = False

import requests
import os

_log = logging.getLogger(__name__)

_MAX_RETRIES: int = 2  # number of extra attempts after the first failure

_DEFAULT_OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
_DEFAULT_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen-fast:latest")

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_APP_SYSTEM_PROMPT = textwrap.dedent("""\
    You are a UI task decomposer. Given a user task and a target application
    name, you output ONLY a valid JSON object — no markdown fences, no
    explanations, no preamble, nothing but the raw JSON.

    The top-level JSON object must contain EXACTLY these keys:
      "app_exe" : string, the Windows process executable name used to launch
                  or identify the application (e.g. "EXCEL.EXE", "WINWORD.EXE",
                  "notepad.exe", "chrome.exe", "msedge.exe").
                  Use the real Windows .exe name, not the full path.
      "steps"   : array of step objects (see below)

    Each step object inside "steps" must contain EXACTLY these keys:
      "id"              : integer, starting at 1 and incrementing by 1
      "target"          : string, a short name that matches a real UI element
                          in the application (e.g. "Insert tab", "OK button")
      "tooltip"         : string, a friendly instruction for the user,
                          20 words or fewer
      "action"          : string, one of: "click", "type", "scroll", "hover"
      "spotlight_shape" : string, one of: "rect", "circle"
      "animation"       : string, one of: "pulse", "arrow", "none"
      "explanation"     : string, 1-2 sentences explaining WHY this step is
                          needed and what it achieves, ≤ 40 words

    Rules:
    - Never include a "coords" key in any step.
    - CRITICAL: target must be the RAW element name only. Strip all suffixes.
      WRONG: "File menu", "Save button", "File name text box", "OK button"
      RIGHT: "File", "Save", "File name", "OK"
    - Keep target names short and matching real UI element names in the app.
    - Keep tooltips concise and friendly (≤ 20 words).
    - Output ONLY the JSON object. Any extra text will break the parser.
""")

_WEBSITE_SYSTEM_PROMPT = textwrap.dedent("""\
    You are given:

    A task description that needs to be performed on a webpage.
    A JSON representation of the entire webpage, where each UI element and its attributes are available.

    Your objective is to decompose the task into the smallest possible executable steps, where each step corresponds to a single user interaction (one click or one atomic action).

    Instructions
    Break the task into a sequence of atomic steps.
    Each step should represent one interaction only (e.g., click a button, open a menu, select an option, focus an input field).
    For every step, identify the corresponding element in the provided webpage JSON.
    Extract and include all relevant attributes required to uniquely identify, filter, or navigate to that element.
    Preserve the correct execution order of the steps.
    If an element is nested, include its parent navigation path when necessary.
    Do not omit intermediate navigation steps.
    Return only valid JSON with no additional explanation.
    Output JSON format
    {
      "task": "<original task>",
      "steps": [
        {
          "step_number": 1,
          "action": "click",
          "description": "Click the Login button",
          "element": {
            "tag": "button",
            "text": "Login",
            "id": "login-btn",
            "class": "btn btn-primary",
            "name": null,
            "role": "button",
            "aria_label": "Login",
            "xpath": "...",
            "css_selector": "...",
            "parent_path": ["header", "nav"]
          }
        }
      ]
    }

    The goal is to generate a machine-readable JSON workflow where every step is directly mapped to the corresponding element in the webpage JSON and contains sufficient attributes for reliable element identification and navigation.
""")

_RETRY_SUFFIX = (
    "\n\nYour last response was not valid JSON. "
    "Return ONLY the JSON array, with no extra text."
)

# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class GeminiTaskGenerator:
    """Task generator supporting Ollama local models (e.g. qwen-fast:latest) and Gemini API.

    Parameters
    ----------
    api_key:
        Optional Google Generative AI API key for Gemini fallback.
    ollama_host:
        Ollama endpoint URL (defaults to http://localhost:11434 or OLLAMA_HOST env var).
    ollama_model:
        Ollama model name (defaults to qwen-fast:latest or OLLAMA_MODEL env var).
    """

    _GEMINI_MODEL = "gemini-2.5-flash"

    def __init__(
        self,
        api_key: str = "",
        ollama_host: str = _DEFAULT_OLLAMA_HOST,
        ollama_model: str = _DEFAULT_OLLAMA_MODEL,
    ) -> None:
        self._api_key = api_key
        self._ollama_host = ollama_host.rstrip("/")
        self._ollama_model = ollama_model
        self._client = None

        if api_key and _GENAI_AVAILABLE:
            try:
                self._client = genai.Client(api_key=api_key)
                self._app_config = types.GenerateContentConfig(
                    system_instruction=_APP_SYSTEM_PROMPT,
                )
                self._website_config = types.GenerateContentConfig(
                    system_instruction=_WEBSITE_SYSTEM_PROMPT,
                )
            except Exception as exc:
                _log.warning("Could not initialize Gemini client: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        task_description: str,
        app_name: str,
        target_mode: str = "app",
        dom_snapshot: list | None = None,
    ) -> dict:
        """Convert *task_description* into a task dict for *app_name*."""
        is_website = (target_mode == "website")
        system_prompt = _WEBSITE_SYSTEM_PROMPT if is_website else _APP_SYSTEM_PROMPT
        user_prompt = (
            self._build_website_user_prompt(task_description, app_name, dom_snapshot)
            if is_website
            else self._build_app_user_prompt(task_description, app_name)
        )

        # 1. Try Ollama first
        try:
            _log.info("Attempting task generation via Ollama (%s at %s)", self._ollama_model, self._ollama_host)
            result = self._generate_ollama(system_prompt, user_prompt, is_website=is_website, app_name=app_name)
            if result:
                _log.info("Ollama task generation succeeded with %d steps", len(result.get("steps", [])))
                return result
        except Exception as exc:
            _log.warning("Ollama generation failed: %s", exc)

        # 2. Fallback to Gemini if client is available
        if self._client is not None:
            _log.info("Falling back to Gemini API (%s)", self._GEMINI_MODEL)
            return self._generate_gemini(user_prompt, is_website=is_website)

        raise RuntimeError(
            f"Task generation failed. Ollama at {self._ollama_host} was unreachable or returned an error, "
            f"and no valid Gemini API key is configured."
        )

    # ------------------------------------------------------------------
    # Ollama Generation
    # ------------------------------------------------------------------

    def _generate_ollama(self, system_prompt: str, user_prompt: str, is_website: bool, app_name: str) -> dict:
        url = f"{self._ollama_host}/api/chat"
        payload = {
            "model": self._ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,
            },
        }

        resp = requests.post(url, json=payload, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        raw = data.get("message", {}).get("content", "")
        parsed = self._parse_json(raw)

        # Normalize outputs to ensure strict adherence to application schema
        if is_website:
            return self._normalize_website_result(parsed, app_name)
        else:
            return self._normalize_app_result(parsed, app_name)

    # ------------------------------------------------------------------
    # Gemini Generation
    # ------------------------------------------------------------------

    def _generate_gemini(self, user_prompt: str, is_website: bool) -> dict:
        config = self._website_config if is_website else self._app_config
        last_error = None

        for attempt in range(1 + _MAX_RETRIES):
            prompt = user_prompt if attempt == 0 else user_prompt + _RETRY_SUFFIX
            try:
                response = self._client.models.generate_content(
                    model=self._GEMINI_MODEL,
                    contents=prompt,
                    config=config,
                )
                raw = (response.text or "").strip()
                result = self._parse_json(raw)
                if is_website:
                    self._validate_website_result(result)
                else:
                    self._validate_app_result(result)
                return result
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                _log.warning("Gemini attempt %d failed: %s", attempt + 1, exc)
            except Exception as exc:
                raise RuntimeError(f"Gemini API request failed: {exc}") from exc

        raise ValueError(f"Gemini returned invalid JSON: {last_error}")

    # ------------------------------------------------------------------
    # Normalizers & Validators
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_app_result(result: dict, app_name: str) -> dict:
        """Ensure all required app-mode keys exist and have valid shapes."""
        steps_raw = result.get("steps") or result.get("workflow") or []
        if isinstance(result, list):
            steps_raw = result
            result = {}

        # Guess default exe if missing
        app_exe = result.get("app_exe") or ""
        if not app_exe:
            lower = app_name.lower()
            if "word" in lower:
                app_exe = "WINWORD.EXE"
            elif "excel" in lower:
                app_exe = "EXCEL.EXE"
            elif "powerpoint" in lower:
                app_exe = "POWERPNT.EXE"
            elif "chrome" in lower:
                app_exe = "chrome.exe"
            elif "edge" in lower:
                app_exe = "msedge.exe"
            elif "notepad" in lower:
                app_exe = "notepad.exe"
            else:
                app_exe = f"{app_name.split()[0].lower()}.exe"

        normalized_steps = []
        for i, s in enumerate(steps_raw):
            if not isinstance(s, dict):
                continue
            step_id = s.get("id") or s.get("step_number") or s.get("step_id") or (i + 1)
            target = s.get("target") or s.get("element") or s.get("description") or f"Step {step_id}"
            if isinstance(target, dict):
                target = target.get("text") or target.get("aria_label") or target.get("tag") or str(target)
            tooltip = s.get("tooltip") or s.get("description") or str(target)
            action = s.get("action") or "click"
            spotlight_shape = s.get("spotlight_shape") or "rect"
            animation = s.get("animation") or "pulse"
            explanation = s.get("explanation") or s.get("description") or ""

            normalized_steps.append({
                "id": int(step_id),
                "target": str(target),
                "tooltip": str(tooltip),
                "action": str(action),
                "spotlight_shape": str(spotlight_shape),
                "animation": str(animation),
                "explanation": str(explanation),
            })

        return {
            "app_exe": app_exe,
            "steps": normalized_steps,
        }

    @staticmethod
    def _normalize_website_result(result: dict, app_name: str) -> dict:
        """Ensure all required website-mode keys exist and have valid shapes."""
        steps_raw = result.get("steps") or []
        if isinstance(result, list):
            steps_raw = result
            result = {}

        normalized_steps = []
        for i, s in enumerate(steps_raw):
            if not isinstance(s, dict):
                continue
            step_number = s.get("step_number") or s.get("id") or s.get("step_id") or (i + 1)
            action = s.get("action") or "click"
            description = s.get("description") or s.get("tooltip") or f"Step {step_number}"
            elem = s.get("element")
            if not isinstance(elem, dict):
                elem = {
                    "tag": "button",
                    "text": s.get("target") or description,
                    "id": None,
                    "role": "button",
                }
            normalized_steps.append({
                "step_number": int(step_number),
                "action": str(action),
                "description": str(description),
                "element": elem,
            })

        return {
            "task": result.get("task") or result.get("name") or app_name,
            "steps": normalized_steps,
        }

    @staticmethod
    def _build_app_user_prompt(task_description: str, app_name: str) -> str:
        return (
            f"Application: {app_name}\n"
            f"Task: {task_description}\n\n"
            "Return the JSON step array now."
        )

    @staticmethod
    def _build_website_user_prompt(
        task_description: str,
        app_name: str,
        dom_snapshot: list | None = None,
    ) -> str:
        parts = [
            f"Target Webpage/URL: {app_name}",
            f"Task: {task_description}",
        ]
        if dom_snapshot:
            dom_json = json.dumps(dom_snapshot, ensure_ascii=False)
            parts.append(
                f"Webpage DOM (UINode JSON array — use this to map steps to exact elements):\n{dom_json}"
            )
        parts.append("Return the JSON workflow object now.")
        return "\n".join(parts)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """Strip accidental markdown fences and parse JSON."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.strip()
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return {"steps": parsed}
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Expected a JSON object at the top level, got {type(parsed).__name__!r}"
            )
        return parsed

    @staticmethod
    def _validate_app_result(result: dict) -> None:
        """Validate Gemini raw app result."""
        if "app_exe" not in result:
            raise ValueError("Response is missing required top-level key: 'app_exe'")
        if "steps" not in result or not isinstance(result["steps"], list):
            raise ValueError("Response is missing a 'steps' list")

    @staticmethod
    def _validate_website_result(result: dict) -> None:
        """Validate Gemini raw website result."""
        if "steps" not in result or not isinstance(result["steps"], list):
            raise ValueError("Response is missing a 'steps' list")