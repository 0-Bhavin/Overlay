import unittest
from unittest.mock import Mock, patch

from core.ai_task_generator import GeminiTaskGenerator, VerifyResponse
from core.step import Step
from core.task_plan import TaskPlan


class TestGeminiGeneratorContracts(unittest.TestCase):
    def setUp(self):
        self.generator = GeminiTaskGenerator()
        # Test contract/normalization paths without contacting Gemini.
        self.generator._client = Mock()

    @staticmethod
    def website_step():
        return {
            "step_number": 1,
            "action": "click",
            "description": "Click Continue",
            "element": {
                "tag": "button",
                "text": "Continue",
                "id": None,
                "class": None,
                "name": None,
                "role": "button",
                "aria_label": None,
                "xpath": None,
                "css_selector": None,
                "parent_path": [],
            },
        }

    def test_initial_plan_response_uses_existing_step_schema(self):
        response = {
            "milestones": [{
                "goal": "Continue setup",
                "success_hint": {"url_contains": [], "text_contains": ["Setup"]},
            }],
            "steps": [self.website_step()],
        }
        with patch.object(self.generator, "_generate_json", return_value=response):
            plan_response = self.generator.generate_plan_and_steps("finish setup", "https://site.test", [])
        self.assertEqual(plan_response.steps[0], self.website_step())
        step = Step.from_dict(plan_response.steps[0])
        self.assertEqual(step.target, "Continue")
        self.assertEqual(set(plan_response.steps[0]), {"step_number", "action", "description", "element"})

    def test_verify_and_generate_sends_current_plan_context(self):
        plan = TaskPlan.single_milestone("finish setup")
        response = {
            "milestone_met": False,
            "goal_complete": False,
            "reason": "Continue on this page",
            "revised_remaining_milestones": None,
            "steps": [self.website_step()],
        }
        with patch.object(self.generator, "_generate_json", return_value=response) as generate:
            result = self.generator.verify_and_generate(
                plan, "Open settings", "https://site.test", [{"id": 1}], False
            )
        self.assertIsInstance(result, VerifyResponse)
        self.assertFalse(result.milestone_met)
        self.assertEqual(result.steps, [self.website_step()])
        payload = generate.call_args.args[0]
        self.assertIn("Open settings", payload)
        self.assertIn("finish setup", payload)
        self.assertIn("https://site.test", payload)

    def test_empty_initial_plan_is_rejected(self):
        with patch.object(self.generator, "_generate_json", return_value={"milestones": [], "steps": []}):
            with self.assertRaises(ValueError):
                self.generator.generate_plan_and_steps("goal", "https://site.test", [])

    def test_malformed_json_retries_once(self):
        valid = '{"steps": [], "app_exe": ""}'
        self.generator._client = Mock()
        with patch.object(self.generator, "_generate_content_once", side_effect=["not json", valid]), \
             patch("core.ai_task_generator.time.sleep") as sleep:
            result = self.generator._generate_json(
                "prompt", "system", None, self.generator._validate_app_result
            )
        self.assertEqual(result["steps"], [])
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
