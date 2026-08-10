# AI Overlay — Browser Extension: Guardrail Reference

**Purpose of this file:** You (the coding assistant) may lose the thread over a long session — over-engineering, refactoring things that don't need it, inventing new architecture, or drifting into a different design than what was agreed. When that happens, **stop and re-read this file before continuing.** It is the source of truth for scope, architecture, and what NOT to do.

If anything you're about to do contradicts this file, **stop and ask the user instead of proceeding.**

---

## 1. The One-Sentence Goal

Add a **browser companion extension** to the existing Windows desktop AI Overlay app, so the same guided-tutorial experience works on websites — **without rewriting the existing Windows functionality.**

If a task doesn't serve this sentence, it's out of scope for the 15-day window.

---

## 2. What Already Exists (DO NOT REBUILD THIS)

The desktop app is a working PyQt6 application. These pieces are DONE and should be reused, not rewritten, unless a task explicitly says "refactor X":

| Piece | File | Status |
|---|---|---|
| Task decomposition via Gemini | `core/ai_task_generator.py` | Working |
| Step/task data model | `core/step.py`, `core/task.py` | Working |
| Step navigation logic | `core/task_controller.py` | Working |
| Windows element resolution | `platforms/uia_resolver.py` via `pywinauto` | Working |
| Hybrid resolver (routes to UIA) | `platforms/hybrid_resolver.py` | Working — **Vision fallback is currently disabled, leave it disabled unless told otherwise** |
| Cached element lookups | `ui_dictionary.json` | Working |
| Overlay rendering | `core/overlay_window.py`, `core/layer_manager.py` | Working |
| HUD / step dots / pause | `core/layers/hud_layer.py` | Working |
| Tooltip / spotlight text | `core/layers/tooltip_layer.py` | Working |
| Click/focus auto-advance | `core/action_watcher.py` | Working |
| TTS narration | `core/tts.py` (Windows SAPI) | Working — reused as-is for browser flow, narration is desktop-side regardless of target platform |
| Mic input | main.py flow | Working — not in scope to change |
| Linux accessibility stub | `platforms/atspy_resolver.py` | Exists, **out of scope**, do not extend during this project |

**Rule of thumb:** if you find yourself editing one of the "Working" files above for a reason other than "implementing the `UIConnector` interface" (see §4), stop and check if that's actually necessary.

---

## 3. What This Project Adds

Only these things are new:

1. A **Chrome/Edge browser extension** (new codebase, separate from the Python app).
2. A **WebSocket/HTTP bridge** between the desktop app and the extension (localhost only).
3. A **`UIConnector` abstract interface** that both `UIAResolver` (existing, adapted) and a new `BrowserConnector` implement.
4. **DOM extraction, filtering, and mutation tracking** inside the extension.
5. **Basic context-awareness** (Level 3): correct action → advance, wrong action → stay, page change → refresh tree.

That's it. Nothing else is in scope. See §7 for the explicit out-of-scope list.

---

## 4. Architecture — Do Not Deviate

```
                         AI Overlay Core (existing, extended)
                ┌──────────────────────────┐
                │ Gemini Task Planner      │
                │ Tutorial State Manager   │
                │ Step Navigator           │
                │ Overlay Renderer         │
                │ Event Manager (NEW)      │
                └────────────┬─────────────┘
                             │
               ┌─────────────┴─────────────┐
               │                           │
       Windows Connector           Browser Connector (NEW)
        (adapts UIAResolver)         (Chrome Extension)
               │                           │
       Windows UI Tree              Simplified DOM Tree
```

**Key architectural rules:**

- The desktop app is **still the brain**. The extension does DOM work and reports state; it does **not** call Gemini directly and does **not** make step-advance decisions on its own.
- Both connectors must produce the **same common UI node shape** (§5) so the Core never needs to know which platform it's talking to.
- Communication is **localhost WebSocket/HTTP only.** Do not add cloud relay, remote access, or anything beyond localhost — that's a scope explosion and a security surface you don't need for a 15-day prototype.

**If you find yourself designing a plugin system, a general-purpose connector SDK, or anything "for future platforms" — stop.** Only two connectors exist. Build for two.

---

## 5. Common UI Node Schema (frozen — don't redesign mid-project)

```json
{
  "id": 42,
  "type": "button",
  "text": "Login",
  "role": "button",
  "enabled": true,
  "visible": true,
  "bounds": { "x": 400, "y": 280, "width": 120, "height": 40 }
}
```

If token cost becomes a real, **measured** problem (not a guess), the fix is:
- Shorten keys (`x/y/w/h` flat instead of nested `bounds`).
- Only include `bounds` for candidate/target elements the model needs to reason about spatially, not every node.
- Array-of-arrays with a header row for the node list.

**Do not introduce a new serialization format (TOON or otherwise) without profiling actual token usage first.** JSON in, small fixed-schema JSON out. See §8 for why.

### `UIConnector` interface (frozen)

```python
class UIConnector:
    def get_tree(): ...
    def highlight(id): ...
    def wait_for_click(id): ...
    def observe_changes(): ...
```

Both `WindowsConnector` (adapting the existing `UIAResolver`) and `BrowserConnector` must implement exactly this. Do not add platform-specific methods to this interface — if the browser needs something Windows doesn't (or vice versa), that logic goes inside the connector implementation, not the shared interface.

---

## 6. Gemini's Role — Keep It Narrow

Gemini does two things and two things only:

1. **Task decomposition** (already working, unchanged) — free text → structured steps.
2. **Target selection** — given the simplified UI tree + current step description, return which `id` is the target.

**Gemini's output must always be a small fixed-schema JSON object, e.g.:**

```json
{ "target_id": 42, "action": "click", "reasoning": "this is the login button" }
```

Gemini should **never** be asked to re-emit a full UI node, re-serialize the tree, or produce TOON/HTML/anything bulky. It points at an `id` you already have. This is a hard rule — if a prompt is being built that asks Gemini to generate structured UI data back, stop and simplify it to an `id` reference instead.

**Vision fallback stays disabled.** Do not re-enable or extend `hybrid_resolver.py`'s vision path as part of this project unless explicitly asked.

---

## 7. Explicitly Out of Scope (Level 4/5 and beyond)

Do not implement, scaffold, or "lay groundwork for" any of the following:

- Cloud/remote communication (localhost only)
- A general plugin/connector SDK for hypothetical future platforms
- Linux desktop support (`atspy_resolver.py` stays untouched)
- Vision-based fallback resolution
- Authentication/permission system for the WebSocket (note the risk, don't build the fix — see §9)
- New TTS/mic behavior — narration is reused as-is
- TOON or any non-JSON serialization, unless profiled and requested
- Predictive/proactive guidance, multi-task memory, or anything beyond "advance / stay / refresh"

If a task seems to require one of these, **stop and flag it to the user** rather than building it.

---

## 8. Data Format Decision (already made — don't relitigate)

- **DOM → simplified tree:** compact JSON, filtered per the rules in the original project plan (keep interactive elements + structural elements with useful content; drop script/style/meta/hidden/empty containers).
- **Storage:** in-RAM only during the active session. Discarded when task ends. `ui_dictionary.json`-style caching is a Windows-only concept for now — do not invent a browser equivalent unless asked.
- **LLM input:** JSON (TOON only if profiling later proves it's worth it — see §5).
- **LLM output:** minimal fixed-schema JSON referencing existing `id`s, never a re-encoding of tree data.

---

## 9. Known Risks (acknowledged, not blocking — don't silently "fix" these by over-building)

- **WebSocket has no auth.** Any local process could connect. Acceptable for a prototype. Do not build a full auth system — that's out of scope (§7). A one-line comment noting the risk in the bridge code is enough.
- **Round-trip staleness:** page could navigate away between "Gemini picks target" and "highlight command reaches browser." Level 3's refresh-on-navigation-change handles this after the fact. Don't build predictive cancellation/debouncing logic beyond what's needed to not crash — that's scope creep.
- **No fast-path cache for browser elements** (unlike Windows' `ui_dictionary.json`). Acceptable for prototype; live DOM extraction is fast enough. Don't build a caching layer unless it's demonstrably too slow.

---

## 10. Phase Checklist (from the original 15-day plan — use this to check where you actually are)

- [ ] **Phase 1:** Shared UI node schema + `UIConnector` interface defined
- [ ] **Phase 2:** Chrome/Edge extension — DOM extraction, filtering, highlighting, click detection, WebSocket comms
- [ ] **Phase 3:** Windows + Browser connectors both implement `UIConnector`
- [ ] **Phase 4:** `MutationObserver` incremental tree updates
- [ ] **Phase 5:** Level 3 context awareness (correct action / wrong action / page change)

**If you're deep into a task and can't tell which phase it belongs to, stop.** It's probably scope creep.

---

## 11. Quick Self-Check Before Any Big Change

Ask, in order:

1. Does this serve §1 (the one-sentence goal)?
2. Am I editing a "Working" file from §2 for a reason other than the `UIConnector` adaptation?
3. Am I about to add a new format, library, service, or abstraction not mentioned in this file?
4. Is this on the §7 out-of-scope list?
5. Would this still make sense if I only had 15 days total?

**Any "yes" to 2 or 3, or "yes" to 4 → stop and surface it to the user instead of proceeding.**
