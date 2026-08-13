"""Unit tests for UIConnector abstraction, UINode schema, and BrowserConnector."""

import sys
import time
import unittest
from pathlib import Path

# Ensure project root directory is in sys.path when running script directly from tests/ folder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from platforms.ui_connector import UIConnector, UINode
from platforms.windows_connector import WindowsConnector
from platforms.browser_connector import BrowserConnector


class TestUIConnector(unittest.TestCase):

    def test_ui_node_serialization(self):
        node = UINode(
            id=42,
            type="button",
            text="Login",
            role="button",
            enabled=True,
            visible=True,
            bounds={"x": 100, "y": 200, "width": 80, "height": 30}
        )
        data = node.to_dict()
        self.assertEqual(data["id"], 42)
        self.assertEqual(data["type"], "button")
        self.assertEqual(data["bounds"]["x"], 100)

        # Deserialization test
        reconstructed = UINode.from_dict(data)
        self.assertEqual(reconstructed.id, 42)
        self.assertEqual(reconstructed.type, "button")
        self.assertEqual(reconstructed.bounds["width"], 80)

    def test_windows_connector_interface(self):
        connector = WindowsConnector()
        self.assertIsInstance(connector, UIConnector)
        tree = connector.get_tree()
        self.assertIsInstance(tree, list)

    def test_browser_connector_interface(self):
        connector = BrowserConnector(port=8769)  # Use test port
        self.assertIsInstance(connector, UIConnector)
        tree = connector.get_tree(timeout=0.2)
        self.assertIsInstance(tree, list)
        self.assertEqual(len(tree), 0)  # Empty when extension not connected


if __name__ == "__main__":
    unittest.main()
