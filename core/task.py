from __future__ import annotations

import json
from dataclasses import dataclass, field

from core.step import Step


@dataclass
class Task:
    """Represents a named guided task composed of ordered :class:`~core.step.Step` objects.

    Supports both **desktop** tasks (Windows UIA) and **web** tasks (browser DOM),
    as well as **mixed** tasks that span both within a single step sequence.
    """

    name: str
    app: str
    app_exe: str = ""          # Windows process exe name from Gemini (e.g. "EXCEL.EXE")
    steps: list[Step] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Web task fields (ignored / default for desktop tasks)
    # ------------------------------------------------------------------

    target_type: str = "desktop"
    """Task-level hint: ``"desktop"`` or ``"web"``.

    Individual :attr:`~core.step.Step.target_type` values take precedence
    when routing each step, so a single task can mix both types.
    """

    url: str = ""
    """Target webpage URL for web tasks (e.g. ``"https://mail.google.com"``).

    Empty for desktop tasks.  Used by :class:`~platforms.web_resolver.WebResolver`
    to disambiguate browser tabs when multiple are open.
    """

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def load_from_file(cls, path: str) -> "Task":
        """Load a :class:`Task` from a JSON file on disk.

        Handles **two top-level schemas**:

        Desktop schema (existing)::

            {
                "name": "Insert an image",
                "app":  "Microsoft Word",
                "steps": [
                    {"id": 1, "target": "Insert tab", "tooltip": "Click the Insert tab.", ...},
                    ...
                ]
            }

        Normalized website schema (produced by
        :meth:`~core.ai_task_generator.GeminiTaskGenerator._normalize_website_result`)::

            {
                "name": "Sign in to Supabase",
                "app":  "supabase.com",
                "target_type": "web",
                "url": "https://supabase.com",
                "steps": [
                    {
                        "id": 1,
                        "target_type": "web",
                        "target": "Sign in",
                        "tooltip": "Click the Sign in link.",
                        "web_element": {"tag": "a", "text": "Sign in", "id": 29, ...}
                    }
                ]
            }

        Parameters
        ----------
        path:
            Absolute or relative path to the JSON task file.

        Returns
        -------
        Task
            A fully populated :class:`Task` instance.

        Raises
        ------
        FileNotFoundError
            If *path* does not exist.
        KeyError
            If required JSON keys (``name``, ``app``, ``steps``) are absent.
        """
        with open(path, encoding="utf-8") as fh:
            data: dict = json.load(fh)

        steps = [Step.from_dict(s) for s in data["steps"]]
        target_type = data.get("target_type")
        if not target_type:
            target_type = "web" if any(getattr(s, "target_type", "desktop") == "web" for s in steps) else "desktop"

        return cls(
            name=data.get("name") or data.get("task", "Untitled Task"),
            app=data["app"],
            app_exe=data.get("app_exe", ""),
            steps=steps,
            target_type=target_type,
            url=data.get("url", ""),
        )
