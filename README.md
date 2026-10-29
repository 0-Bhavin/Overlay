# AI Overlay (`Overlay`)

---

## 1. Summary

**AI Overlay** is a desktop assistant that **teaches users how to do computer tasks by pointing at the screen**. You type a goal such as "how to insert an image in an Excel sheet". Google **Gemini** breaks it into steps. A transparent **PyQt6 overlay** then dims the screen, spotlights the exact control to use, and shows a tooltip. It advances automatically when you click the right thing, and can speak the instructions aloud.

It works in two modes:

| Mode | Target | How elements are found |
|---|---|---|
| **App mode** | Windows desktop apps (Word, Excel, Notepad, ...) | Windows UI Automation through `pywinauto`, plus a cached `ui_dictionary.json` |
| **Website mode** | Any page in Chrome or Edge | A companion **browser extension** extracts a simplified DOM, highlights elements and reports clicks over a local WebSocket (`ws://127.0.0.1:8765`) |

Website mode has the most advanced logic: Gemini builds a **milestone plan** (2 to 6 goal-level milestones). After each batch of steps the app re-reads the page, asks Gemini whether the milestone was met, and generates the next steps, replanning if the page doesn't match expectations. The project plan frames it as a "cross-platform AI UI guidance framework" with one shared core and two connectors (Windows and Browser).

---

## 2. Repository at a Glance

| Item | Detail |
|---|---|
| Project name | AI Overlay (folder `Overlay`) |
| Platform | **Windows** (Linux AT-SPI resolver exists but is a stub and out of scope) |
| Python | 3.13 targeted (per project notes) |
| Entry point | `python main.py` |
| AI provider | Google Gemini (`gemini-2.5-flash`), through the `google-genai` SDK |
| Contributors named in docs | `p4rth-rana314`, Bhavin Prajapati (added the mic and speech feature) |
| Docs describe | Branch `feat/UIDictornary`, last listed commit 23 Jul 2026 |
| License | None found in the zip |

### Project structure

```
Overlay-main/
├── main.py                     # Qt app wiring, mode setup, website verify/replan loop
├── core/
│   ├── UI.py                   # Task input dialog (history, mic, mode, window picker)
│   ├── ai_task_generator.py    # Gemini prompts, JSON schemas, plan/verify calls
│   ├── task_controller.py      # Step navigation + async coordinate resolution
│   ├── step.py / task.py       # Step & Task dataclasses, element lookup fallbacks
│   ├── layer_manager.py        # Orchestrates overlay layers and flashes
│   ├── overlay_window.py       # Frameless transparent window (dim + spotlight)
│   ├── layers/hud_layer.py     # Step dots, back/next, pause
│   ├── layers/tooltip_layer.py # Pointer tooltip + expandable explanation
│   ├── action_watcher.py       # Win32 WinEvent hooks to auto-advance (App mode)
│   ├── completion_toast.py     # "Task complete" celebration
│   ├── tts.py                  # Windows SAPI speech (optional)
│   └── task_history.py         # Recent tasks
├── platforms/
│   ├── ui_connector.py         # Abstract UIConnector + UINode schema
│   ├── browser_connector.py    # WebSocket server bridging to the extension
│   ├── windows_connector.py    # Windows implementation
│   ├── uia_resolver.py         # pywinauto UIA lookup (cache, strategies, retry)
│   ├── hybrid_resolver.py      # Routes to UIA (vision fallback disabled)
│   ├── atspy_resolver.py       # Linux stub
│   └── getwindow.py            # get_resolver() factory
├── extension/                  # Chrome/Edge MV3 extension (4 scripts + manifest)
├── tasks/                      # Sample generated tasks, DOM snapshot, history, logs
├── ui_dictionary.json          # Cached element locators for Word and Excel
├── tests/ + test_*.py          # 2 unit-test files + manual WebSocket/resolver scripts
├── docs/                       # Project plan, guardrails, status notes
├── CLAUDE.md, .claude/         # AI-coding-assistant guidance and hooks
└── websocket_diagnostic.html   # Browser page to test the WebSocket server
```

---

## 3. Tech Stack

| Layer | Technology |
|---|---|
| Desktop UI / overlay | PyQt6 6.7.0 (frameless, transparent, always-on-top window; custom-painted layers) |
| AI | Google Gemini `gemini-2.5-flash` via `google-genai`, JSON-mode with response schemas |
| Windows automation | `pywinauto` 0.6.8 (UIA backend), `ctypes` Win32 `SetWinEventHook` |
| Browser bridge | `websockets` (asyncio server on a background thread); Chrome MV3 extension (service worker, content scripts, `MutationObserver`) |
| Speech | Windows SAPI through `pywin32` (optional); `speechrecognition` + `pyaudio` for mic input (optional) |
| Screen utilities | `screeninfo`, `mss`, `Pillow` |
| Config | `python-dotenv` (`GEMINI_API_KEY` in `.env`), `keyboard` for hotkeys |
| Data | JSON files for tasks, history, DOM snapshots and the UI dictionary |
| Testing | `unittest` plus manual scripts |

---

## 4. How It Works

**Shared flow**

1. The user enters a goal in `TaskInputDialog` and picks App or Website mode. Past tasks can be reused, and a microphone button supports voice input.
2. Gemini generates a task as JSON steps.
3. `TaskController` resolves each step's element to screen coordinates in a background worker thread.
4. `LayerManager` dims the screen, draws the spotlight and tooltip, and `TTSEngine` can speak the instruction.
5. When the user performs the action, a flash confirms it and the next step starts. A HUD allows back, next, pause and jumping to a step.

**App mode.** Element coordinates come from `pywinauto` UIA lookups, with `ui_dictionary.json` giving fast cached locators for Word and Excel. `ActionWatcher` listens for Windows accessibility events (menus, dialogs, focus) to detect that the user acted, with no polling or mouse hooks.

**Website mode**
1. The extension extracts a filtered DOM and sends it over WebSocket.
2. `generate_plan_and_steps` returns milestones plus steps for milestone 0 in a single Gemini call.
3. The extension highlights the element, dims the page and shows a tooltip and progress bar.
4. The extension reports clicks (`user_click`), page changes (`page_navigated`) and DOM changes (`dom_mutated`).
5. When steps run out, `_SubTaskWorker` fetches the current DOM and checks a cheap heuristic (URL or text hints). It then calls `verify_and_generate`, which decides whether the milestone was met and returns the next steps, possibly with a revised plan.
6. Generated steps whose targets aren't in the DOM are dropped, and attempts per milestone and replans are capped.

**Common UI schema (`UINode`):** `id, type, text, role, enabled, visible, bounds{x,y,width,height}` for both platforms.

---

## 5. Key Metrics

| Metric | Value |
|---|---|
| Files in zip | 48 |
| Python files / lines | 28 / about 6,200 (incl. about 360 lines of tests) |
| JavaScript lines (extension) | about 1,590 across 4 scripts |
| Docs / notes | about 880 lines across 5 Markdown files |
| Operating modes | 2 (App, Website) |
| Platform connectors | 3 files (Windows UIA, Browser, Linux stub) |
| WebSocket port | 8765 (bound to 127.0.0.1) |
| Gemini model | `gemini-2.5-flash` |
| Milestones per plan | 1 (single-page task) or 2 to 6 |
| Gemini retries per call | 1 |
| WebSocket message types seen | 7 (`tree_response`, `highlight_response`, `clear_overlay_response`, `user_click`, `page_navigated`, `dom_mutated`, `heartbeat`) |
| Cached app dictionary | 2 apps: Word (17 entries), Excel (12 entries) |
| Task history | 20 entries (Sep to Oct 2026) in the sample data |
| Sample DOM snapshot | 105 nodes (an earlier log shows 87) |
| Automated unit tests | 6 (3 in `test_task_and_step.py`, 3 in `test_ui_connector.py`) |
| Manual test scripts | 5 |

---

## 6. Application Use Cases

- **Software onboarding and training.** Guide new hires through internal tools, ERP/CRM screens or cloud consoles (the sample data walks through creating a MongoDB Atlas cluster).
- **Digital literacy and accessibility.** Step-by-step visual and spoken help for older adults or less technical users, in Word, Excel and common websites.
- **Customer support.** "Show me how" overlays instead of long screenshot-based instructions.
- **Interactive tutorials** for products without writing tutorials by hand, since Gemini generates them from the live UI.
- **Research platform.** A base for experiments in AI-guided UI automation, DOM simplification and human-in-the-loop guidance. It only guides the user and does not click for them.

---

## 7. Setup (from the project docs)

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
echo GEMINI_API_KEY=your_key_here > .env
python main.py
```

Website mode also needs the extension (`extension/`) loaded unpacked in Chrome or Edge. Optional extras are `pywin32` for speech and `speechrecognition` with `pyaudio` for voice input. Tests: `python -m unittest discover tests`.

---
