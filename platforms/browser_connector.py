"""Browser UI Connector implementation connecting to Chrome/Edge extension via WebSocket.

Runs a local WebSocket bridge server on ws://localhost:8765 to receive DOM state,
highlight elements, and capture user actions from the browser companion extension.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from typing import Any, Callable

import websockets

from platforms.ui_connector import UIConnector, UINode

_log = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8765


class BrowserConnector(UIConnector):
    """Browser platform UI connector communicating with the Chrome/Edge extension."""

    def __init__(self, host: str = HOST, port: int = PORT) -> None:
        self.host = host
        self.port = port
        self.active_socket: websockets.WebSocketServerProtocol | None = None
        self._pending_responses: dict[str, asyncio.Future] = {}
        self._change_callbacks: list[Callable[[dict[str, Any]], None]] = []
        self._click_events: list[dict[str, Any]] = []
        self._server_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server_ready: threading.Event = threading.Event()
        self._last_viewport_offset: dict[str, int] = {"x": 0, "y": 0}  # screen-space offset of browser viewport
        self._start_server()

    def _start_server(self) -> None:
        """Start WebSocket bridge server in a background thread."""
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            async def serve():
                try:
                    async with websockets.serve(self._handle_client, self.host, self.port):
                        _log.info("BrowserConnector: WebSocket server running on ws://%s:%d", self.host, self.port)
                        self._server_ready.set()
                        await asyncio.Future()  # Run forever
                except Exception as err:
                    _log.error("BrowserConnector server loop error: %s", err)
                    self._server_ready.set()

            try:
                self._loop.run_until_complete(serve())
            except Exception as err:
                _log.error("BrowserConnector server loop error: %s", err)
                self._server_ready.set()

        self._server_thread = threading.Thread(target=run_loop, daemon=True)
        self._server_thread.start()

    async def _handle_client(self, websocket: Any, *args: Any) -> None:
        """Handle incoming WebSocket connections from Chrome extension background worker."""
        self.active_socket = websocket
        _log.info("BrowserConnector: Extension connected")
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    req_id = data.get("req_id")
                    if req_id and req_id in self._pending_responses:
                        fut = self._pending_responses.pop(req_id)
                        if not fut.done():
                            fut.set_result(data)

                    # Trigger registered callbacks on DOM mutations or user clicks
                    msg_type = data.get("action")
                    if msg_type in ("DOM_MUTATED", "USER_CLICK"):
                        if msg_type == "USER_CLICK":
                            self._click_events.append(data)
                        for cb in self._change_callbacks:
                            try:
                                cb(data)
                            except Exception as err:
                                _log.warning("Error in change callback: %s", err)
                except Exception as parse_err:
                    _log.error("Failed to parse WebSocket message: %s", parse_err)
        except websockets.exceptions.ConnectionClosed:
            _log.info("BrowserConnector: Extension disconnected")
        finally:
            if self.active_socket == websocket:
                self.active_socket = None

    def get_tree(self, timeout: float = 3.0) -> list[dict[str, Any]]:
        """Fetch current simplified DOM tree JSON from the active browser tab.

        Returns list of UINode dictionaries conforming to common UI schema.
        Bounds are viewport-relative (not screen-space) — the extension uses
        getBoundingClientRect() directly for rendering, so no conversion needed.
        """
        # Wait for the server to be ready (with a timeout)
        if not self._server_ready.wait(timeout=1.0):
            _log.warning("BrowserConnector: WebSocket server not ready after 1.0s")
            return []

        # Wait for the extension to connect (active_socket to be set) with a timeout
        timeout_seconds = timeout
        end_time = time.time() + timeout_seconds
        while time.time() < end_time:
            if self.active_socket is not None and self._loop is not None and self._loop.is_running():
                break
            time.sleep(0.1)
        else:
            _log.warning("BrowserConnector: No active browser extension connected after waiting")
            return []

        print(f"[BrowserConnector.get_tree] Socket active={self.active_socket is not None}, loop={self._loop is not None}, running={self._loop.is_running() if self._loop else False}")

        req_id = str(uuid.uuid4())
        fut: asyncio.Future = self._loop.create_future()
        self._pending_responses[req_id] = fut

        msg = json.dumps({"action": "GET_TREE", "req_id": req_id})
        asyncio.run_coroutine_threadsafe(self.active_socket.send(msg), self._loop)

        try:
            res = asyncio.run_coroutine_threadsafe(
                asyncio.wait_for(fut, timeout=timeout), self._loop
            ).result()
            raw_tree = res.get("tree", [])
            print(f"[BrowserConnector.get_tree] Received {len(raw_tree)} nodes")
            # Return nodes with viewport-relative bounds (no screen-space conversion)
            validated_nodes = []
            for item in raw_tree:
                node = UINode.from_dict(item)
                validated_nodes.append(node.to_dict())
            return validated_nodes
        except Exception as exc:
            print(f"[BrowserConnector.get_tree] Exception: {exc}")
            _log.warning("BrowserConnector.get_tree timed out or failed: %s", exc)
            self._pending_responses.pop(req_id, None)
            return []

    def highlight(self, element_id: int | str | None = None, tooltip: str = "", target: str = "", timeout: float = 2.0) -> bool:
        """Highlight browser element with matching data-ai-overlay-id or target text.

        The extension renders the overlay (highlight ring, dim, tooltip) directly
        in the page using getBoundingClientRect().
        """
        if not self.active_socket or not self._loop or not self._loop.is_running():
            return False

        req_id = str(uuid.uuid4())
        fut: asyncio.Future = self._loop.create_future()
        self._pending_responses[req_id] = fut

        payload = {
            "action": "HIGHLIGHT",
            "req_id": req_id,
            "elementId": str(element_id) if element_id is not None else "",
            "target": target,
        }
        if tooltip:
            payload["tooltip"] = tooltip
        msg = json.dumps(payload)
        asyncio.run_coroutine_threadsafe(self.active_socket.send(msg), self._loop)

        try:
            res = asyncio.run_coroutine_threadsafe(
                asyncio.wait_for(fut, timeout=timeout), self._loop
            ).result()
            return bool(res.get("success", False))
        except Exception as exc:
            _log.warning("BrowserConnector.highlight failed: %s", exc)
            self._pending_responses.pop(req_id, None)
            return False

    def clear_overlay(self, timeout: float = 2.0) -> bool:
        """Clear all in-page overlay elements (highlight, dim, tooltip)."""
        if not self.active_socket or not self._loop or not self._loop.is_running():
            return False

        req_id = str(uuid.uuid4())
        fut: asyncio.Future = self._loop.create_future()
        self._pending_responses[req_id] = fut

        msg = json.dumps({"action": "clear_overlay", "req_id": req_id})
        asyncio.run_coroutine_threadsafe(self.active_socket.send(msg), self._loop)

        try:
            res = asyncio.run_coroutine_threadsafe(
                asyncio.wait_for(fut, timeout=timeout), self._loop
            ).result()
            return bool(res.get("success", False))
        except Exception as exc:
            _log.warning("BrowserConnector.clear_overlay failed: %s", exc)
            self._pending_responses.pop(req_id, None)
            return False

    def wait_for_click(self, element_id: int | str, timeout: float = 10.0) -> bool:
        """Wait for click event on target browser element ID."""
        target_str = str(element_id)
        start_count = len(self._click_events)
        loop_interval = 0.1
        elapsed = 0.0

        while elapsed < timeout:
            if len(self._click_events) > start_count:
                for evt in self._click_events[start_count:]:
                    if str(evt.get("elementId")) == target_str:
                        return True
            threading.Event().wait(loop_interval)
            elapsed += loop_interval

        return False

    def observe_changes(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register callback for DOM mutations or user clicks."""
        self._change_callbacks.append(callback)

    def shutdown(self) -> None:
        """Shutdown the WebSocket server and clean up resources."""
        _log.info("BrowserConnector: Shutting down WebSocket server")
        if self._loop and self._loop.is_running():
            # Schedule the cleanup coroutine to run in the event loop
            asyncio.run_coroutine_threadsafe(self._shutdown_async(), self._loop)
        else:
            # If loop isn't running, try to stop the thread gracefully
            self._server_ready.set()  # Unblock any waiting threads
            if self._server_thread and self._server_thread.is_alive():
                self._server_thread.join(timeout=2.0)

    async def _shutdown_async(self) -> None:
        """Async shutdown helper to close WebSocket connections."""
        try:
            # Close all active connections
            if self.active_socket:
                await self.active_socket.close()
                self.active_socket = None

            # Stop the event loop
            if self._loop and self._loop.is_running():
                self._loop.stop()

        except Exception as exc:
            _log.warning("Error during BrowserConnector shutdown: %s", exc)

    def send_custom_message(self, message: dict[str, Any]) -> bool:
        """Send a custom message to the browser extension.

        Args:
            message: Dictionary to send as JSON message

        Returns:
            True if message was sent successfully, False otherwise
        """
        if not self.active_socket or not self._loop or not self._loop.is_running():
            _log.warning("BrowserConnector: No active connection to send custom message")
            return False

        try:
            msg = json.dumps(message)
            asyncio.run_coroutine_threadsafe(self.active_socket.send(msg), self._loop)
            return True
        except Exception as exc:
            _log.warning("BrowserConnector.send_custom_message failed: %s", exc)
            return False
