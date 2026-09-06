from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from core.step import Step


@dataclass
class Task:
    """Represents a named guided task composed of ordered :class:`~core.step.Step` objects."""

    name: str
    app: str
    app_exe: str = ""          # Windows process exe name from Gemini (e.g. "EXCEL.EXE")
    mode: str = "app"          # "app" | "website" — which resolver pipeline to use
    steps: list[Step] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def load_from_file(cls, path: str) -> "Task":
        """Load a :class:`Task` from a JSON file on disk.

        Expected JSON shape::

            {
                "name": "Insert an image",
                "app":  "Microsoft Word",
                "mode": "app",
                "steps": [
                    {"id": 1, "target": "Insert tab", "tooltip": "Click the Insert tab.", ...},
                    ...
                ]
            }

        For website-mode tasks, a ``dom_snapshot.json`` next to the task file is
        loaded and used to resolve element coordinates from UINode bounds.

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
        """
        with open(path, encoding="utf-8") as fh:
            data: dict = json.load(fh)

        # Load DOM snapshot for website-mode coord resolution
        dom_lookup: dict[int, dict] = {}
        dom_path = os.path.join(os.path.dirname(os.path.abspath(path)), "dom_snapshot.json")
        if os.path.exists(dom_path):
            with open(dom_path, encoding="utf-8") as fh:
                for node in json.load(fh):
                    dom_lookup[node["id"]] = node

        steps = [
            Step.from_dict(s, default_id=i + 1, dom_lookup=dom_lookup or None)
            for i, s in enumerate(data.get("steps", []))
        ]
        return cls(
            name=data.get("name") or data.get("task") or "Untitled Task",
            app=data.get("app", ""),
            app_exe=data.get("app_exe", ""),
            mode=data.get("mode", "app"),
            steps=steps,
        )
