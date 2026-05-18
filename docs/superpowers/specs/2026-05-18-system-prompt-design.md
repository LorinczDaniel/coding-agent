# System Prompt — Design Spec

**Date:** 2026-05-18
**Status:** Approved

## Overview

Add a two-layer system prompt to claude-agent. A hardcoded base establishes the agent's identity as a coding assistant. A user-editable `system.md` file appended on top lets the user customize behaviour without touching source code.

## Architecture

A new `app/config.py` module owns all configuration loading. For now it contains a single function; future config concerns (model selection, tool toggles, etc.) land here too.

`app/tui.py` calls `load_system_prompt()` once at startup and pre-populates the message history with the system message before the first user turn. `app/agent.py` is unchanged — it treats the system message as a normal entry in the messages list.

## Components

### `app/config.py`

```python
def load_system_prompt() -> str
```

- Hardcoded base string establishes: role (coding assistant), available tools (Read, Write, Bash), expected behaviour (think before acting, prefer targeted edits, explain what you did)
- Reads `system.md` from the current working directory if it exists; silently skips if absent
- Returns `base + "\n\n" + custom` if `system.md` exists, otherwise returns `base` alone

### `app/tui.py`

Single change in `on_mount`:

```python
from .config import load_system_prompt

self._messages = [{"role": "system", "content": load_system_prompt()}]
```

### `system.md` (user file, not committed)

Added to `.gitignore`. Users create and edit this file to extend the system prompt.

### `system.md.example` (committed)

Shipped with the repo. Documents the format and provides example customisations:

```markdown
# Custom instructions

- Prefer Python over shell scripts when both would work
- Always write tests alongside new code
- Keep responses concise — skip the preamble
```

## File Map

| File | Action |
|---|---|
| `app/config.py` | Create |
| `app/tui.py` | Modify — `on_mount` only |
| `system.md.example` | Create |
| `.gitignore` | Modify — add `system.md` |

## Error Handling

- Missing `system.md` — silently ignored, hardcoded base is used alone
- Unreadable `system.md` (permissions, encoding) — raise with a clear error message rather than silently continuing with no custom prompt

## Testing

- `load_system_prompt()` with no `system.md` present → returns base string only
- `load_system_prompt()` with a `system.md` present → returns base + custom content
- Hardcoded base always present in both cases

## Out of Scope

- Hot-reloading `system.md` during a session
- Multiple system prompt files
- UI for editing the system prompt
