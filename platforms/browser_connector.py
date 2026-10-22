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
from collections.abc import Callable
from typing import Any

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
        self._server: Any = None  # WebSocket server object
        self._server_ready: threading.Event = threading.Event()
        self._shutdown_requested = threading.Event()
        self._shutdown_event: asyncio.Event | None = None
        self._last_viewport_offset: dict[str, int] = {"x": 0, "y": 0}  # screen-space offset of browser viewport
        self._last_url: str = ""
        self._start_server()

    def _start_server(self) -> None:
        """Start WebSocket bridge server in a background thread."""
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._shutdown_event = asyncio.Event()

            async def serve():
                while not self._shutdown_requested.is_set():
                    try:
                        self._server = await websockets.serve(
                            self._handle_client, self.host, self.port,
                            reuse_address=True
                        )
                        _log.info("BrowserConnector: WebSocket server running on ws://%s:%d", self.host, self.port)
                        self._server_ready.set()
                        await self._shutdown_event.wait()
                        break
                    except OSError as err:
                        if err.winerror == 10048:  # Address already in use
                            _log.warning("Port %d is in use, retrying in 1 second...", self.port)
                            await asyncio.sleep(1)
                            continue
                        else:
                            _log.error("BrowserConnector server loop error: %s", err)
                            await asyncio.sleep(1)
                    except Exception as err:
                        if self._shutdown_requested.is_set():
                            break
                        _log.error("BrowserConnector server loop error: %s", err)
                        await asyncio.sleep(1)

            try:
                self._loop.run_until_complete(serve())
            except Exception as err:
                _log.error("BrowserConnector server loop error: %s", err)
                self._server_ready.set()
            finally:
                self._loop.close()

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

                    # Trigger registered callbacks on DOM mutations, clicks,
                    # and completed page navigations.
                    msg_type = data.get("action")
                    if not msg_type:
                        msg_type = {
                            "dom_mutated": "DOM_MUTATED",
                            "user_click": "USER_CLICK",
                            "user_input": "USER_INPUT",
                            "page_navigated": "PAGE_NAVIGATED",
                        }.get(data.get("type"))
                    if msg_type in ("DOM_MUTATED", "USER_CLICK", "USER_INPUT", "PAGE_NAVIGATED"):
                        if msg_type == "USER_CLICK":
                            self._click_events.append(data)
                        callback_data = {
                            **data,
                            "type": {
                                "DOM_MUTATED": "dom_mutated",
                                "USER_CLICK": "user_click",
                                "USER_INPUT": "user_input",
                                "PAGE_NAVIGATED": "page_navigated",
                            }[msg_type],
                        }
                        for cb in self._change_callbacks:
                            try:
                                cb(callback_data)
                            except Exception as err:
                                _log.warning("Error in change callback: %s", err)
                except Exception as parse_err:
                    _log.error("Failed to parse WebSocket message: %s", parse_err)
        except websockets.exceptions.ConnectionClosed as exc:
            _log.info("BrowserConnector: Extension disconnected (%s)", exc)
        except Exception as exc:
            _log.warning("BrowserConnector: Extension handler stopped: %s", exc)
        finally:
            # Clean up pending responses for this connection
            if self.active_socket == websocket:
                self.active_socket = None
                # Cancel any pending futures since the connection is gone
                for req_id, fut in list(self._pending_responses.items()):
                    if not fut.done():
                        fut.cancel()
                    self._pending_responses.pop(req_id, None)

    def get_tree(self, timeout: float = 3.0) -> list[dict[str, Any]]:
        """Fetch current simplified DOM tree JSON from the active browser tab.

        Returns list of UINode dictionaries conforming to common UI schema.
        Bounds are viewport-relative (not screen-space) — the extension uses
        getBoundingClientRect() directly for rendering, so no conversion needed.
        """
        # Wait for the server to be ready (with a fixed timeout of 1.0 second)
        if not self._server_ready.wait(timeout=1.0):
            _log.warning("BrowserConnector: WebSocket server not ready after 1.0s")
            return []

        # Wait for the extension to connect (active_socket to be set) with the passed timeout
        timeout_seconds = timeout
        end_time = time.time() + timeout_seconds
        while time.time() < end_time:
            if self.active_socket is not None and self._loop is not None and self._loop.is_running():
                break
            time.sleep(0.1)
        else:
            _log.warning("BrowserConnector: No active browser extension connected after waiting")
            return []

        socket = self.active_socket
        loop = self._loop
        if socket is None or loop is None or not loop.is_running():
            _log.warning("BrowserConnector: Extension disconnected before GET_TREE send")
            return []

        print(f"[BrowserConnector.get_tree] Socket active=True, loop=True, running=True")

        req_id = str(uuid.uuid4())
        fut: asyncio.Future = loop.create_future()
        self._pending_responses[req_id] = fut

        msg = json.dumps({"action": "GET_TREE", "req_id": req_id})
        asyncio.run_coroutine_threadsafe(socket.send(msg), loop)

        try:
            res = asyncio.run_coroutine_threadsafe(
                asyncio.wait_for(fut, timeout=timeout), loop
            ).result()
            raw_tree = res.get("tree", [])
            self._last_url = str(res.get("url") or self._last_url)
            self._last_viewport_offset = res.get("viewportOffset") or self._last_viewport_offset
            print(f"[BrowserConnector.get_tree] Received {len(raw_tree)} nodes from {self._last_url}")
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

    @property
    def is_connected(self) -> bool:
        """Whether the extension currently has an open WebSocket connection."""
        return bool(
            self.active_socket is not None
            and self._loop is not None
            and self._loop.is_running()
        )

    @property
    def current_url(self) -> str:
        """Return the URL reported by the most recent DOM extraction."""
        return self._last_url

    def observe_changes(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register callback for DOM mutations or user clicks."""
        if callback not in self._change_callbacks:
            self._change_callbacks.append(callback)

    def shutdown(self) -> None:
        """Shutdown the WebSocket server and clean up resources."""
        _log.info("BrowserConnector: Shutting down WebSocket server")
        self._shutdown_requested.set()
        if self._loop and self._loop.is_running():
            # Let the server coroutine finish naturally before closing the loop.
            future = asyncio.run_coroutine_threadsafe(self._shutdown_async(), self._loop)
            try:
                future.result(timeout=3.0)
            except Exception as exc:
                _log.warning("BrowserConnector shutdown did not complete cleanly: %s", exc)
            if self._server_thread and self._server_thread.is_alive():
                self._server_thread.join(timeout=3.0)
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

            # Close the server if it exists
            if self._server:
                self._server.close()
                await self._server.wait_closed()
                self._server = None

            # Wake the server coroutine so run_until_complete() can return.
            if self._shutdown_event is not None:
                self._shutdown_event.set()

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
