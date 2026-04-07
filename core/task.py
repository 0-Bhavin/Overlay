from __future__ import annotations

import json
from dataclasses import dataclass, field

from core.step import Step


@dataclass
class Task:
    """Represents a named guided task composed of ordered :class:`~core.step.Step` objects."""

    name: str
    app: str
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
                "steps": [
                    {"id": 1, "target": "Insert tab", "tooltip": "Click the Insert tab.", ...},
                    ...
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
        return cls(
            name=data["name"],
            app=data["app"],
            steps=steps,
        )
