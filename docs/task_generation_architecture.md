# Task Generation and Highlighting Architecture

This document describes the website-mode pipeline from the initial user request through DOM extraction, task generation, sub-task regeneration, and browser highlighting.

## High-level flow

```mermaid
flowchart TD
    A[User enters task in TaskInputDialog] --> B[Website mode selected]
    B --> C[BrowserConnector requests DOM tree]
    C --> D[Extension background sends GET_TREE to active tab]
    D --> E[content.js calls dom_extractor.js]
    E --> F[DOM snapshot returned to Python]
    F --> G[GeminiTaskGenerator generates task JSON]
    F[DOM snapshot returned to Python] --> G[Gemini Call 1 generates milestones and milestone 0 steps]
    G --> H[tasks/plan.json and tasks/sub_task.json written]
    H --> I[tasks/dom_snapshot.json written]
    I --> J[TaskController loads task]
    J --> K[Step.from_dict resolves element from DOM snapshot]
    K --> L[BrowserConnector sends HIGHLIGHT]
    L --> M[content.js highlights target element]
```

## Main components

| Component | File | Responsibility |
|---|---|---|
| Task input UI | `core/UI.py` | Captures user query, target app/URL, fetches initial DOM, starts generation. |
| Task generator | `core/ai_task_generator.py` | Uses Gemini structured output for initial milestone plans, combined verification/step generation, and app-mode tasks. |
| Task model | `core/task.py` | Loads task JSON and DOM snapshot from disk. |
| Step model | `core/step.py` | Converts generated step JSON into runtime `Step` objects and resolves DOM element IDs/coords. |
| Controller | `core/task_controller.py` | Drives step progression and emits resolved steps. |
| Browser bridge | `platforms/browser_connector.py` | Runs WebSocket server on `ws://127.0.0.1:8765`; exchanges DOM, click, navigation, and highlight messages. |
| Extension background | `extension/background.js` | Maintains WebSocket client connection to Python and forwards messages to active browser tab. |
| Extension content script | `extension/content.js` | Handles DOM extraction requests, click events, navigation/mutation reporting, and page overlay rendering. |
| DOM extractor | `extension/dom_extractor.js` | Traverses the live page and returns simplified interactive/structural UI nodes. |

## Initial task generation

```mermaid
sequenceDiagram
    participant User
    participant UI as TaskInputDialog
    participant BC as BrowserConnector
    participant BG as extension/background.js
    participant CS as extension/content.js
    participant DOM as dom_extractor.js
    participant AI as GeminiTaskGenerator
    participant FS as tasks/*.json
    participant TC as TaskController

    User->>UI: Enter website task
    UI->>BC: get_tree()
    BC->>BG: GET_TREE over WebSocket
    BG->>CS: chrome.tabs.sendMessage(GET_TREE)
    CS->>DOM: extractSimplifiedDOM()
    DOM-->>CS: UINode array
    CS-->>BG: tree + url + viewportOffset
    BG-->>BC: tree_response
    BC-->>UI: DOM snapshot
    UI->>AI: generate_plan_and_steps(query, url, DOM)
    AI-->>UI: milestones + milestone 0 steps
    UI->>FS: Write plan.json + sub_task.json
    UI->>FS: Write generated_task.json compatibility copy
    UI->>FS: Write dom_snapshot.json
    UI->>TC: load_task(sub_task.json)
```

## Highlighting flow

```mermaid
sequenceDiagram
    participant TC as TaskController
    participant Step as Step.from_dict
    participant BC as BrowserConnector
    participant BG as extension/background.js
    participant CS as extension/content.js

    TC->>Step: Load step using generated_task.json + dom_snapshot.json
    Step-->>TC: Step with element_id and coords
    TC->>BC: highlight(element_id, target, tooltip)
    BC->>BG: HIGHLIGHT
    BG->>CS: HIGHLIGHT
    CS->>CS: extractElements() to refresh data-ai-overlay-id tags
    CS->>CS: findElement(element_id, target)
    CS->>CS: Render dim layer, ring, tooltip
    CS-->>BG: highlight_response success/failure
    BG-->>BC: highlight_response
```

### Important detail: element IDs are volatile

`dom_extractor.js` assigns `data-ai-overlay-id` values during each extraction. These IDs are not stable across page changes or repeated DOM traversal.

To reduce stale-ID errors, highlighting should validate that the element found by ID still matches the expected target text/type. If the ID points to the wrong element, `content.js` falls back to text/label matching.

## User click and navigation handling

```mermaid
flowchart TD
    A[User clicks highlighted element] --> B[content.js captures click]
    B --> C[background.js forwards user_click]
    C --> D[BrowserConnector callback queued to Qt main thread]
    D --> E{Click matches pending element?}
    E -- No --> F[Ignore click]
    E -- Yes --> G[Mark current step complete]
    G --> H{Navigation detected or steps exhausted?}
    H -- No --> I[TaskController advances within current sub-task]
    H -- Yes --> J[Fetch fresh DOM]
    J --> K[Combined Gemini verify and next-step generation]
```

## Multi-page sub-task generation loop

When the user follows a link or route change, the original `generated_task.json` may no longer match the current page. The runtime therefore generates a page-specific sub-task.

```mermaid
flowchart TD
    A[Navigation or current sub-task exhausted] --> B[Fetch fresh DOM and URL]
    B --> C[Read active milestone and success hints from plan.json]
    C --> D{Last milestone hint matched?}
    D -- Yes --> Z[Complete task]
    D -- No --> E[One Gemini verify_and_generate call]
    E --> F{goal_complete?}
    F -- Yes --> Z
    F -- No --> G[Update milestone status, attempts, replans]
    G --> H[Persist plan.json, sub_task.json, dom_snapshot.json]
    H --> I[TaskController loads new sub-task]
    I --> J[Highlight first step]
    J --> A
```

## Runtime files

| File | Purpose |
|---|---|
| `tasks/plan.json` | Persistent original goal, milestones, current index, attempt counts, and replan count. |
| `tasks/generated_task.json` | Compatibility copy of the initial website task; retained for existing tools. |
| `tasks/sub_task.json` | Current workflow steps for the active milestone/page. Rewritten at each verification point. |
| `tasks/dom_snapshot.json` | DOM snapshot used by `Task.load_from_file` to resolve step element IDs and bounds. Rewritten when a new page/sub-task is generated. |
| `tasks/history.json` | Recent task history used by the task input dialog. |

## Prompt context for sub-tasks

Each verification/generation call receives:

```text
Original user goal: <original query>
Full milestone plan and active milestone: <plan.json state>
Most recently completed step: <last completed target>
Current page URL: <browser URL>
Heuristic success-hint match: <boolean evidence>
Current page DOM: <fresh UINode JSON array>
```

The generator is instructed to:

- Continue the original goal.
- Generate only the next steps for the current page.
- Avoid repeating completed actions.
- Avoid navigating backward.

## Current failure points to watch

### Gemini API failure

Gemini API requests are retried once with backoff. If the retry also fails or returns malformed JSON, the current workflow is retained and a non-fatal recovery message is shown.

Relevant file:

```text
core/ai_task_generator.py
```

### Extension/WebSocket disconnect

The extension connects to Python at:

```text
ws://127.0.0.1:8765
```

A heartbeat in `extension/background.js` keeps the Manifest V3 service worker alive while Python waits for generation.

### DOM mutation loops

Overlay-created DOM mutations must not trigger repeated extraction/highlighting. `content.js` filters mutations involving overlay elements such as:

```text
#ai-overlay-dim
#ai-overlay-tooltip
#ai-overlay-spotlight-ring
#ai-overlay-progress-bar
#ai-overlay-style
```

## Simplified end-to-end loop

```mermaid
stateDiagram-v2
    [*] --> CaptureInitialDOM
    CaptureInitialDOM --> GenerateInitialTask
    GenerateInitialTask --> HighlightCurrentStep
    HighlightCurrentStep --> WaitForUserAction
    WaitForUserAction --> AdvanceSamePage: Click without navigation
    AdvanceSamePage --> HighlightCurrentStep
    WaitForUserAction --> CaptureNewPageDOM: Click or route navigation
    CaptureNewPageDOM --> GenerateSubTask
    GenerateSubTask --> LoadSubTask
    LoadSubTask --> HighlightCurrentStep
    HighlightCurrentStep --> Complete: No steps remain
    Complete --> [*]
```
