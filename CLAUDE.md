# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

1. Clone the repository and navigate to the root directory.
2. Create a virtual environment (optional but recommended):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create a `.env` file with your Gemini API key:
   ```bash
   echo "GEMINI_API_KEY=your_key_here" > .env
   ```
   (Optional: For voice input or TTS, install additional dependencies as noted in the existing CLAUDE.md.)

## Running the Application

- Start the application:
  ```bash
  python main.py
  ```
- The application will launch a task input dialog. Enter a task description to generate step-by-step guidance.
- The overlay will appear in either **App mode** (for Windows desktop applications) or **Website mode** (for browser-based tasks via extension).

## Running Tests

- Run all unit tests:
  ```bash
  python -m unittest discover tests
  ```
- Run a specific test file:
  ```bash
  python -m unittest tests.test_task_and_step
  ```
- Note: Some tests (e.g., `test_browser_connector.py`, `test_websocket.py`) are designed to be run manually and may require a running WebSocket server or browser extension.

## Code Architecture

### High-Level Structure

The application follows a modular architecture with distinct layers:

1. **Entry Point** (`main.py`):
   - Initializes Qt application, TTS engine, browser connector, overlay window, layer manager, task controller, and action watcher.
   - Sets up signal-slot connections for coordination between components.

2. **Core Components** (`core/` directory):
   - `task_controller.py`: Manages step-by-step task progression, asynchronous coordinate resolution, and step navigation.
   - `ai_task_generator.py`: Calls Gemini API (or local Ollama) to decompose user tasks into steps.
   - `layer_manager.py`: Renders PyQt6 overlays (spotlight, dim, tooltip, HUD) and manages visual state.
   - `action_watcher.py`: Uses Win32 mouse hooks to detect clicks in target regions for App mode.
   - `overlay_window.py`: Frameless, transparent Qt window that hosts the overlay layers.
   - `step.py` and `task.py`: Data models for individual steps and entire tasks.
   - `ui.py`: Task input dialog for user interaction.

3. **Platform Connectors** (`platforms/` directory):
   - `ui_connector.py`: Abstract base class defining the `UINode` common schema used by all platforms.
   - `browser_connector.py`: WebSocket server (port 8765) that bridges to the browser extension; handles DOM extraction and element highlighting.
   - `uia_resolver.py` and `atspy_resolver.py`: Platform-specific resolvers for Windows UI Automation and Linux AT-SPI (currently Windows-only).
   - `getwindow.py`: Utility for retrieving window handles and bounds.
   - `hybrid_resolver.py`: Combines visual and accessibility data for robust element detection.

4. **Browser Extension** (`extension/` directory):
   - `content.js`: Injected script that communicates with the desktop WebSocket server, highlights elements, and reports user interactions.
   - `dom_extractor.js`: Simplified DOM traversal that extracts interactive elements based on filtering rules.

### Data Flow

1. User enters a task description in `TaskInputDialog`.
2. `GeminiTaskGenerator` calls the Gemini API to generate a JSON task description (list of steps).
3. `TaskController` loads the task and drives progression:
   - For each step, it requests coordinate resolution via the appropriate platform connector.
   - In App mode: Uses `UIAResolver` (via `pywinauto`) to locate element bounds.
   - In Website mode: Uses `BrowserConnector` to query the extension for element coordinates.
4. `LayerManager` renders a spotlight over the target element and a tooltip with instructions.
5. `ActionWatcher` (App mode) or browser extension (Website mode) waits for the user to click the target.
6. On successful click:
   - App mode: `ActionWatcher` detects the click and signals advancement.
   - Website mode: Extension sends a click event via WebSocket, validated against the target element.
7. A flash animation confirms completion, and the controller advances to the next step.

### Key Concepts

- **Two Operating Modes**:
  - **App mode**: For traditional Windows desktop applications, using UI Automation via `pywinauto`.
  - **Website mode**: For web applications, using a browser extension to extract DOM and interact with page elements.

- **UINode Common Schema**: All platforms produce elements conforming to:
  ```python
  {"id": int, "type": str, "text": str, "role": str, "enabled": bool, "visible": bool, "bounds": {"x": int, "y": int, "width": int, "height": int}}
  ```

- **Extension Communication**: The browser extension connects to `ws://localhost:8765` and exchanges messages for:
  - DOM tree requests and responses.
  - Element highlighting and tooltip display.
  - Click event reporting and DOM mutation notifications.
  - Step progress updates (for progress bar).
  - Navigation detection (to handle page changes).

## Common Development Tasks

- **Adding a new platform connector**: Implement a class that adheres to the `UIConnector` interface in `platforms/ui_connector.py`, then integrate it into the resolver selection logic in `task_controller.py`.
- **Modifying overlay visuals**: Edit the QSS styles or painting methods in `core/layers/` (e.g., `hud_layer.py`, `tooltip_layer.py`).
- **Updating step validation logic**: Adjust the matching criteria in `main.py` for website mode clicks (e.g., tolerance for text matching, element ID vs. text fallback).
- **Debugging WebSocket communication**: Use `websocket_diagnostic.html` (open in browser) to test the WebSocket server independently.

## Notes

- The project is currently on the `main` branch, with the DOM branch merged. Active work focuses on deeper platform integration and incremental DOM updates.
- When modifying code, run `graphify update .` (if the graphify skill is available) to keep the knowledge graph current.
- Always test both App mode and Website mode when changing core interaction logic.

Co-Authored-By: Claude Code <noreply@anthropic.com>