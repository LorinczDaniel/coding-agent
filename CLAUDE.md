# CLAUDE.md

Guidance for AI coding agents working in this repository.

## What this is

`claude-agent` — a "build your own Claude Code" project: a Textual TUI coding
agent driven by Claude models through OpenRouter's OpenAI-compatible API.
Pure Python 3.14, managed with uv. No web services, no database.

## Commands

```bash
uv sync --group dev            # install everything (uses uv.lock)
uv run pytest                  # full test suite (fast, ~2s)
uv run pytest tests/test_agent.py -k task   # subset
uv run ruff check app tests    # lint (rules configured in pyproject.toml)
uv run mypy app                # type-check
uv run claude-agent            # launch the TUI (needs OPENROUTER_API_KEY in .env)
```

CI (`.github/workflows/ci.yml`) runs exactly ruff + mypy + pytest; all three
must pass before a change is done.

## Architecture in one pass

- `app/agent.py` — the agent loop. Streams one model request per turn,
  accumulates tool-call deltas, executes tools in parallel via
  `asyncio.gather`, appends results, repeats until the model stops calling
  tools (capped at `MAX_TOOL_TURNS`). Also runs `Task` subagents as nested
  conversations. **Invariant: every assistant `tool_calls` entry must get a
  matching `role:"tool"` message, no matter what fails** — malformed args and
  handler crashes become error results, never exceptions.
- `app/tools.py` — tool implementations, JSON schemas, and `TOOL_REGISTRY`
  (the single source of truth for tool names; profiles validate against it).
- `app/tui.py` — the Textual app. Slash commands dispatch through the
  `COMMANDS` registry (which also generates `/help`). Pure state lives in
  `__init__`; widget wiring in `on_mount`. On error/interrupt the message
  list is rolled back to `_safe_msg_count` before the session is saved.
- `app/session.py` — persistence. All writes are atomic (temp file +
  `os.replace`); corrupt files are quarantined, never overwritten. Sessions
  are keyed by a hash of the resolved cwd; sidecars: `<name>.lesson.json`
  (lesson state), `<name>.meta.json` (agent profile).
- `app/agents.py` — built-in profiles (coach, mentor) + custom profile store
  (`.claude-agent/profiles.json`). Saving must never destroy entries it
  couldn't parse.
- `app/permissions.py` — Bash risky-command gate and outside-cwd path gate.
  Auto-allow requires **every** pipeline segment to match; command
  substitution always prompts.
- `app/config.py` — system prompt assembly: base prompt, profile-aware tool
  list, project type, discovered skills, optional `system.md`, profile
  addendum.
- `app/lessons.py` / `app/skills.py` — pure logic (no Textual imports).
- `app/format.py` / `app/widgets.py` — rendering helpers and widgets.

## Testing conventions

- `tests/conftest.py` isolates every test from the real `~/.claude-agent`
  session store and the repo's profile store. Never remove that fixture; if
  you add a new persistence path, isolate it there too.
- TUI tests construct `AgentApp()` without mounting and monkeypatch
  `query_one` / `_append_sync` / module globals (`app.tui.save_session`,
  `app.tui.run_agent`, …). The agent loop is tested by faking
  `client.chat.completions.create` with scripted stream chunks (see
  `_make_chunk` / `_make_stream` in `tests/test_agent.py`).
- Prefer asserting behavior (state, message lists, tool schemas) over exact
  UI copy strings.

## Gotchas

- The permission gate is a heuristic guardrail, not a sandbox — keep it
  conservative, and never let an auto-allow path skip segment analysis.
- `Bash` runs with `shell=True` in its own process group; timeouts must kill
  the whole group or grandchildren hold the pipe open forever.
- OpenRouter streams can deliver a tool call's `id`/`name` in any chunk, and
  arguments may be truncated — `parse_tool_args` returning `None` is a normal
  case, not an error path to remove.
- `docs/superpowers/` holds historical planning specs from early feature
  work — they do not describe the current design. Source of truth is the
  code, README.md, and this file.
- Learning/demo projects (things built *with* the agent, like a snake game)
  go in `playground/`, which is gitignored — never in the repo root, and
  never mixed into the agent's own source.
