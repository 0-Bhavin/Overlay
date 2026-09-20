#!/usr/bin/env python3
"""
Test the BrowserConnector class to see if it can establish connection
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'platforms'))

from browser_connector import BrowserConnector
import time

def test_browser_connector():
    print("Testing BrowserConnector...")

    # Create connector instance
    connector = BrowserConnector()

    # Wait a bit for server to start
    print("Waiting for server to be ready...")
    time.sleep(2)

    # Check if server ready
    if connector._server_ready.is_set():
        print("[OK] Server ready flag is set")
    else:
        print("[FAIL] Server ready flag is NOT set")

    # Check if we have a loop
    if connector._loop is not None:
        print("[OK] Event loop is set")
    else:
        print("[FAIL] Event loop is NOT set")

    # Check if we have active socket
    if connector.active_socket is not None:
        print("[OK] Active socket is set")
    else:
        print("[FAIL] Active socket is NOT set (waiting for extension)")

    # Try to get tree (this will fail without extension but should not crash)
    try:
        print("Attempting to get DOM tree...")
        tree = connector.get_tree(timeout=2.0)
        print(f"[OK] get_tree returned {len(tree)} nodes")
    except Exception as e:
        print(f"[FAIL] get_tree failed: {e}")

    # Clean up
    print("Shutting down...")
    try:
        connector._thread.quit()
        connector._thread.wait()
    except:
        pass

    print("Test completed")

if __name__ == "__main__":
    test_browser_connector()