# claude-agent

A terminal-based AI coding assistant with a live chat UI. Powered by Claude via OpenRouter, it can read files, write files, run shell commands, spawn subagents, and follow reusable skills — all from a single conversation.

---

## What it does

claude-agent gives you a conversational interface to an AI that can actually act on your codebase. You describe what you want; the agent decides which tools to use, runs them, sees the results, and responds — in a loop until the task is done.

### Tools available

| Tool | What it does |
|---|---|
| **Read** | Reads and returns the full contents of any file |
| **Write** | Creates a new file or fully overwrites an existing one |
| **Edit** | Replaces an exact string in an existing file (preferred for modifications) |
| **Bash** | Runs any shell command and returns stdout and stderr separately |
| **Glob** | Finds files matching a glob pattern (e.g. `**/*.py`) |
| **Grep** | Searches file contents with a regex |
| **TodoWrite** | Tracks multi-step plans with a todo panel |
| **Task** | Spawns a subagent with a fresh context for a self-contained side quest; only its final report comes back |
| **Skill** | Loads a `SKILL.md` instruction pack by name and follows it |

The agent can chain these freely. Ask it to "refactor this file" and it will read it, figure out the changes, write the result, and confirm — without you doing anything in between. Independent tool calls in one turn run in parallel.

### Subagents (Task)

When the agent hits a self-contained side quest — "find every caller of X", "summarize this directory" — it can delegate to a **subagent**: a nested agent conversation with its own fresh context and the same tools (minus Task, so no infinite nesting). Only the subagent's final report enters the parent conversation, keeping the main context small. Subagent token usage counts toward the session totals, and risky commands inside a subagent still hit the same permission prompts.

### Skills

A **skill** is a reusable instruction pack: a `SKILL.md` file with a tiny frontmatter block and markdown instructions.

```markdown
---
name: code-review
description: Review a diff or file for bugs, risks, and clarity.
---

# Code review
1. Read every file under review in full…
```

Skills are discovered from `skills/<name>/SKILL.md` (committed, shared with the project) and `.claude-agent/skills/<name>/SKILL.md` (personal) under the working directory. The agent sees the available skill names and descriptions in its system prompt and loads the matching one with the Skill tool before starting a task it covers. List them with `/skills`. This repo ships a `code-review` skill as a working example.

### Project context

On startup the agent is told its working directory and a guess at the project type (Python / Node / Rust / Go / Java, inferred from marker files like `pyproject.toml`, `package.json`, etc.), plus the tools its active profile actually allows and any discovered skills.

### UI features

- **Streaming responses** — text appears as the model generates it, not all at once
- **Inline tool output** — tool calls are shown as unframed, styled output as they happen
- **Rich tool output** —
  - `Write` / `Edit` show a **unified diff** of what changed (green additions, red deletions); new files render as all-additions
  - `Read` output is **syntax-highlighted** (lexer guessed from the file extension) with line numbers
  - `Bash` output hides **stdout** in the chat, shows **stderr** when present, and shows the command's **exit code** on a final line (green for 0, red otherwise); timeouts and denials render visibly
  - `TodoWrite` updates the todo panel without dumping its arguments or result into the chat
  - `Read` and `Bash` results over 50KB are truncated before rendering, keeping the beginning and end with an explicit truncated marker
  - long blocks show the first 15 lines and a clickable **`▸ show N more lines`** toggle to expand/collapse the rest
- **Markdown rendering** — bold, inline code, and other formatting renders properly in the terminal
- **Multi-turn conversation** — the full message history is kept in memory for the session, so you can follow up, correct, or ask for more
- **Named sessions** — conversations are stored in `~/.claude-agent/sessions/` keyed by working directory, saved **atomically** after every agent turn and auto-loaded on startup. Each session remembers which agent profile it was created under and restores it on load. Corrupt session files are quarantined (`.corrupt`) instead of silently overwritten.
- **Markdown export** — `/export [filename]` writes the current user/agent conversation to a Markdown file, excluding raw tool calls and tool output.
- **Token + cost tracking** — a status bar shows lifetime tokens in / out and total spend in USD (computed by OpenRouter, so no hardcoded pricing), plus a `ctx` segment showing how full the model's context window actually is (measured from the last request, not a running total). Warnings appear once at 75% and 90%.
- **Active lesson status** — lessons show a banner with the active goal and current hint level, plus milestones in the docked side panel. The panel is actionable: the current task carries a `next: edit …, then /check` pointer, and clicking any milestone shows its task card (status, check command, and the workspace `TASK.md` for the current task).
- **Model switching** — swap between models mid-session (e.g. haiku for speed, sonnet for capability) without losing context
- **Agent profiles** — the agent runs under a named *profile* that sets its persona and which tools it may use. The built-in **Coach** profile (the default) is a CodeCrafters-style learning coach; **Mentor** is a read-only guide. Switch with `/agent <name>`, or define your own with `/agent create`.
- **Guided learning (`/learn`)** — `/learn <thing>` starts a build-your-own-X lesson in a fresh `lesson-<thing>` session (your current conversation is kept). The Coach turns your goal into 5–10 milestones, hands you one task at a time, and offers graduated hints (`/hint`).
- **Milestone verification (`/check`)** — each milestone carries a check command the Coach sets when planning the lesson. `/check` runs it, shows the output, and has the Coach judge the result: pass advances to the next task, fail gets an explanation and a hint. The learner's loop is edit file → `/check` → feedback.
- **Tool permission gates** — risky `Bash` commands and any `Read`/`Write`/`Edit` touching a path outside the working directory pause for inline y/n approval. Denying tells the model not to retry.

### Commands

| Command | Description |
|---|---|
| `/help` | Show all available commands |
| `/clear` | Clear the current conversation |
| `/export [filename]` | Export the current conversation to Markdown |
| `/learn <thing>` | Start a guided build-your-own lesson with the Coach (e.g. `/learn grep`) |
| `/hint` | Get the next-strongest hint for the current lesson task |
| `/check` | Run the current milestone's check command and get the Coach's verdict |
| `/agent` | Show the current agent profile and available profiles |
| `/agent <name>` | Switch to an agent profile (starts a fresh conversation) |
| `/agent create [name]` | Create a custom agent profile interactively |
| `/model` | Show current model and available options |
| `/model <name>` | Switch to a different model (e.g. `haiku`, `sonnet`) |
| `/skills` | List skills available to the agent |
| `/sessions` | List all sessions for this directory |
| `/sessions new <name>` | Create and switch to a new named session |
| `/sessions load <name>` | Switch to an existing session |
| `/sessions rename <old> <new>` | Rename a saved session |
| `/sessions delete <name>` | Delete a saved session |
| `/todo-clear` | Clear the todo panel |

Most commands also support a `help` subcommand (e.g. `/model help`, `/sessions help`).

### Keyboard shortcuts

| Key | Action |
|---|---|
| <kbd>Enter</kbd> | Send message |
| <kbd>Esc</kbd> | Interrupt the running agent. Drops any partial response, keeps your last user message, and re-enables input so you can steer or retry. |
| <kbd>Ctrl</kbd>+<kbd>X</kbd> | Quit |
| <kbd>↑</kbd> / <kbd>↓</kbd> | Recall input history |

---

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) for dependency management
- An [OpenRouter](https://openrouter.ai) API key

## Setup

```bash
git clone https://github.com/LorinczDaniel/coding-agent.git
cd coding-agent
uv sync
cp .env.example .env   # then add your OpenRouter key
```

## Running

```bash
uv run claude-agent      # or: uv run -m app.main
```

The Textual TUI opens in your terminal. The input box at the bottom is focused automatically.

---

## Configuration

### Permission prompts (`.agent_config.json`)

Drop an optional `.agent_config.json` in the project root to tune permission prompts:

```json
{
  "auto_allow": ["git push", "pytest", "uv run"]
}
```

`auto_allow` is a list of **whole-word prefixes**. A command runs without prompting only when **every** segment of the command (split on `&&`, `||`, `;`, `|`, `&`, and newlines) matches one of these prefixes — an allowed first segment does not whitelist whatever is chained after it. Commands containing `$( )` or backtick substitution always prompt, since prefix analysis can't see inside them.

The built-in risky list (always prompts unless every segment is auto-allowed):
`rm`, `rmdir`, `git push`, `git reset --hard`, `git checkout --`, `git clean -f*`, `sudo`, `shutdown`, `reboot`, `halt`, `mkfs`, `dd`, `chmod`, `chown`, `kill`, `killall`, `pkill`, `npm publish`, `pip uninstall`, `uv remove`, plus any `… | sh|bash|zsh|fish` pipe. Env-var prefixes (`FOO=1 rm …`), absolute paths (`/bin/rm`), and wrappers (`env`, `xargs`, `nohup`, …) don't hide a risky command.

For `Read`, `Write`, and `Edit`, any `file_path` resolving outside the current working directory also prompts.

The gate is a **guardrail, not a sandbox**: determined obfuscation (e.g. `python -c "import os; os.remove(...)"`) still slips through. It catches obvious foot-guns.

### Custom system prompt (`system.md`)

Copy `system.md.example` to `system.md` to append personal instructions to the agent's system prompt.

### Model

The default is `haiku` (`anthropic/claude-haiku-4.5` via OpenRouter). Available aliases live in the `MODELS` dict in `app/agent.py`; switch at runtime with `/model <name>`. Any OpenAI-compatible model available on OpenRouter will work.

---

## Project structure

```
app/
  main.py      # entry point — launches the Textual app
  tui.py       # Textual App: command registry, layout, streaming callbacks
  agent.py     # async agent loop, OpenRouter streaming, tool dispatch, Task subagents
  tools.py     # tool implementations + schemas + registry (Read/Write/Edit/Bash/Glob/Grep/TodoWrite/Skill/Task)
  lessons.py   # pure lesson logic: goal extraction, hint ladder, milestones
  skills.py    # SKILL.md discovery, parsing, prompt section
  config.py    # system prompt assembly (profile-aware tool list, skills, project type)
  agents.py    # agent profiles (Coach, Mentor, custom), allowed-tool validation, profile store
  session.py   # atomic session/lesson/profile-meta persistence, Markdown export
  format.py    # UI-agnostic formatting helpers (usage bar, bash stream parsing, diff styles)
  permissions.py  # risky-command detection, auto-allow config, path gating
  widgets.py   # ToolBlock / ToolToggle / TodoPanel widgets + tool body rendering
skills/
  code-review/SKILL.md  # example skill, also live when running the agent here
```

## Development

```bash
uv sync --group dev
uv run pytest            # test suite
uv run ruff check app tests
uv run mypy app
```

CI runs the same three checks on every PR.

---

## Limitations

- Tool output shows the first 15 lines by default; click `▸ show N more lines` to expand. `Read` and `Bash` results are capped at 50KB before display and model context.
- `Esc` only takes effect at the next `await` — if the agent is blocked inside a long synchronous tool call, the interrupt waits until that tool returns (Bash timeouts kill the whole process group, so nothing hangs forever).
- Session files are per-directory — launching the agent from a different cwd starts a fresh conversation.
- Subagent activity is invisible until it finishes; you only see its final report (permission prompts still surface).
- `.agent_config.json` is read on every tool call, but the system prompt is captured at startup, so new skills or a changed `system.md` need a `/clear` or restart to show up.
