#!/usr/bin/env python3
"""
Simple test to verify WebSocket server can start
"""

import asyncio
import websockets
import threading
import time
import logging

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8765

async def handle_client(websocket):
    _log.info("Client connected")
    try:
        async for message in websocket:
            _log.info(f"Received: {message}")
            # Echo back for testing
            await websocket.send(message)
    except websockets.exceptions.ConnectionClosed:
        _log.info("Client disconnected")

async def start_server():
    try:
        async with websockets.serve(handle_client, HOST, PORT):
            _log.info(f"WebSocket server started on ws://{HOST}:{PORT}")
            await asyncio.Future()  # Run forever
    except Exception as e:
        _log.error(f"Server failed to start: {e}")
        raise

def run_server():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(start_server())
    except Exception as e:
        _log.error(f"Server thread error: {e}")

if __name__ == "__main__":
    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Give it a moment to start
    time.sleep(2)

    # Test connection
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex((HOST, PORT))
    if result == 0:
        print('SUCCESS: Port is open and accepting connections')
    else:
        print(f'FAILED: Port is not open: {result}')

    # Keep alive for a bit
    time.sleep(5)
    print("Test completed")