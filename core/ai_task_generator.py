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
    # pyrefly: ignore [missing-import]
    from google.genai import types 
except ModuleNotFoundError as _err:
    raise ModuleNotFoundError(
        "google-genai is not installed. Run: pip install google-genai"
    ) from _err

_log = logging.getLogger(__name__)

_MAX_RETRIES: int = 2  # number of extra attempts after the first failure

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
    """Calls the Gemini API to generate a structured step list from free text.

    Parameters
    ----------
    api_key:
        A valid Google Generative AI API key.
    """

    _MODEL = "gemini-2.5-flash"

    def __init__(self, api_key: str) -> None:
        genai.configure(api_key=api_key)
        self._app_model = genai.GenerativeModel(
            model_name=self._MODEL,
            system_instruction=_APP_SYSTEM_PROMPT,
        )
        self._website_model = genai.GenerativeModel(
            model_name=self._MODEL,
            system_instruction=_WEBSITE_SYSTEM_PROMPT,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, task_description: str, app_name: str, target_mode: str = "app") -> dict:
        """Convert *task_description* into a task dict for *app_name*.

        Parameters
        ----------
        task_description:
            Plain-English description of what the user wants to accomplish,
            e.g. ``"Insert an image from file into the document"``.
        app_name:
            The name of the target application or website URL, e.g. ``"Microsoft Word"``
            or ``"https://google.com"``.
        target_mode:
            ``"app"`` for window desktop applications, or ``"website"`` for web applications.

        Returns
        -------
        dict
            A dict containing generated task steps.

        Raises
        ------
        ValueError
            If the Gemini response cannot be parsed as valid JSON after all
            retries are exhausted.
        """
        is_website = (target_mode == "website")
        model = self._website_model if is_website else self._app_model
        user_prompt = (
            self._build_website_user_prompt(task_description, app_name)
            if is_website
            else self._build_app_user_prompt(task_description, app_name)
        )
        last_error: Exception | None = None

        for attempt in range(1 + _MAX_RETRIES):
            prompt = user_prompt if attempt == 0 else user_prompt + _RETRY_SUFFIX
            _log.debug("Gemini request attempt %d/%d (mode=%s)", attempt + 1, 1 + _MAX_RETRIES, target_mode)

            try:
                response = model.generate_content(prompt)
                raw = (response.text or "").strip()
                _log.debug("Gemini raw response: %s", raw[:200])
                result = self._parse_json(raw)
                if is_website:
                    self._validate_website_result(result)
                else:
                    self._validate_app_result(result)
                return result

            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                _log.warning(
                    "Attempt %d failed — %s: %s",
                    attempt + 1,
                    type(exc).__name__,
                    exc,
                )
            except Exception as exc:  # noqa: BLE001  — network/API errors
                raise RuntimeError(
                    f"Gemini API request failed on attempt {attempt + 1}: {exc}"
                ) from exc

        raise ValueError(
            f"Gemini returned invalid JSON after {1 + _MAX_RETRIES} attempts. "
            f"Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_app_user_prompt(task_description: str, app_name: str) -> str:
        return (
            f"Application: {app_name}\n"
            f"Task: {task_description}\n\n"
            "Return the JSON step array now."
        )

    @staticmethod
    def _build_website_user_prompt(task_description: str, app_name: str) -> str:
        return (
            f"Target Webpage/URL: {app_name}\n"
            f"Task: {task_description}\n\n"
            "Return the JSON workflow object now."
        )

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """Strip accidental markdown fences and parse JSON.

        Raises ``json.JSONDecodeError`` on failure so the retry loop can catch it.
        """
        # Defensively strip ```json ... ``` fences in case the model slips up
        text = raw
        if text.startswith("```"):
            lines = text.splitlines()
            # drop first and last fence line
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.strip()
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Expected a JSON object at the top level, got {type(parsed).__name__!r}"
            )
        return parsed  # type: ignore[return-value]

    @staticmethod
    def _validate_app_result(result: dict) -> None:
        """Raise ``ValueError`` if the top-level result or any step is missing required keys for app mode."""
        if "app_exe" not in result:
            raise ValueError("Response is missing required top-level key: 'app_exe'")
        if "steps" not in result or not isinstance(result["steps"], list):
            raise ValueError("Response is missing a 'steps' list")
        required = {"id", "target", "tooltip", "action", "spotlight_shape", "animation", "explanation"}
        for i, step in enumerate(result["steps"]):
            if not isinstance(step, dict):
                raise ValueError(f"Step {i} is not a dict: {step!r}")
            missing = required - step.keys()
            if missing:
                raise ValueError(
                    f"Step {i} is missing required keys: {missing}"
                )

    @staticmethod
    def _validate_website_result(result: dict) -> None:
        """Raise ``ValueError`` if the top-level result or any step is missing required keys for website mode."""
        if "steps" not in result or not isinstance(result["steps"], list):
            raise ValueError("Response is missing a 'steps' list")
        for i, step in enumerate(result["steps"]):
            if not isinstance(step, dict):
                raise ValueError(f"Step {i} is not a dict: {step!r}")
            if "step_number" not in step and "id" not in step:
                raise ValueError(f"Step {i} is missing 'step_number' or 'id'")