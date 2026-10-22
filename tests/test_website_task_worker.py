import unittest
from unittest.mock import Mock, patch

from core.ai_task_generator import VerifyResponse
from core.task_plan import TaskPlan
from main import _SubTaskWorker, _filter_steps_to_dom


class TestSubTaskWorker(unittest.TestCase):
    def setUp(self):
        self.connector = Mock()
        self.connector.get_tree.return_value = [{
            "id": 7,
            "type": "button",
            "text": "Save",
            "role": "button",
        }]
        self.connector.current_url = "https://example.test/editor"
        self.plan = TaskPlan.single_milestone("Save the document")

    def test_calls_mocked_generator_with_fresh_context(self):
        generated = VerifyResponse(
            milestone_met=False,
            goal_complete=False,
            reason="Save is available on this page",
            revised_remaining_milestones=None,
            steps=[{
                "step_number": 1,
                "action": "click",
                "description": "Click Save",
                "element": {"tag": "button", "text": "Save"},
            }],
        )
        worker = _SubTaskWorker(self.connector, "fake-key", self.plan, "Opened editor")
        results = []
        failures = []
        worker.succeeded.connect(results.append)
        worker.failed.connect(failures.append)

        with patch("main.GeminiTaskGenerator") as generator_class:
            generator_class.return_value.verify_and_generate.return_value = generated
            worker.run()

        self.assertEqual(failures, [])
        payload = results[0]
        self.assertEqual(payload["dom"], self.connector.get_tree.return_value)
        self.assertEqual(payload["url"], self.connector.current_url)
        generator_class.return_value.verify_and_generate.assert_called_once_with(
            self.plan,
            "Opened editor",
            self.connector.current_url,
            self.connector.get_tree.return_value,
            False,
        )

    def test_last_milestone_hint_shortcut_skips_model_call(self):
        milestone = self.plan.current()
        assert milestone is not None
        milestone["success_hint"] = {
            "url_contains": ["/editor"],
            "text_contains": [],
        }
        worker = _SubTaskWorker(self.connector, "fake-key", self.plan, "Opened editor")
        results = []
        worker.succeeded.connect(results.append)

        with patch("main.GeminiTaskGenerator") as generator_class:
            worker.run()

        generator_class.assert_not_called()
        self.assertTrue(results[0]["response"].goal_complete)
        self.assertTrue(results[0]["hint_matched"])


class TestGroundWebsiteSteps(unittest.TestCase):
    def setUp(self):
        # Simplified excerpt of GitHub's repository creation page. The
        # extractor supplies accessible text for the empty controls.
        self.dom = [
            {"id": 66, "type": "label", "text": "Repository name *", "role": "label"},
            {"id": 70, "type": "input:text", "text": "Repository name *", "role": "input"},
            {"id": 91, "type": "button", "text": "Public (opens menu)", "role": "button"},
            {"id": 110, "type": "div", "text": "Off", "role": "div"},
            {"id": 112, "type": "button", "text": "Off", "role": "button"},
            {"id": 119, "type": "div", "text": "No .gitignore", "role": "div"},
            {"id": 120, "type": "button", "text": "No .gitignore", "role": "button"},
            {"id": 130, "type": "button", "text": "No license", "role": "button"},
        ]

    @staticmethod
    def step(number, tag, text, description, element_id=None):
        return {"step_number": number, "action": "click", "description": description,
                "element": {"tag": tag, "text": text, "id": element_id}}

    def test_form_input_and_switch_are_retained(self):
        steps = [
            self.step(1, "input", "Repository name", "Enter bench-demo into the repository name field", "70"),
            self.step(2, "button", "Off", "Turn on Add README", "112"),
        ]
        result = _filter_steps_to_dom(steps, self.dom)
        self.assertEqual([s["element"]["id"] for s in result], ["70", "112"])
        self.assertEqual(result[0]["element"]["text"], "Repository name *")

    def test_dropdown_grounds_button_not_div_and_stops_before_hidden_choices(self):
        steps = [
            self.step(1, "button", "No .gitignore", "Open the .gitignore dropdown to choose Python"),
            self.step(2, "button", "No license", "Open license dropdown to choose MIT"),
        ]
        result = _filter_steps_to_dom(steps, self.dom)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["element"]["id"], "120")

    def test_visibility_picker_stops_before_readme_until_private_is_selected(self):
        steps = [
            self.step(1, "input", "Repository name", "Type bench-demo into the repository name field", "70"),
            self.step(2, "button", "Public", "Click Public to set visibility to Private", "91"),
            self.step(3, "button", "Off", "Enable README", "112"),
        ]
        result = _filter_steps_to_dom(steps, self.dom)
        self.assertEqual([s["element"]["id"] for s in result], ["70", "91"])
        self.assertEqual(result[-1]["element"]["text"], "Public (opens menu)")
        self.dom[2]["text"] = "Public"  # custom picker without aria-haspopup
        self.assertEqual(len(_filter_steps_to_dom(steps, self.dom)), 2)

    def test_label_wrapper_click_uses_equivalently_named_button(self):
        steps = [self.step(1, "div", "No .gitignore", "Open the .gitignore dropdown", "119")]
        result = _filter_steps_to_dom(steps, self.dom)
        self.assertEqual(result[0]["element"]["id"], "120")

    def test_does_not_ground_hallucinated_text_to_unrelated_id(self):
        steps = [self.step(1, "button", "Python", "Choose Python", "130")]
        self.assertEqual(_filter_steps_to_dom(steps, self.dom), [])


if __name__ == "__main__":
    unittest.main()
