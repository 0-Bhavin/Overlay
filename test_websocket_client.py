#!/usr/bin/env python3
"""
Test WebSocket client to verify our server works
"""

import asyncio
import websockets
import json

async def test_connection():
    uri = "ws://127.0.0.1:8765"
    print(f"Connecting to {uri}...")

    try:
        async with websockets.connect(uri) as websocket:
            print("Connected!")

            # Send a test message
            test_msg = {
                "type": "get_tree",
                "req_id": "test123"
            }
            await websocket.send(json.dumps(test_msg))
            print("Sent get_tree request")

            # Wait for response
            response = await websocket.recv()
            print(f"Received: {response}")

    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())