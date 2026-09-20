"""Unit tests for Task and Step loading and deserialization."""

import unittest
from core.step import Step
from core.task import Task


class TestTaskAndStep(unittest.TestCase):

    def test_step_from_dict_standard(self):
        d = {
            "id": 1,
            "target": "Insert tab",
            "tooltip": "Click Insert tab",
            "action": "click",
            "spotlight_shape": "rect",
            "animation": "pulse",
        }
        step = Step.from_dict(d)
        self.assertEqual(step.id, 1)
        self.assertEqual(step.target, "Insert tab")
        self.assertEqual(step.tooltip, "Click Insert tab")
        self.assertEqual(step.action, "click")

    def test_step_from_dict_website_format(self):
        d = {
            "step_number": 2,
            "action": "type",
            "description": "Type 'instagram story' into search",
            "element": {
                "tag": "input",
                "id": "search-input",
                "placeholder": "Search your content",
            },
        }
        step = Step.from_dict(d)
        self.assertEqual(step.id, 2)
        self.assertEqual(step.target, "Search your content")
        self.assertEqual(step.tooltip, "Type 'instagram story' into search")
        self.assertEqual(step.action, "type")

    def test_task_load_from_dict(self):
        # Testing fallback mapping for 'task' key and steps without 'id'
        path_task_data = {
            "task": "Test Task Name",
            "app": "Chrome",
            "steps": [
                {
                    "step_number": 1,
                    "description": "Step 1 description",
                    "element": {"tag": "button", "text": "Submit"},
                }
            ],
        }
        # Step conversion
        steps = [Step.from_dict(s, default_id=i + 1) for i, s in enumerate(path_task_data["steps"])]
        task = Task(
            name=path_task_data.get("name") or path_task_data.get("task") or "Untitled",
            app=path_task_data.get("app", ""),
            steps=steps,
        )
        self.assertEqual(task.name, "Test Task Name")
        self.assertEqual(len(task.steps), 1)
        self.assertEqual(task.steps[0].id, 1)
        self.assertEqual(task.steps[0].target, "Submit")


if __name__ == "__main__":
    unittest.main()
