# TUI Design — codecrafters-agent

**Date:** 2026-05-15
**Status:** Approved

## Overview

Add a Textual-based terminal UI to the existing Python AI agent. The UI presents a single scrollable chat feed with inline styled tool-call blocks and a persistent input box at the bottom. The agent loop runs as an async Textual worker so the UI stays responsive during streaming and tool execution.

## Layout

```
┌─────────────────────────────┐
│  codecrafters-agent         │  ← header
├─────────────────────────────┤
│                             │
│  You: list files            │  ← RichLog (scrollable, fills space)
│  Agent: I'll start...       │
│  ┌─ Bash ──────────────┐    │
│  │ $ ls -la            │    │  ← tool call block (dimmed box)
│  │ main.py tools.py    │    │
│  └─────────────────────┘    │
│  Agent: Done ✓              │
│                             │
├─────────────────────────────┤
│  > type a message...   Send │  ← Input + Button (always visible)
└─────────────────────────────┘
```

Single panel. No sidebars. Tool calls appear inline as dimmed styled boxes.

## Components

| File | Role |
|---|---|
| `app/tui.py` | Textual `App` subclass — layout, widgets, event handlers |
| `app/agent.py` | Async agent loop — streaming, tool dispatch, yields events |
| `app/main.py` | Entry point — launches the Textual app |
| `app/tools.py` | Unchanged — `Read`, `Write`, `Bash` functions + schema dicts |

## Data Flow

1. User types message and presses Enter or Send
2. Input is cleared and disabled; message appended to `RichLog` as `You: ...`
3. Textual worker starts `run_agent(messages)` coroutine
4. Agent loop calls OpenRouter with `stream=True`
5. Each streamed text delta is appended to `RichLog` live (same "Agent:" line)
6. When a tool call chunk is complete, a styled block is appended:
   - Header: tool name (amber)
   - Body: command/args (dim)
   - Footer: output (default color)
7. Tool result is added to messages; loop continues
8. When finish_reason is `stop`, input is re-enabled

## Agent Loop (`app/agent.py`)

- `async def run_agent(messages, on_text, on_tool_call, on_tool_result)` — callback-based so `tui.py` doesn't need to know about OpenAI internals
- Accumulates streamed tool call chunks before executing (OpenAI streaming returns tool calls in fragments)
- Calls `Read`, `Write`, or `Bash` synchronously inside the async loop (all three are fast enough; no threadpool needed)
- Returns when the model stops calling tools

## TUI (`app/tui.py`)

- `Header` widget with app name
- `RichLog` fills the remaining space; `auto_scroll=True`
- `Input` + `Button` in a horizontal `Compose` at the bottom
- `on_input_submitted` and `on_button_pressed` both trigger the same send handler
- Agent runs via `self.run_worker(self._agent_task(...), exclusive=True)`

## Error Handling

- If the OpenRouter call fails, append an error line to the feed and re-enable input
- Tool execution errors (e.g., file not found) are returned as the tool result string; the agent sees them and responds accordingly
- No retry logic — surface errors to the user

## Dependencies

- `textual` (add to `pyproject.toml` or `requirements.txt`)
- Existing: `openai`, python stdlib

## Out of Scope

- Multi-turn session persistence (no history saved to disk)
- Multiple concurrent agent sessions
- Streaming tool output in real time (output shown after tool completes)
