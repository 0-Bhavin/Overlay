"""Recent-task history persistence (feature 1.7).

Stores the last :data:`_MAX_ENTRIES` task-description / app-name pairs in
``tasks/history.json`` so the UI can offer a "recent tasks" dropdown.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import List

_log = logging.getLogger(__name__)

_HISTORY_FILE = os.path.join(
    os.path.dirname(__file__), "..", "tasks", "history.json"
)
_MAX_ENTRIES = 20


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def load_history() -> List[dict]:
    """Return list of recent task dicts (newest first).

    Each dict has keys: ``"task"``, ``"app"``, ``"timestamp"`` (ISO-8601).
    Returns an empty list when the file does not exist or is corrupt.
    """
    try:
        with open(_HISTORY_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def save_to_history(task: str, app: str) -> None:
    """Prepend *task* / *app* to the history file, capping at :data:`_MAX_ENTRIES`.

    Duplicate (task, app) pairs are deduplicated before inserting so that
    re-running the same task simply moves it to the top.
    """
    history = load_history()
    # Remove existing duplicates
    history = [
        h for h in history
        if not (h.get("task") == task and h.get("app") == app)
    ]
    history.insert(0, {
        "task":      task,
        "app":       app,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    })
    history = history[:_MAX_ENTRIES]
    try:
        os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
        with open(_HISTORY_FILE, "w", encoding="utf-8") as fh:
            json.dump(history, fh, indent=2, ensure_ascii=False)
    except OSError as exc:
        _log.warning("Could not save task history: %s", exc)
