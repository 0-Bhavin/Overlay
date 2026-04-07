"""Gemini-powered task generator.

Converts a plain-text task description into a structured list of step dicts
that can be passed directly to :class:`~core.task.Task` or serialised to JSON.
"""
from __future__ import annotations

import json
import logging
import textwrap

try:
    import google.generativeai as genai  # type: ignore[import]
except ModuleNotFoundError as _err:
    raise ModuleNotFoundError(
        "google-generativeai is not installed. Run: pip install google-generativeai"
    ) from _err

_log = logging.getLogger(__name__)

_MAX_RETRIES: int = 2  # number of extra attempts after the first failure

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = textwrap.dedent("""\
    You are a UI task decomposer. Given a user task and a target application
    name, you output ONLY a valid JSON array of step objects — no markdown
    fences, no explanations, no preamble, nothing but the raw JSON.

    Each step object must contain EXACTLY these keys:
      "id"              : integer, starting at 1 and incrementing by 1
      "target"          : string, a short name that matches a real UI element
                          in the application (e.g. "Insert tab", "OK button")
      "tooltip"         : string, a friendly instruction for the user,
                          20 words or fewer
      "action"          : string, one of: "click", "type", "scroll", "hover"
      "spotlight_shape" : string, one of: "rect", "circle"
      "animation"       : string, one of: "pulse", "arrow", "none"

    Rules:
    - Never include a "coords" key.
    - CRITICAL: target must be the RAW element name only. Strip all suffixes.
      WRONG: "File menu", "Save button", "File name text box", "OK button"
      RIGHT: "File", "Save", "File name", "OK"
    - Keep target names short and matching real UI element names in the app.
    - Keep tooltips concise and friendly (≤ 20 words).
    - Output ONLY the JSON array. Any extra text will break the parser.
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
        self._model = genai.GenerativeModel(
            model_name=self._MODEL,
            system_instruction=_SYSTEM_PROMPT,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, task_description: str, app_name: str) -> list[dict]:
        """Convert *task_description* into a list of step dicts for *app_name*.

        Parameters
        ----------
        task_description:
            Plain-English description of what the user wants to accomplish,
            e.g. ``"Insert an image from file into the document"``.
        app_name:
            The name of the target application, e.g. ``"Microsoft Word"``.

        Returns
        -------
        list[dict]
            A list of raw step dicts, each containing the keys specified in
            the system prompt.  Pass each dict to :meth:`~core.step.Step.from_dict`
            to create :class:`~core.step.Step` objects.

        Raises
        ------
        ValueError
            If the Gemini response cannot be parsed as valid JSON after all
            retries are exhausted.
            
        "IMPORTANT: In the 'target' field, use SHORT exact UI element names "
        "as they appear in the app — e.g. 'File' not 'File menu', "
        "'Save' not 'Save button', 'File name' not 'File name text box'. "
        "Target names must match what Windows UIAutomation exposes."
        """
        user_prompt = self._build_user_prompt(task_description, app_name)
        last_error: Exception | None = None

        for attempt in range(1 + _MAX_RETRIES):
            prompt = user_prompt if attempt == 0 else user_prompt + _RETRY_SUFFIX
            _log.debug("Gemini request attempt %d/%d", attempt + 1, 1 + _MAX_RETRIES)

            try:
                response = self._model.generate_content(prompt)
                raw = (response.text or "").strip()
                _log.debug("Gemini raw response: %s", raw[:200])
                steps = self._parse_json(raw)
                self._validate_steps(steps)
                return steps

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
    def _build_user_prompt(task_description: str, app_name: str) -> str:
        return (
            f"Application: {app_name}\n"
            f"Task: {task_description}\n\n"
            "Return the JSON step array now."
        )

    @staticmethod
    def _parse_json(raw: str) -> list[dict]:
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
        if not isinstance(parsed, list):
            raise ValueError(
                f"Expected a JSON array at the top level, got {type(parsed).__name__!r}"
            )
        return parsed  # type: ignore[return-value]

    @staticmethod
    def _validate_steps(steps: list[dict]) -> None:
        """Raise ``ValueError`` if any step is missing required keys."""
        required = {"id", "target", "tooltip", "action", "spotlight_shape", "animation"}
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"Step {i} is not a dict: {step!r}")
            missing = required - step.keys()
            if missing:
                raise ValueError(
                    f"Step {i} is missing required keys: {missing}"
                )


