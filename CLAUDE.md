# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file with your Gemini API key
echo "GEMINI_API_KEY=your_key_here" > .env

# Run the application
python main.py
```

**Optional dependencies** (not in requirements.txt):
```bash
# Voice input (feature 1.6)
pip install speechrecognition pyaudio

# TTS (feature 1.5)
pip install pywin32
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    main.py                              │
│         TaskInputDialog → TaskController                │
└─────────────────────┬───────────────────────────────────┘
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
┌───────────────┐           ┌─────────────────┐
│ LayerManager  │           │ ActionWatcher   │
│  (PyQt6)     │           │ (mouse hooks)   │
└───────┬───────┘           └─────────────────┘
        ▼
┌───────────────────┐     ┌─────────────────────────────────┐
│  HUD Layer        │     │      platforms/                  │
│  Tooltip Layer    │     │  ui_connector.py (abstract)    │
└───────────────────┘     │  windows_connector.py           │
                          │  browser_connector.py           │
                          └────────────┬────────────────────┘
                                       │ WebSocket (port 8765)
                          ┌────────────▼────────────────────┐
                          │   extension/                    │
                          │   background.js → content.js    │
                          │   dom_extractor.js              │
                          └─────────────────────────────────┘
```

### Two Operating Modes

- **App mode**: Uses `WindowsConnector` + `UIAResolver` (pywinauto/UIA) to locate UI elements in Windows desktop applications.
- **Website mode**: Uses `BrowserConnector` (WebSocket) + browser extension to extract DOM and highlight elements.

### Core Data Flow

1. User enters task description in `TaskInputDialog`
2. `GeminiTaskGenerator` calls Gemini API to decompose task into steps
3. `TaskController` drives step-by-step progression
4. For each step:
   - Background `_CoordWorker` resolves element coordinates via the appropriate connector
   - `LayerManager` renders spotlight + tooltip
   - `ActionWatcher` waits for the user's click
   - On click: flash animation, advance to next step

### Key Components

| Component | Purpose |
|-----------|---------|
| `core/task_controller.py` | Step navigation, background coord resolution via QThread |
| `core/ai_task_generator.py` | Gemini API calls for task decomposition (two modes: app/website) |
| `core/layer_manager.py` | PyQt6 overlay rendering (spotlight, dim, tooltip, HUD) |
| `core/action_watcher.py` | Win32 mouse hook to detect clicks in target regions |
| `platforms/ui_connector.py` | Abstract base class + `UINode` dataclass (common schema) |
| `platforms/browser_connector.py` | WebSocket server (port 8765) bridging to browser extension |
| `extension/content.js` | DOM extraction, element highlighting, click tracking |
| `extension/dom_extractor.js` | Simplified DOM traversal per filtering rules |

### UINode Common Schema

All platforms produce nodes conforming to this structure:
```python
{"id": 42, "type": "button", "text": "Login", "role": "button",
 "enabled": True, "visible": True, "bounds": {"x": 400, "y": 280, "width": 120, "height": 40}}
```

### Browser Extension Loading

To test in Chrome/Edge:
1. Go to `chrome://extensions/`
2. Enable "Developer mode"
3. Click "Load unpacked" and select the `extension/` directory
4. Open a webpage and ensure the extension connects (check browser console for `[AI Overlay Extension] Connected to desktop bridge server`)

## Project Status

The project is on branch `DOM`. Phase 1 (Common UI Model) and Phase 2 (Browser Connector/DOM extraction) are complete. Remaining work:
- Phase 3: Deeper integration of platform connectors with UIConnector interface
- Phase 4: Incremental DOM updates via MutationObserver
- Phase 5: Context awareness (correct/wrong action detection)
