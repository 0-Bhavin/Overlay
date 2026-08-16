"""Unit tests for WebResolver, HybridResolver web routing, and ActionWatcher web mode.

Run with:
    python -m pytest tests/test_web_resolver.py -v

No browser or extension required — all WebSocket interactions are mocked.
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is importable when running directly from tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.step import Step
from core.task import Task


# ---------------------------------------------------------------------------
# Helpers — mock BrowserConnector
# ---------------------------------------------------------------------------

class _MockBrowserConnector:
    """Lightweight stand-in for BrowserConnector.

    Allows tests to inject predetermined responses without a real WebSocket.
    """

    def __init__(self, viewport_response=None, resolve_response=None):
        self.active_socket = object()   # truthy — signals "connected"
        self._loop = asyncio.new_event_loop()
        self._pending_responses: dict = {}
        self._change_callbacks: list = []

        self._viewport_response = viewport_response or {
            "screenX": 100,
            "screenY": 50,
            "outerWidth": 1280,
            "outerHeight": 820,
            "innerWidth": 1280,
            "innerHeight": 760,  # toolbar = 820 - 760 = 60 px
        }
        self._resolve_response = resolve_response or {
            "found": True,
            "elementId": "aiov-123",
            "resolvedBy": "aria-label",
            "rect": {"x": 80, "y": 120, "width": 100, "height": 36},
        }

    def _simulate_send_and_wait(self, payload: dict, timeout: float) -> dict | None:
        """Return the pre-configured mock response based on payload type."""
        msg_type = payload.get("type", "")
        if msg_type == "get_viewport_info":
            resp = dict(self._viewport_response)
            resp["req_id"] = payload.get("req_id", "")
            return resp
        if msg_type == "resolve_element":
            resp = dict(self._resolve_response)
            resp["req_id"] = payload.get("req_id", "")
            return resp
        return None

    def observe_changes(self, callback):
        self._change_callbacks.append(callback)


def _make_web_step(
    step_id: int = 1,
    target: str = "Compose",
    web_element: dict | None = None,
) -> Step:
    return Step(
        id=step_id,
        target=target,
        tooltip=f"Click {target}",
        target_type="web",
        web_element=web_element or {
            "tag": "div",
            "text": "Compose",
            "aria_label": "Compose",
            "role": "button",
        },
    )


# ---------------------------------------------------------------------------
# Tests: Step schema
# ---------------------------------------------------------------------------

class TestStepSchema(unittest.TestCase):

    def test_desktop_step_defaults(self):
        step = Step(id=1, target="File", tooltip="Click File")
        self.assertEqual(step.target_type, "desktop")
        self.assertIsNone(step.web_element)

    def test_web_step_fields(self):
        step = _make_web_step()
        self.assertEqual(step.target_type, "web")
        self.assertIsNotNone(step.web_element)

    def test_from_dict_desktop(self):
        d = {
            "id": 1,
            "target": "Insert tab",
            "tooltip": "Click the Insert tab.",
            "action": "click",
            "spotlight_shape": "rect",
            "animation": "pulse",
            "explanation": "Opens Insert ribbon.",
        }
        step = Step.from_dict(d)
        self.assertEqual(step.target_type, "desktop")
        self.assertIsNone(step.web_element)

    def test_from_dict_web(self):
        d = {
            "id": 1,
            "target_type": "web",
            "target": "Sign in",
            "tooltip": "Click the Sign in link.",
            "web_element": {"tag": "a", "text": "Sign in", "id": "29"},
        }
        step = Step.from_dict(d)
        self.assertEqual(step.target_type, "web")
        self.assertEqual(step.web_element["tag"], "a")


# ---------------------------------------------------------------------------
# Tests: Task schema
# ---------------------------------------------------------------------------

class TestTaskSchema(unittest.TestCase):

    def test_load_desktop_task(self):
        path = str(Path(__file__).parent.parent / "tasks" / "insert_image_word.json")
        task = Task.load_from_file(path)
        self.assertEqual(task.target_type, "desktop")
        self.assertEqual(task.url, "")
        for step in task.steps:
            self.assertEqual(step.target_type, "desktop")

    def test_load_normalized_web_task(self):
        path = str(Path(__file__).parent.parent / "tasks" / "generated_task.json")
        task = Task.load_from_file(path)
        self.assertEqual(task.target_type, "web")
        for step in task.steps:
            self.assertEqual(step.target_type, "web")
            self.assertIsNotNone(step.web_element)

    def test_load_mixed_task(self):
        path = str(Path(__file__).parent.parent / "tasks" / "mixed_desktop_web_task.json")
        task = Task.load_from_file(path)
        self.assertEqual(task.steps[0].target_type, "desktop")
        for step in task.steps[1:]:
            self.assertEqual(step.target_type, "web")


# ---------------------------------------------------------------------------
# Tests: WebResolver coordinate conversion
# ---------------------------------------------------------------------------

class TestWebResolverCoords(unittest.TestCase):

    def _make_resolver(self, viewport=None, element=None):
        from platforms.web_resolver import WebResolver
        bc = _MockBrowserConnector(
            viewport_response=viewport,
            resolve_response=element,
        )
        resolver = WebResolver(bc)
        # Patch the internal _send_and_wait to use the mock
        resolver._send_and_wait = bc._simulate_send_and_wait
        return resolver, bc

    def test_basic_coord_conversion(self):
        """screen = (screenX + rect.x, screenY + toolbar + rect.y)"""
        resolver, _ = self._make_resolver()
        step = _make_web_step()
        coords = resolver.resolve(step)
        # screenX=100, rect.x=80  → L = 180
        # screenY=50, toolbar=60, rect.y=120 → T = 230
        # width=100 → R = 280, height=36 → B = 266
        self.assertEqual(coords, (180, 230, 280, 266))

    def test_zero_toolbar(self):
        """When outerHeight == innerHeight (toolbar 0), coords match viewport directly."""
        resolver, _ = self._make_resolver(viewport={
            "screenX": 0, "screenY": 0,
            "outerWidth": 1920, "outerHeight": 1080,
            "innerWidth": 1920, "innerHeight": 1080,
        }, element={
            "found": True, "elementId": "aiov-1", "resolvedBy": "id",
            "rect": {"x": 200, "y": 300, "width": 50, "height": 20},
        })
        step = _make_web_step()
        l, t, r, b = resolver.resolve(step)
        self.assertEqual(l, 200)
        self.assertEqual(t, 300)
        self.assertEqual(r, 250)
        self.assertEqual(b, 320)

    def test_high_dpi_screen_offset(self):
        """Toolbar and screen offsets on a 1440p monitor with offset taskbar."""
        resolver, _ = self._make_resolver(viewport={
            "screenX": 1920, "screenY": 0,   # second monitor
            "outerWidth": 2560, "outerHeight": 1440,
            "innerWidth": 2560, "innerHeight": 1390,  # toolbar = 50px
        }, element={
            "found": True, "elementId": "aiov-9", "resolvedBy": "text+tag",
            "rect": {"x": 0, "y": 0, "width": 150, "height": 40},
        })
        step = _make_web_step()
        l, t, r, b = resolver.resolve(step)
        self.assertEqual(l, 1920)   # screenX + rect.x
        self.assertEqual(t, 50)     # screenY + toolbar + rect.y = 0+50+0
        self.assertEqual(r, 2070)
        self.assertEqual(b, 90)

    def test_element_not_connected(self):
        """Raises ElementNotFoundError when no extension is connected."""
        from platforms.web_resolver import WebResolver
        from platforms.uia_resolver import ElementNotFoundError
        bc = _MockBrowserConnector()
        bc.active_socket = None   # simulate disconnected
        resolver = WebResolver(bc)
        step = _make_web_step()
        with self.assertRaises(ElementNotFoundError):
            resolver.resolve(step)

    def test_element_not_found(self):
        """Raises ElementNotFoundError when extension can't find the element."""
        from platforms.uia_resolver import ElementNotFoundError
        resolver, _ = self._make_resolver(element={
            "found": False, "elementId": None, "resolvedBy": "none", "rect": None,
        })
        step = _make_web_step()
        with self.assertRaises(ElementNotFoundError):
            resolver.resolve(step)

    def test_resolved_element_id_stored(self):
        """After resolve(), web_element['resolved_element_id'] is populated."""
        resolver, _ = self._make_resolver()
        step = _make_web_step()
        resolver.resolve(step)
        self.assertEqual(step.web_element.get("resolved_element_id"), "aiov-123")


# ---------------------------------------------------------------------------
# Tests: HybridResolver routing
# ---------------------------------------------------------------------------

class TestHybridResolverRouting(unittest.TestCase):

    def test_desktop_step_uses_uia(self):
        """A desktop step never calls WebResolver even if browser_connector is provided."""
        from platforms.hybrid_resolver import HybridResolver
        resolver = HybridResolver()
        resolver._uia = None  # force UIA unavailable

        step = Step(id=1, target="File", tooltip="Click File", target_type="desktop")
        from platforms.uia_resolver import ElementNotFoundError
        with self.assertRaises(ElementNotFoundError) as ctx:
            resolver.resolve("Notepad", "File", step=step, browser_connector=MagicMock())
        self.assertIn("unavailable", str(ctx.exception).lower())

    def test_web_step_without_connector_raises(self):
        """A web step with browser_connector=None raises ElementNotFoundError."""
        from platforms.hybrid_resolver import HybridResolver
        from platforms.uia_resolver import ElementNotFoundError
        resolver = HybridResolver()
        step = _make_web_step()
        with self.assertRaises(ElementNotFoundError):
            resolver.resolve("browser", "Compose", step=step, browser_connector=None)

    def test_web_step_calls_web_resolver(self):
        """A web step routes to WebResolver and returns coords."""
        from platforms.hybrid_resolver import HybridResolver
        from platforms.web_resolver import WebResolver

        resolver = HybridResolver()
        step = _make_web_step()
        bc = _MockBrowserConnector()

        # Inject mock WebResolver
        mock_web = MagicMock(spec=WebResolver)
        mock_web.resolve.return_value = (100, 200, 300, 400)
        mock_web._bc = bc
        resolver._web = mock_web

        coords = resolver.resolve("browser", "Compose", step=step, browser_connector=bc)
        mock_web.resolve.assert_called_once_with(step)
        self.assertEqual(coords, (100, 200, 300, 400))

    def test_legacy_call_without_step_uses_uia(self):
        """Calls without step= still route to UIA (backward compat)."""
        from platforms.hybrid_resolver import HybridResolver
        from platforms.uia_resolver import ElementNotFoundError
        resolver = HybridResolver()
        resolver._uia = None
        with self.assertRaises(ElementNotFoundError) as ctx:
            resolver.resolve("Notepad", "File")
        self.assertIn("unavailable", str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# Tests: ActionWatcher web mode
# ---------------------------------------------------------------------------

class TestActionWatcherWebMode(unittest.TestCase):

    def setUp(self):
        # PyQt6 QObject requires a QApplication
        from PyQt6.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication(sys.argv)

    def _make_watcher(self):
        from core.action_watcher import ActionWatcher
        from PyQt6.QtCore import QRect
        watcher = ActionWatcher()
        return watcher

    def test_web_callback_registered(self):
        from PyQt6.QtCore import QRect
        watcher = self._make_watcher()
        bc = _MockBrowserConnector()
        watcher.start_watching(QRect(0, 0, 100, 50), target_type="web", browser_connector=bc)
        self.assertEqual(len(bc._change_callbacks), 1)
        watcher.stop_watching()

    def test_web_callback_unregistered_on_stop(self):
        from PyQt6.QtCore import QRect
        watcher = self._make_watcher()
        bc = _MockBrowserConnector()
        watcher.start_watching(QRect(0, 0, 100, 50), target_type="web", browser_connector=bc)
        watcher.stop_watching()
        self.assertEqual(len(bc._change_callbacks), 0)

    def test_web_action_fires_signal(self):
        """web_action_detected event triggers action_detected signal."""
        from PyQt6.QtCore import QRect
        watcher = self._make_watcher()
        bc = _MockBrowserConnector()

        fired = []
        watcher.action_detected.connect(lambda: fired.append(True))

        watcher.start_watching(QRect(0, 0, 100, 50), target_type="web", browser_connector=bc)

        # Simulate the extension sending a click event via the callback
        cb = bc._change_callbacks[0]
        cb({"type": "web_action_detected", "elementId": None})

        # Wait for the 400 ms settle timer
        deadline = time.monotonic() + 2.0
        while not fired and time.monotonic() < deadline:
            self._app.processEvents()
            time.sleep(0.05)

        self.assertTrue(fired, "action_detected should have fired after web_action_detected")

    def test_element_id_filter(self):
        """Callback for a different element id should not fire signal."""
        from PyQt6.QtCore import QRect
        watcher = self._make_watcher()
        bc = _MockBrowserConnector()

        fired = []
        watcher.action_detected.connect(lambda: fired.append(True))

        watcher.start_watching(
            QRect(0, 0, 100, 50),
            target_type="web",
            browser_connector=bc,
            web_element_id="aiov-99",
        )

        cb = bc._change_callbacks[0]
        cb({"type": "web_action_detected", "elementId": "aiov-other"})

        # Short wait — signal should NOT fire
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            self._app.processEvents()
            time.sleep(0.05)

        self.assertFalse(fired, "action_detected should NOT have fired for a different elementId")


# ---------------------------------------------------------------------------
# Tests: ai_task_generator normalizer
# ---------------------------------------------------------------------------

class TestWebResultNormalizer(unittest.TestCase):

    def _normalize(self, raw: dict, app_name="example.com", url="https://example.com") -> dict:
        from core.ai_task_generator import GeminiTaskGenerator
        return GeminiTaskGenerator._normalize_website_result(raw, app_name=app_name, url=url)

    def test_basic_normalization(self):
        raw = {
            "task": "Sign in",
            "steps": [
                {
                    "step_number": 1,
                    "action": "click",
                    "description": "Click the Sign in link.",
                    "element": {
                        "tag": "a", "text": "Sign in", "id": "29",
                        "role": "link", "aria_label": None,
                        "xpath": "//a[text()='Sign in']",
                    }
                }
            ]
        }
        result = self._normalize(raw)
        self.assertEqual(result["target_type"], "web")
        self.assertEqual(result["url"], "https://example.com")
        step = result["steps"][0]
        self.assertEqual(step["id"], 1)
        self.assertEqual(step["target_type"], "web")
        self.assertEqual(step["target"], "Sign in")
        self.assertEqual(step["tooltip"], "Click the Sign in link.")
        self.assertEqual(step["web_element"]["tag"], "a")

    def test_target_fallback_chain(self):
        """Target uses aria_label when text is empty."""
        raw = {
            "steps": [{
                "step_number": 1,
                "action": "click",
                "description": "Click compose",
                "element": {"tag": "div", "text": "", "aria_label": "Compose", "id": None}
            }]
        }
        result = self._normalize(raw)
        self.assertEqual(result["steps"][0]["target"], "Compose")

    def test_multiple_steps(self):
        raw = {
            "task": "Multi step",
            "steps": [
                {"step_number": i, "action": "click", "description": f"Step {i}",
                 "element": {"tag": "button", "text": f"Button {i}"}}
                for i in range(1, 4)
            ]
        }
        result = self._normalize(raw)
        self.assertEqual(len(result["steps"]), 3)
        self.assertEqual(result["steps"][2]["id"], 3)

    def test_roundtrip_via_step_from_dict(self):
        """Normalised steps should deserialise correctly through Step.from_dict."""
        raw = {
            "steps": [{
                "step_number": 1, "action": "type", "description": "Enter email",
                "element": {"tag": "input", "text": "", "name": "email", "aria_label": "Email"}
            }]
        }
        result = self._normalize(raw)
        step = Step.from_dict(result["steps"][0])
        self.assertEqual(step.target_type, "web")
        self.assertEqual(step.action, "type")
        self.assertIsNotNone(step.web_element)


if __name__ == "__main__":
    unittest.main()
