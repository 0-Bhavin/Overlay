# AI Overlay — Browser Extension Project Plan

## Agreed Goal

Extend the existing **AI Overlay** desktop assistance application from Microsoft/Windows applications to web browsers.

The target is:

- **Level 2:** Cross-platform AI guidance with a common UI abstraction.
- **Level 3:** Basic context-aware guidance.
- Levels 4 and 5 are out of scope.

The system will use a **2-platform, 1-base architecture**:

- One shared AI Overlay Core.
- One Windows connector.
- One Browser connector.

---

## Final Architecture

```text
                         AI Overlay Core
                ┌──────────────────────────┐
                │ Gemini Task Planner      │
                │ Tutorial State Manager   │
                │ Step Navigator           │
                │ Overlay Renderer         │
                │ Event Manager            │
                └────────────┬─────────────┘
                             │
               ┌─────────────┴─────────────┐
               │                           │
       Windows Connector           Browser Connector
          (UIA/pywinauto)             (Chrome Extension)
               │                           │
       Windows UI Tree              Simplified DOM Tree
```

The AI Core works with a common UI representation rather than platform-specific UI structures.

---

## Browser Architecture

The browser will use a **Chrome/Edge extension as a companion to the desktop application**.

The desktop application remains the main application and AI brain.

```text
User
 │
 ▼
PyQt6 Desktop Application
 │
 │ localhost communication
 │ WebSocket / HTTP
 ▼
Browser Extension
 │
 ▼
Current Website
```

### Desktop Application

Responsible for:

- Gemini task decomposition
- Tutorial state
- Step navigation
- Overall workflow
- PyQt6 overlay
- TTS
- Communication with the browser extension

### Browser Extension

Responsible for:

- DOM extraction
- DOM change detection
- Element identification
- Element highlighting
- Click detection
- Sending browser state/events to the desktop application

The extension does not contain the main AI logic.

---

## Common UI Model

Both platforms produce the same simplified UI representation.

```json
{
  "id": 42,
  "type": "button",
  "text": "Login",
  "role": "button",
  "enabled": true,
  "visible": true,
  "bounds": {
    "x": 400,
    "y": 280,
    "width": 120,
    "height": 40
  }
}
```

The shared interface will provide operations such as:

```python
class UIConnector:
    def get_tree()
    def highlight(id)
    def wait_for_click(id)
    def observe_changes()
```

Implementations:

```text
WindowsConnector
BrowserConnector
```

---

## Browser Data Pipeline

```text
Website
   ↓
Browser Extension
   ↓
DOM Extraction
   ↓
Filter & Simplify
   ↓
Simplified UI Tree
   ↓
Desktop Application
   ↓
Gemini
   ↓
Target Element
   ↓
Browser Extension
   ↓
Highlight Element
   ↓
User Action
   ↓
Event sent to Desktop
   ↓
Next Step
```

The complete raw HTML is not sent to Gemini.

---

## DOM Filtering

The system will keep **useful UI elements**, not every HTML tag.

### Keep

Interactive elements:

```text
button
a
input
textarea
select
option
label
form
summary
details
```

Useful structural elements when they contain relevant content:

```text
nav
menu
header
footer
main
section
article
aside
div
span
```

`div` and `span` are retained only when they contain useful text, ARIA roles, event-related information, or interactive descendants.

### Ignore

```text
script
style
meta
link
noscript
template
```

Non-interactive SVG internals such as:

```text
svg
path
defs
clipPath
```

are ignored.

Invisible elements are ignored when they use:

```text
display: none
visibility: hidden
hidden
aria-hidden="true"
```

Empty containers without useful descendants are ignored.

---

## DOM Node Information

Each retained element will contain only relevant information:

```text
id
tag/type
role
text
ARIA information
enabled state
visibility
bounding box
```

Styles, JavaScript, and unnecessary HTML content are excluded.

---

## DOM Storage

The current simplified DOM tree is stored **in RAM during the active session**.

```text
Task starts
    ↓
Build simplified tree
    ↓
Store in RAM
    ↓
Update through DOM mutations
    ↓
Task ends
    ↓
Session data discarded
```

Local storage is used only for persistent application data such as preferences or cached mappings, not the active DOM.

---

## DOM Updates

The browser extension will use `MutationObserver` to detect changes such as:

- Node added
- Node removed
- Text changed
- Attribute changed

The system updates the affected part of the in-memory UI tree instead of rebuilding the entire DOM after every action.

---

## Level 3 Context Awareness

The system will support basic adaptive behavior.

### Correct action

```text
User clicks target
        ↓
Advance to next step
```

### Wrong action

```text
User clicks another element
        ↓
Remain on current step
        ↓
Continue guidance
```

### Page/navigation change

```text
Page changes
    ↓
Refresh simplified UI tree
    ↓
Continue guidance
```

---

## 15-Day Implementation Target

### Phase 1 — Common UI Model
- Define shared UI node schema.
- Define `UIConnector` interface.

### Phase 2 — Browser Connector
- Build Chrome/Edge extension.
- Extract simplified DOM.
- Highlight elements.
- Detect clicks.
- Communicate with desktop application.

### Phase 3 — Platform Abstraction
- Integrate Windows and Browser connectors with the common interface.

### Phase 4 — Incremental DOM Updates
- Implement `MutationObserver`.
- Update changed nodes in memory.

### Phase 5 — Basic Context Awareness
- Correct action detection.
- Wrong-action handling.
- Page/navigation change handling.

---

## Final 15-Day Deliverable

The completed prototype will demonstrate:

- One shared AI Overlay Core.
- Windows desktop application support.
- Browser support through a companion extension.
- Common UI abstraction.
- Simplified DOM extraction.
- In-memory DOM state.
- Incremental DOM updates.
- AI-guided browser element highlighting.
- User action detection.
- Basic context-aware guidance.

The project will be presented as a **cross-platform AI UI guidance framework**, with Windows applications and web browsers as its two supported platforms.
