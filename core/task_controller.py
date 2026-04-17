from __future__ import annotations

import dataclasses
import logging

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, pyqtSlot

from core.step import Step
from core.task import Task

try:
    from platforms.getwindow import get_resolver as _get_resolver
    _RESOLVER_AVAILABLE = True
except Exception:  # noqa: BLE001 — platform library not installed
    _RESOLVER_AVAILABLE = False

_log = logging.getLogger(__name__)

# ── Phase 4: remove this lookup table once the coord resolver is live. ────────
_FAKE_COORDS: dict[int, tuple[int, int, int, int]] = {
    1: (100,  60, 300,  96),   # simulates a ribbon tab
    2: (120, 100, 280, 140),
    3: (300, 200, 480, 240),
    4: (200, 300, 460, 344),
    5: (350, 420, 470, 456),
    6: (240, 260, 540, 460),
}

_RESOLUTION_TIMEOUT_MS: int = 10_000


# ---------------------------------------------------------------------------
# Background worker — runs on its own QThread
# ---------------------------------------------------------------------------

class _CoordWorker(QObject):
    """Resolves UI element coordinates on a background thread.

    Communicate with this object only via signals/slots so that every
    method invocation crosses the thread boundary safely.
    """

    # Emitted when AT-SPI successfully returns coords.
    resolved = pyqtSignal(object)   # payload: Step (with coords filled)
    # Emitted when AT-SPI cannot find the element or its coords.
    failed = pyqtSignal(str)        # payload: step.target

    def __init__(self) -> None:
        super().__init__()
        self._resolver = _get_resolver() if _RESOLVER_AVAILABLE else None

    @pyqtSlot(object, str)
    def resolve(self, step: Step, app_name: str) -> None:
        """Resolve coordinates on the worker thread via HybridResolver.resolve().

        Parameters
        ----------
        step:
            The step to resolve.
        app_name:
            The ``Task.app`` string used to locate the target window.
        """
        if self._resolver is None:
            self.failed.emit(step.target)
            return

        try:
            coords = self._resolver.resolve(app_name, step.target)
            if coords is None:
                _log.warning("Resolver returned None for %r in app %r", step.target, app_name)
                self.failed.emit(step.target)
                return

            # Sanity-check: reject implausibly large rects (full-window matches).
            # A real interactive element is almost never larger than 600×400 px.
            left, top, right, bottom = coords
            w, h = right - left, bottom - top
            if w > 600 or h > 400:
                _log.warning(
                    "Resolved rect for %r is suspiciously large (%dx%d) — discarding",
                    step.target, w, h,
                )
                self.failed.emit(step.target)
                return

            _log.debug("Resolved %r → %s", step.target, coords)
            self.resolved.emit(dataclasses.replace(step, coords=coords))
        except Exception as exc:  # noqa: BLE001
            _log.error("Resolution error for %r: %s", step.target, exc)
            self.failed.emit(step.target)




# ---------------------------------------------------------------------------
# TaskController
# ---------------------------------------------------------------------------

class TaskController(QObject):
    """Drives step-by-step progression through a :class:`~core.task.Task`.

    The controller is the single source of truth for *which* step is active.
    It delegates all visual updates to the ``LayerManager`` it was given at
    construction time.

    Coordinate resolution runs on a background ``QThread`` so the UI never
    blocks.  The rendering sequence for each step is:

    1. Immediately render the step *without* coords (spotlight hidden,
       tooltip shows "Locating element…").
    2. Kick off background AT-SPI resolution.
    3a. On success → emit :attr:`coords_resolved`; LayerManager re-renders
        with the real spotlight rect.
    3b. On timeout (≥3 s) or failure → emit :attr:`resolution_failed`;
        LayerManager shows the manual-click fallback message.

    Signals
    -------
    step_changed(current_index, total):
        Emitted whenever the active step changes.
    task_completed:
        Emitted when the user advances past the final step.
    coords_resolved(step):
        Emitted from the main thread when background resolution succeeds.
    resolution_failed(target):
        Emitted when AT-SPI cannot locate *target* within the timeout.
    """

    step_changed      = pyqtSignal(int, int)       # (index, total)
    task_completed    = pyqtSignal()
    coords_resolved   = pyqtSignal(object)         # Step
    resolution_failed = pyqtSignal(str)            # target name
    _resolve_requested = pyqtSignal(object, str)   # (Step, app_name)
    
    def __init__(self, layer_manager) -> None:
        """
        Parameters
        ----------
        layer_manager:
            Any object exposing ``render_step(step)``, ``clear_all()``, and
            ``show_locating(step)`` / ``show_resolution_failed(target)``.
        """
        super().__init__()
        self._layer_manager = layer_manager
        self._task: Task | None = None
        self._index: int = -1
        self._pending_step_id: int | None = None  # id of the step being resolved

        # ── Background resolution thread ──────────────────────────────
        self._worker = _CoordWorker()
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)

        # Wire worker signals back to main-thread slots
        self._worker.resolved.connect(self._on_worker_resolved)
        self._worker.failed.connect(self._on_worker_failed)

        # Wire the internal signal → worker slot (crosses thread boundary)
        self._resolve_requested.connect(self._worker.resolve)

        self._thread.start()

        # ── Timeout timer (lives on main thread) ─────────────────────
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(_RESOLUTION_TIMEOUT_MS)
        self._timeout_timer.timeout.connect(self._on_resolution_timeout)

    # ------------------------------------------------------------------
    # Task loading
    # ------------------------------------------------------------------

    def load_task(self, path: str) -> None:
        """Load a task from *path* and immediately render the first step."""
        self._task = Task.load_from_file(path)
        self._index = -1
        self.next_step()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def next_step(self) -> None:
        """Advance to the next step, or emit :attr:`task_completed`."""
        if self._task is None:
            return

        next_index = self._index + 1
        if next_index >= len(self._task.steps):
            self._cancel_pending_resolution()
            self._layer_manager.clear_all()
            self.task_completed.emit()
            return

        self._index = next_index
        self._render_current()

    def prev_step(self) -> None:
        """Go back one step and render it.  No-op if already at step 0."""
        if self._task is None or self._index <= 0:
            return
        self._index -= 1
        self._render_current()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def current_step_index(self) -> int:
        """Return the 0-based index of the active step, or ``-1``."""
        return self._index

    def total_steps(self) -> int:
        """Return the total number of steps in the loaded task, or ``0``."""
        return len(self._task.steps) if self._task is not None else 0

    # ------------------------------------------------------------------
    # Internal — rendering & async resolution
    # ------------------------------------------------------------------

    def _render_current(self) -> None:
        """Immediately render the step without coords, then start resolution."""
        if self._task is None:
            return

        self._cancel_pending_resolution()

        step = self._task.steps[self._index]

        # 1. Show locating state immediately (no coords yet)
        print(f"Rendering step {step.id}: {step.target!r} — locating…")
        self._layer_manager.show_locating(step)
        self.step_changed.emit(self._index, len(self._task.steps))

        # 2. Try live resolver first
        if self._resolver_available():
            self._pending_step_id = step.id
            self._timeout_timer.start()
            self._resolve_requested.emit(step, self._task.app)
        else:
            # No resolver — fall back to fake coords
            step_with_fake = self.inject_fake_coords(step)
            if step_with_fake.coords is not None:
                print(f"Rendering step {step.id}: {step.target!r} at {step_with_fake.coords} [fake]")
                self._layer_manager.render_step(step_with_fake)

    def _resolver_available(self) -> bool:
        return _RESOLVER_AVAILABLE and self._task is not None

    def _cancel_pending_resolution(self) -> None:
        """Stop the timeout timer and discard any stale pending resolution."""
        self._timeout_timer.stop()
        self._pending_step_id = None

    # ------------------------------------------------------------------
    # Slots — called on the main thread from the worker thread
    # ------------------------------------------------------------------

    @pyqtSlot(object)
    def _on_worker_resolved(self, step: Step) -> None:
        """Called when AT-SPI successfully resolved coords for *step*."""
        if step.id != self._pending_step_id:
            return  # stale result — user navigated away
        self._cancel_pending_resolution()
        print(f"Resolved step {step.id}: {step.target!r} at {step.coords} [live]")
        self.coords_resolved.emit(step)

    @pyqtSlot(str)
    def _on_worker_failed(self, target: str) -> None:
        """Called when AT-SPI could not find *target*."""
        # Only act if this matches the step we're still waiting on.
        if self._task is None:
            return
        current = self._task.steps[self._index] if self._index >= 0 else None
        if current is None or current.target != target:
            return
        self._cancel_pending_resolution()
        self.resolution_failed.emit(target)

    @pyqtSlot()
    def _on_resolution_timeout(self) -> None:
        """Called 3 s after a resolution was started if it hasn't finished."""
        if self._task is None or self._pending_step_id is None:
            return
        current = self._task.steps[self._index] if self._index >= 0 else None
        if current is None:
            return
        _log.warning("Resolution timed out after %d ms for %r", _RESOLUTION_TIMEOUT_MS, current.target)
        self._pending_step_id = None
        self.resolution_failed.emit(current.target)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Stop the worker thread gracefully.  Call before app exit."""
        self._timeout_timer.stop()
        self._thread.quit()
        self._thread.wait()

    # ------------------------------------------------------------------
    # Smoke-test shim — REMOVE IN PHASE 4
    # ------------------------------------------------------------------

    @staticmethod
    def inject_fake_coords(step: Step) -> Step:
        """Return *step* with fake coords if ``step.coords`` is None.

        .. warning::
            **Temporary shim for smoke-testing.**  Remove in Phase 4 once the
            real coordinate resolver is wired in and validated.
        """
        if step.coords is not None:
            return step
        fake = _FAKE_COORDS.get(step.id)
        if fake is None:
            return step
        return dataclasses.replace(step, coords=fake)
