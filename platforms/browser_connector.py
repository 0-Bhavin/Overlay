"""Browser UI Connector implementation connecting to Chrome/Edge extension via WebSocket.

Runs a local WebSocket bridge server on ws://localhost:8765 to receive DOM state,
highlight elements, and capture user actions from the browser companion extension.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
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
        self._start_server()

    def _start_server(self) -> None:
        """Start WebSocket bridge server in a background thread."""
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            async def serve():
                async with websockets.serve(self._handle_client, self.host, self.port):
                    _log.info("BrowserConnector: WebSocket server running on ws://%s:%d", self.host, self.port)
                    await asyncio.Future()  # Run forever

            try:
                self._loop.run_until_complete(serve())
            except Exception as err:
                _log.error("BrowserConnector server loop error: %s", err)

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
                    msg_type = data.get("type")
                    if msg_type in ("dom_mutated", "user_click"):
                        if msg_type == "user_click":
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
        """
        if not self.active_socket or not self._loop:
            _log.warning("BrowserConnector: No active browser extension connected")
            return []

        req_id = str(uuid.uuid4())
        fut: asyncio.Future = self._loop.create_future()
        self._pending_responses[req_id] = fut

        msg = json.dumps({"type": "get_tree", "req_id": req_id})
        asyncio.run_coroutine_threadsafe(self.active_socket.send(msg), self._loop)

        try:
            res = asyncio.run_coroutine_threadsafe(
                asyncio.wait_for(fut, timeout=timeout), self._loop
            ).result()
            raw_tree = res.get("tree", [])
            # Validate and convert nodes via UINode model
            validated_nodes = []
            for item in raw_tree:
                node = UINode.from_dict(item)
                validated_nodes.append(node.to_dict())
            return validated_nodes
        except Exception as exc:
            _log.warning("BrowserConnector.get_tree timed out or failed: %s", exc)
            self._pending_responses.pop(req_id, None)
            return []

    def highlight(self, element_id: int | str, timeout: float = 2.0) -> bool:
        """Highlight browser element with matching data-ai-overlay-id."""
        if not self.active_socket or not self._loop:
            return False

        req_id = str(uuid.uuid4())
        fut: asyncio.Future = self._loop.create_future()
        self._pending_responses[req_id] = fut

        msg = json.dumps({"type": "highlight", "req_id": req_id, "elementId": str(element_id)})
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
