"""Main entry point for the AI overlay application."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import Callable
from typing import Any, cast

from PyQt6.QtCore import QObject, Qt, QRect, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QMessageBox

# Force 1:1 pixel mapping so pywinauto's physical pixel coords match Qt's
# coordinate space exactly. Without this, on a 125% DPI display Qt uses
# logical pixels (physical / 1.25) which shifts every spotlight/dim rect.
QApplication.setAttribute(Qt.ApplicationAttribute.AA_Use96Dpi)

from core.overlay_window import OverlayWindow
from core.layer_manager import LayerManager
from core.task_controller import TaskController
from core.action_watcher import ActionWatcher
from core.step import Step
from core.UI import TaskInputDialog
from core.tts import TTSEngine
from core.completion_toast import CompletionToast
from core.ai_task_generator import GeminiTaskGenerator, VerifyResponse
from core.website_step_grounding import filter_steps_to_dom as _filter_steps_to_dom
from core.task_plan import (
    MAX_ATTEMPTS_PER_MILESTONE,
    MAX_REPLANS,
    TaskPlan,
    apply_verification,
    dom_text,
    tier1_match,
)
from platforms.browser_connector import BrowserConnector
from dotenv import load_dotenv
load_dotenv()

_log = logging.getLogger(__name__)


class _MainThreadInvoker(QObject):
    requested = pyqtSignal()
    event_received = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.requested_callback: Callable[[], None] | None = None
        self.event_callback: Callable[[dict], None] | None = None
        self.requested.connect(self._dispatch_request)
        self.event_received.connect(self._dispatch_event)

    @pyqtSlot()
    def _dispatch_request(self) -> None:
        if self.requested_callback is not None:
            self.requested_callback()

    @pyqtSlot(object)
    def _dispatch_event(self, event: object) -> None:
        if self.event_callback is not None and isinstance(event, dict):
            self.event_callback(event)


class _SubTaskWorker(QObject):
    """Fetch current-page evidence and make one combined Gemini verify/generate call."""

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        connector: BrowserConnector,
        api_key: str,
        plan: TaskPlan,
        last_completed_step: str,
    ) -> None:
        super().__init__()
        self._connector = connector
        self._api_key = api_key
        self._plan = plan
        self._last_completed_step = last_completed_step

    @pyqtSlot()
    def run(self) -> None:
        try:
            dom = self._connector.get_tree(timeout=8.0)
            # Retry if the page is still loading (0 nodes returned after navigation)
            if not dom:
                _log.info("MilestoneVerifyWorker: empty DOM on first fetch — page may still be loading, retrying...")
                for _attempt in range(5):
                    time.sleep(2.0)
                    dom = self._connector.get_tree(timeout=8.0)
                    _log.info("MilestoneVerifyWorker: retry %d returned %d nodes", _attempt + 1, len(dom))
                    if dom:
                        break
            if not dom:
                raise RuntimeError("The browser returned an empty DOM at the verification point")
            url = self._connector.current_url or "Current browser page"
            current = self._plan.current()
            hint_matched = tier1_match(
                current.get("success_hint") if current else None,
                url,
                dom_text(dom),
            )
            if self._plan.is_last() and hint_matched:
                response = VerifyResponse(
                    milestone_met=True,
                    goal_complete=True,
                    reason="Last milestone success hint matched current page",
                    revised_remaining_milestones=None,
                    steps=[],
                )
            else:
                response = GeminiTaskGenerator(self._api_key).verify_and_generate(
                    self._plan,
                    self._last_completed_step,
                    url,
                    dom,
                    hint_matched,
                )
            self.succeeded.emit({
                "response": response,
                "dom": dom,
                "url": url,
                "hint_matched": hint_matched,
            })
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


# ── API key ───────────────────────────────────────────────────────────────────
# Gemini is the sole task-generation provider.
_GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
if not _GEMINI_API_KEY:
    _log.warning("GEMINI_API_KEY is not set; task generation will require a key in .env.")


def _get_step_element_id(step: Step) -> int | None:
    """Return the DOM element ID for a step, or None if not available."""
    return getattr(step, "element_id", None)



def main() -> None:
    # ── 1. Application ────────────────────────────────────────────
    app = QApplication(sys.argv)
    app.setApplicationName("AI Overlay")

    # ── 2. TTS engine & Browser Connector ─────────────────────────
    tts = TTSEngine()
    browser_connector = BrowserConnector()  # Starts WebSocket server on ws://localhost:8765

    # ── 3. Core overlay objects (hidden until task is ready) ──────────
    overlay       = OverlayWindow()
    layer_manager = LayerManager(overlay, tts=tts)
    controller    = TaskController(layer_manager)
    hud           = layer_manager.hud_layer
    watcher       = ActionWatcher()

    # ── 4. Shared exit handler ────────────────────────────────────────
    def _on_exit() -> None:
        watcher.shutdown()
        controller.shutdown()
        tts.shutdown()
        browser_connector.shutdown()
        overlay.hide_overlay()
        app.quit()

    # ── 5. Task-completion celebration (feature 1.4) ──────────────────
    def _on_task_completed() -> None:
        watcher.shutdown()
        controller.shutdown()
        browser_connector.shutdown()
        overlay.hide_overlay()
        # Show toast; quit when it finishes fading out
        _toast = CompletionToast(callback=lambda: (tts.shutdown(), app.quit()))  # noqa: F841
        # Keep a reference so GC doesn't collect it
        app._completion_toast = _toast  # type: ignore[attr-defined]

    # ── 6. HUD navigation signals ─────────────────────────────────────
    hud.exit_clicked.connect(_on_exit)

    # Pause: hide spotlight/dim/tooltip but keep HUD visible
    def _on_pause(is_paused: bool) -> None:
        layer_manager.set_paused(is_paused)
        if is_paused:
            watcher.stop_watching()

    hud.paused.connect(_on_pause)

    # 1.8  Step dots — random-access navigation
    hud.step_dot_clicked.connect(controller.go_to_step)

    # ── 7. Step-complete flash (feature 1.3) before advancing ─────────
    def _advance_with_flash() -> None:
        """Show green ✓ flash on current spotlight, then advance."""
        layer_manager.flash_step_complete(callback=controller.next_step)

    def _go_back_with_flash() -> None:
        layer_manager.flash_step_complete(callback=controller.prev_step)

    hud.next_clicked.connect(_advance_with_flash)
    hud.back_clicked.connect(_go_back_with_flash)

    # ── 8. Async coord-resolution signals ────────────────────────────
    controller.coords_resolved.connect(layer_manager.on_coords_resolved)
    controller.resolution_failed.connect(layer_manager.show_resolution_failed)

    def _on_element_not_found(target: str, error: object) -> None:
        layer_manager.show_recovery_panel(
            target=target,
            error=error,
            on_skip=controller.next_step,
            on_retry=lambda: controller.go_to_step(controller.current_step_index())
        )
    controller.element_not_found.connect(_on_element_not_found)

    # ── 8b. ActionWatcher — auto-advance on menu/dialog/focus events ──
    def _on_coords_resolved(step) -> None:
        if layer_manager.is_website_mode:
            return  # Website mode: extension handles overlay + click detection
        layer_manager.on_coords_resolved(step)
        if step.coords:
            l, t, r, b = step.coords
            watcher.start_watching(QRect(l, t, r - l, b - t))

    controller.coords_resolved.disconnect(layer_manager.on_coords_resolved)
    controller.coords_resolved.connect(_on_coords_resolved)

    # Auto-advance with flash when ActionWatcher fires
    def _on_action_detected() -> None:
        watcher.stop_watching()
        layer_manager.flash_step_complete(callback=controller.next_step)

    watcher.action_detected.connect(_on_action_detected)

    # Stop watcher when user manually navigates
    hud.next_clicked.connect(watcher.stop_watching)
    hud.back_clicked.connect(watcher.stop_watching)
    controller.task_completed.connect(watcher.shutdown)

    # ── 9. Step-counter: HUD + window title ───────────────────────────
    def _on_step_changed(index: int, total: int) -> None:
        hud.update_progress(index, total)
        overlay.setWindowTitle(f"AI Overlay — Step {index + 1} of {total}")
        # Send step update to browser extension for progress bar
        browser_connector.send_custom_message({
            'type': 'stepUpdate',
            'currentStep': index + 1,
            'totalSteps': total
        })

    controller.step_changed.connect(_on_step_changed)
    controller.task_completed.connect(_on_task_completed)

    # ── 10. Keyboard shortcuts ─────────────────────────────────────────
    sc_next = QShortcut(QKeySequence(Qt.Key.Key_Right), overlay)
    sc_next.setContext(Qt.ShortcutContext.ApplicationShortcut)
    sc_next.activated.connect(_advance_with_flash)

    sc_prev = QShortcut(QKeySequence(Qt.Key.Key_Left), overlay)
    sc_prev.setContext(Qt.ShortcutContext.ApplicationShortcut)
    sc_prev.activated.connect(_go_back_with_flash)

    sc_exit = QShortcut(QKeySequence(Qt.Key.Key_Escape), overlay)
    sc_exit.setContext(Qt.ShortcutContext.ApplicationShortcut)
    sc_exit.activated.connect(_on_exit)

    # ── 11. Task-input dialog ─────────────────────────────────────────
    dialog = TaskInputDialog(api_key=_GEMINI_API_KEY, browser_connector=browser_connector)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    def _on_task_ready(path: str, mode: str) -> None:
        """Called when AI generator finishes and the task JSON file is saved."""
        dialog.task_ready.disconnect(_on_task_ready)  # prevent double-load
        dialog.hide()
        dialog.close()

        if mode == "website":
            # ── Website mode setup ────────────────────────────────────────────
            # 1. Hide PyQt overlay immediately — browser extension renders instead
            layer_manager.set_mode("website")
            overlay.hide_overlay()

            # Track pending element_id and target for click detection
            pending_element_id: int | None = None
            pending_target: str = ""
            pending_action: str = ""
            subtask_thread: QThread | None = None
            subtask_worker: _SubTaskWorker | None = None
            navigation_pending = False
            empty_step_retries = 0
            waiting_poll_retries = 0
            last_completed_step = ""
            last_page_url = browser_connector.current_url
            navigation_invoker = _MainThreadInvoker()
            with open(path, encoding="utf-8") as task_file:
                original_task = json.load(task_file).get("name", "")
            plan_path = os.path.join(os.path.dirname(os.path.abspath(path)), "plan.json")
            try:
                task_plan = TaskPlan.load(plan_path)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                _log.warning("No valid milestone plan found; using one implicit milestone")
                task_plan = TaskPlan.single_milestone(original_task)

            # We'll wait for the browser extension to connect before proceeding
            timer = QTimer()
            timer.setInterval(1000)  # 1 second
            attempt = 0
            max_attempts = 10  # 10 seconds

            def check_connection():
                nonlocal attempt
                attempt += 1
                try:
                    # Try to get the DOM tree with a short timeout
                    tree = browser_connector.get_tree(timeout=0.5)
                    if browser_connector.is_connected:
                        _log.info(
                            "Browser extension connected (DOM nodes returned: %d).",
                            len(tree),
                        )
                        timer.stop()
                        setup_website_mode()
                        return
                except Exception as e:
                    _log.warning("Error checking extension connection: %s", e)
                # If we get here, the extension is not connected yet; continue timer
                if attempt >= max_attempts:
                    timer.stop()
                    _log.warning("Browser extension did not connect after %d seconds", max_attempts)
                    # Show a message box to the user
                    msg_box = QMessageBox()
                    msg_box.setIcon(QMessageBox.Icon.Warning)
                    msg_box.setWindowTitle("Browser Extension Not Connected")
                    msg_box.setText("The browser extension did not connect within the expected time.")
                    msg_box.setInformativeText("Please make sure the extension is installed and connected to ws://localhost:8765.")
                    msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
                    msg_box.exec()
                    # We cannot proceed in website mode without the extension, so we exit the application
                    app.quit()

            def setup_website_mode():
                # Now set up the website mode signals and load the task
                # ── Bug 1 fix: connect BEFORE load_task so step 1 is not missed ──
                def _on_step_resolved_website(step) -> None:
                    # Try to highlight immediately
                    result1 = browser_connector.highlight(
                        _get_step_element_id(step),
                        tooltip=step.tooltip,
                        target=getattr(step, "target", ""),
                    )
                    if not result1:
                        _log.warning("Highlight failed for step %d (first attempt)", step.id)
                    # Try again after a short delay
                    def try_again():
                        result2 = browser_connector.highlight(
                            _get_step_element_id(step),
                            tooltip=step.tooltip,
                            target=getattr(step, "target", ""),
                        )
                        if not result2:
                            _log.warning("Highlight failed for step %d (second attempt)", step.id)
                    QTimer.singleShot(200, try_again)

                def _track_element(step) -> None:
                    nonlocal pending_element_id, pending_target, pending_action
                    pending_element_id = _get_step_element_id(step)
                    pending_target = getattr(step, "target", "")
                    pending_action = str(getattr(step, "action", "click")).casefold()
                    if pending_action == "click":
                        import re
                        if re.search(r"\b(type|enter|fill|write)\b.*\b(field|input|name|text|description|title)\b", step.tooltip, re.IGNORECASE):
                            pending_action = "type"

                def _on_subtask_thread_finished() -> None:
                    nonlocal subtask_thread, subtask_worker
                    subtask_thread = None
                    subtask_worker = None

                def _show_stuck(reason: str) -> None:
                    _log.warning("Website task needs recovery: %s", reason)
                    QMessageBox.warning(
                        None,
                        "Task Needs Help",
                        "I couldn't determine the next safe step. The current workflow has been paused.\n\n"
                        + reason,
                    )

                _WAIT_KEYWORDS = (
                    "wait", "waiting", "provision", "provisioning", "creat",
                    "loading", "in progress", "not yet", "not available",
                    "being created", "still", "pending",
                )
                _MAX_WAIT_POLLS = 20   # up to 20 × 30 s = 10 minutes
                _WAIT_POLL_MS  = 30_000  # 30 seconds between polls

                def _on_subtask_success(payload: object) -> None:
                    nonlocal navigation_pending, empty_step_retries, waiting_poll_retries
                    navigation_pending = False
                    data = payload if isinstance(payload, dict) else {}
                    response = data.get("response")
                    dom = data.get("dom") or []
                    url = data.get("url") or browser_connector.current_url
                    hint_matched = bool(data.get("hint_matched"))
                    if not isinstance(response, VerifyResponse):
                        _show_stuck("Gemini returned an invalid verification response.")
                        return
                    if response.milestone_met != hint_matched:
                        _log.info(
                            "Milestone hint disagreement: heuristic=%s model=%s reason=%s",
                            hint_matched, response.milestone_met, response.reason,
                        )
                    update = apply_verification(task_plan, response)
                    if response.revised_remaining_milestones is not None and not update.replan_applied:
                        _log.warning("Ignoring model replan: MAX_REPLANS=%d reached", MAX_REPLANS)
                    if response.goal_complete:
                        task_plan.save(plan_path)
                        _log.info("Website task complete: %s", response.reason)
                        controller.task_completed.emit()
                        return
                    task_plan.save(plan_path)
                    grounded_steps = _filter_steps_to_dom(response.steps, dom)
                    if not grounded_steps:
                        reason_lower = (response.reason or "").lower()
                        is_wait_state = any(kw in reason_lower for kw in _WAIT_KEYWORDS)
                        if is_wait_state and waiting_poll_retries < _MAX_WAIT_POLLS:
                            waiting_poll_retries += 1
                            _log.info(
                                "Page is in a wait/provisioning state — polling again in %ds (%d/%d): %s",
                                _WAIT_POLL_MS // 1000, waiting_poll_retries, _MAX_WAIT_POLLS,
                                response.reason,
                            )
                            QTimer.singleShot(_WAIT_POLL_MS, _schedule_subtask_on_main_thread)
                            return
                        waiting_poll_retries = 0  # reset for next milestone
                        if empty_step_retries < 1:
                            empty_step_retries += 1
                            _log.info("No DOM-grounded steps generated; retrying after page settle (%d/1)", empty_step_retries)
                            QTimer.singleShot(1500, _schedule_subtask_on_main_thread)
                            return
                        _show_stuck(response.reason or "No actionable elements were found in the current page DOM.")
                        return
                    empty_step_retries = 0
                    waiting_poll_retries = 0
                    task_data = {
                        "name": original_task,
                        "app": url,
                        "app_exe": "",
                        "mode": "website",
                        "steps": grounded_steps,
                    }
                    output_dir = os.path.dirname(os.path.abspath(path))
                    snapshot_path = os.path.join(output_dir, "dom_snapshot.json")
                    subtask_path = os.path.join(output_dir, "sub_task.json")
                    try:
                        with open(snapshot_path, "w", encoding="utf-8") as fh:
                            json.dump(dom, fh, indent=2)
                        with open(subtask_path, "w", encoding="utf-8") as fh:
                            json.dump(task_data, fh, indent=2)
                        controller.load_task(subtask_path)
                    except Exception:
                        _log.exception("Failed to persist/load the generated sub-task")
                        _show_stuck("The generated steps could not be loaded.")

                def _on_subtask_failure(error: str) -> None:
                    nonlocal navigation_pending
                    navigation_pending = False
                    task_plan.save(plan_path)
                    _log.error("Milestone verification/generation failed after API retry: %s", error)
                    _show_stuck(f"Gemini API request failed: {error}")

                def _generate_subtask() -> None:
                    nonlocal subtask_thread, subtask_worker, navigation_pending
                    if subtask_thread is not None and subtask_thread.isRunning():
                        return
                    current_milestone = task_plan.current()
                    if current_milestone is None:
                        navigation_pending = False
                        _show_stuck("The milestone plan has no active milestone, but Gemini did not confirm completion.")
                        return
                    attempt = task_plan.mark_attempt()
                    task_plan.save(plan_path)
                    if attempt > MAX_ATTEMPTS_PER_MILESTONE:
                        if task_plan.replans < MAX_REPLANS:
                            remaining = cast(
                                list[dict[str, Any] | str],
                                task_plan.milestones[task_plan.current_index:],
                            )
                            task_plan.replace_remaining(remaining)
                            attempt = task_plan.mark_attempt()
                            task_plan.save(plan_path)
                            _log.warning("Forcing milestone replan after attempt cap (%d/%d)", task_plan.replans, MAX_REPLANS)
                        else:
                            navigation_pending = False
                            _show_stuck(f"Milestone attempt limit ({MAX_ATTEMPTS_PER_MILESTONE}) and replan limit ({MAX_REPLANS}) reached: {current_milestone['goal']}")
                            return
                    subtask_thread = QThread(app)
                    subtask_worker = _SubTaskWorker(
                        browser_connector,
                        _GEMINI_API_KEY,
                        task_plan,
                        last_completed_step,
                    )
                    subtask_worker.moveToThread(subtask_thread)
                    subtask_thread.started.connect(subtask_worker.run)
                    subtask_worker.succeeded.connect(_on_subtask_success)
                    subtask_worker.failed.connect(_on_subtask_failure)
                    subtask_worker.succeeded.connect(subtask_thread.quit)
                    subtask_worker.failed.connect(subtask_thread.quit)
                    subtask_thread.finished.connect(subtask_thread.deleteLater)
                    subtask_thread.finished.connect(_on_subtask_thread_finished)
                    subtask_thread.start()

                def _schedule_subtask() -> None:
                    """Request scheduling from any thread safely."""
                    navigation_invoker.requested.emit()

                def _schedule_subtask_on_main_thread() -> None:
                    nonlocal navigation_pending
                    if navigation_pending:
                        return
                    if subtask_thread is not None and subtask_thread.isRunning():
                        return
                    navigation_pending = True
                    QTimer.singleShot(2000, _generate_subtask)

                navigation_invoker.requested_callback = _schedule_subtask_on_main_thread

                def _handle_website_event(data: dict) -> None:
                    nonlocal pending_element_id, pending_target, pending_action, last_completed_step, last_page_url
                    msg_type = data.get("type")

                    if msg_type == "page_navigated":
                        new_url = str(data.get("url") or "")
                        url_changed = bool(new_url and new_url != last_page_url)
                        if new_url:
                            last_page_url = new_url
                        if url_changed:
                            # This covers full-page links even when an older
                            # extension service worker drops the click metadata.
                            _schedule_subtask()
                        return

                    if msg_type == "dom_mutated":
                        # DOM mutations are common in SPAs and must not
                        # re-highlight the current step. Full-page navigation
                        # is handled by the page_navigated event, which fetches
                        # a fresh DOM and generates sub_task.json.
                        return

                    if msg_type not in ("user_click", "user_input"):
                        return
                    is_text_entry = pending_action in ("type", "fill", "enter", "input", "write")
                    if is_text_entry != (msg_type == "user_input"):
                        return
                    if is_text_entry and not data.get("hasValue"):
                        return

                    clicked = data.get("elementId")
                    clicked_text = (data.get("targetText") or "").strip().lower()

                    matched = False
                    if clicked is not None and pending_element_id is not None:
                        if str(clicked) == str(pending_element_id):
                            matched = True
                    if not matched and pending_target and clicked_text:
                        if pending_target.lower() in clicked_text or clicked_text in pending_target.lower():
                            matched = True

                    if matched:
                        last_completed_step = pending_target or clicked_text
                        # Successful interaction is progress, not a failed attempt
                        # at this milestone (long forms can have many controls).
                        current = task_plan.current()
                        if current is not None:
                            current["attempts"] = 0
                            task_plan.save(plan_path)
                        # A later page_navigated event confirms whether this
                        # click changed pages. This also handles links whose
                        # click metadata incorrectly reports isNavigation=false.
                        pending_element_id = None
                        pending_target = ""
                        pending_action = ""
                        if data.get("isNavigation"):
                            # Wait for the new document to settle, then extract
                            # its DOM and generate tasks/sub_task.json.
                            _schedule_subtask()
                        else:
                            controller.next_step()

                def _on_website_click(data: dict) -> None:
                    # BrowserConnector callbacks arrive on its asyncio thread;
                    # process click/state changes on Qt's main thread.
                    navigation_invoker.event_received.emit(data)

                navigation_invoker.event_callback = _handle_website_event

                # Connect website-mode signals before loading the task
                controller.coords_resolved.disconnect(_on_coords_resolved)
                controller.resolution_failed.disconnect(layer_manager.show_resolution_failed)
                controller.coords_resolved.connect(_on_step_resolved_website)
                controller.coords_resolved.connect(_track_element)

                # Wire click/mutation detection from browser connector
                browser_connector.observe_changes(_on_website_click)
                controller.steps_exhausted.connect(_schedule_subtask_on_main_thread)

                # Now load the task — coords_resolved will fire for step 1 immediately
                # and _on_step_resolved_website is already connected to catch it
                try:
                    controller.load_task(path)
                except Exception:
                    _log.exception("Failed to load task from %s", path)
                    return

            # Start the timer to check for extension connection
            timer.timeout.connect(check_connection)
            timer.start()

        else:
            # ── App mode ─────────────────────────────────────────────────────
            try:
                controller.load_task(path)
            except Exception:
                _log.exception("Failed to load task from %s", path)
                return
            overlay.show_overlay()

    dialog.task_ready.connect(_on_task_ready)

    def _on_dialog_closed() -> None:
        # Only quit if no task was started
        if controller.total_steps() == 0 and not overlay.isVisible():
            controller.shutdown()
            tts.shutdown()
            app.quit()

    app.lastWindowClosed.connect(_on_dialog_closed)

    # ── 12. Show the input dialog ─────────────────────────────────────
    dialog.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
