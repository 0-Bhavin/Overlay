import json
import os
import tempfile
import unittest

from types import SimpleNamespace

from core.task_plan import (
    MAX_ATTEMPTS_PER_MILESTONE,
    MAX_REPLANS,
    TaskPlan,
    apply_verification,
    dom_text,
    tier1_match,
)


class TestTaskPlan(unittest.TestCase):
    def setUp(self):
        self.plan = TaskPlan("buy item", [
            {"goal": "Open product", "success_hint": {"url_contains": ["/product"], "text_contains": ["Product"]}},
            {"goal": "Checkout", "success_hint": {"url_contains": ["/checkout"], "text_contains": ["Order summary"]}},
        ])

    def test_initial_milestone_is_active(self):
        self.assertEqual(self.plan.current()["status"], "active")
        self.assertEqual(self.plan.current_index, 0)
        self.assertFalse(self.plan.is_last())

    def test_advance_marks_done_and_resets_attempts(self):
        self.plan.mark_attempt()
        self.plan.advance()
        self.assertEqual(self.plan.milestones[0]["status"], "done")
        self.assertEqual(self.plan.milestones[1]["status"], "active")
        self.assertEqual(self.plan.current()["attempts"], 0)
        self.assertTrue(self.plan.is_last())

    def test_mark_attempt_and_cap(self):
        attempts = [self.plan.mark_attempt() for _ in range(MAX_ATTEMPTS_PER_MILESTONE + 1)]
        self.assertEqual(attempts[-1], MAX_ATTEMPTS_PER_MILESTONE + 1)

    def test_replace_remaining_preserves_completed(self):
        self.plan.advance()
        self.plan.replace_remaining([{
            "goal": "Finish purchase",
            "success_hint": {"url_contains": [], "text_contains": ["Receipt"]},
        }])
        self.assertEqual(self.plan.milestones[0]["status"], "done")
        self.assertEqual(self.plan.current_index, 1)
        self.assertEqual(self.plan.current()["goal"], "Finish purchase")
        self.assertEqual(self.plan.current()["status"], "active")
        self.assertEqual(self.plan.replans, 1)

    def test_persistence_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "plan.json")
            self.plan.mark_attempt()
            self.plan.save(path)
            loaded = TaskPlan.load(path)
        self.assertEqual(loaded.to_dict(), self.plan.to_dict())

    def test_single_milestone_factory(self):
        plan = TaskPlan.single_milestone("save document")
        self.assertEqual(plan.current()["goal"], "save document")
        self.assertEqual(plan.current()["status"], "active")

    def test_verification_not_met_keeps_current_milestone(self):
        update = apply_verification(self.plan, SimpleNamespace(
            milestone_met=False, goal_complete=False, revised_remaining_milestones=None,
        ))
        self.assertFalse(update.goal_complete)
        self.assertFalse(update.milestone_advanced)
        self.assertEqual(self.plan.current_index, 0)

    def test_verification_met_advances(self):
        update = apply_verification(self.plan, SimpleNamespace(
            milestone_met=True, goal_complete=False, revised_remaining_milestones=None,
        ))
        self.assertTrue(update.milestone_advanced)
        self.assertEqual(self.plan.current_index, 1)

    def test_goal_complete_is_returned_to_orchestrator(self):
        update = apply_verification(self.plan, SimpleNamespace(
            milestone_met=True, goal_complete=True, revised_remaining_milestones=None,
        ))
        self.assertTrue(update.goal_complete)

    def test_replan_respects_limit(self):
        new = [{"goal": "Revised goal", "success_hint": {"url_contains": [], "text_contains": []}}]
        update = apply_verification(self.plan, SimpleNamespace(
            milestone_met=False, goal_complete=False, revised_remaining_milestones=new,
        ))
        self.assertTrue(update.replan_applied)
        self.assertEqual(self.plan.current()["goal"], "Revised goal")
        self.plan.replans = MAX_REPLANS
        update = apply_verification(self.plan, SimpleNamespace(
            milestone_met=False, goal_complete=False, revised_remaining_milestones=new,
        ))
        self.assertFalse(update.replan_applied)

    def test_empty_steps_are_not_interpreted_as_completion(self):
        update = apply_verification(self.plan, SimpleNamespace(
            milestone_met=False, goal_complete=False, revised_remaining_milestones=None, steps=[],
        ))
        self.assertFalse(update.goal_complete)
        self.assertIsNotNone(self.plan.current())


class TestTier1Match(unittest.TestCase):
    def test_empty_hint_does_not_match(self):
        self.assertFalse(tier1_match({}, "https://site.test/checkout", "Order summary"))
        self.assertFalse(tier1_match(None, "https://site.test/checkout", "Order summary"))

    def test_url_match(self):
        hint = {"url_contains": ["/checkout"], "text_contains": []}
        self.assertTrue(tier1_match(hint, "https://site.test/checkout", ""))

    def test_text_match_is_case_insensitive(self):
        hint = {"url_contains": [], "text_contains": ["Order Summary"]}
        self.assertTrue(tier1_match(hint, "https://site.test", "Your ORDER SUMMARY is ready"))

    def test_dom_text_is_bounded(self):
        self.assertEqual(dom_text([{"text": "Page"}, {"text": "Title"}]), "Page Title")


if __name__ == "__main__":
    unittest.main()
