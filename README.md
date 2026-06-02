# claude-agent

A terminal-based AI coding assistant with a live chat UI. Powered by Claude via OpenRouter, it can read files, write files, and run shell commands — all from a single conversation.

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

The agent can chain these freely. Ask it to "refactor this file" and it will read it, figure out the changes, write the result, and confirm — without you doing anything in between.

### Project context

On startup the agent is told its working directory and a guess at the project type (Python / Node / Rust / Go / Java, inferred from marker files like `pyproject.toml`, `package.json`, etc.). This means it knows things like "you're in `/home/me/my-project`, a Python project" without you having to spell it out every time.

### UI features

- **Streaming responses** — text appears as the model generates it, not all at once
- **Inline tool blocks** — each tool call is shown in a styled box as it happens:
  ```
  ┌─ Bash ──────────────────────────────
  │ ls -la
  │ total 32
  │ drwxr-xr-x  app/
  │ -rw-r--r--  pyproject.toml
  └─ exit 0 ────────────────────────────
  ```
- **Rich tool output** —
  - `Write` / `Edit` show a **unified diff** of what changed (green additions, red deletions) instead of dumping the whole file; new files render as all-additions
  - `Read` output is **syntax-highlighted** (lexer guessed from the file extension) with line numbers
  - `Bash` blocks show **stdout** and **stderr** as separate sections, with stderr dimmed red, and show the command's **exit code** in the closing line (green for 0, red otherwise)
  - `Read` and `Bash` results over 50KB are truncated before rendering, keeping the beginning and end with an explicit truncated marker
  - long blocks show the first 15 lines and a clickable **`▸ show N more lines`** toggle to expand/collapse the rest
- **Markdown rendering** — bold, inline code, and other formatting renders properly in the terminal
- **Multi-turn conversation** — the full message history is kept in memory for the session, so you can follow up, correct, or ask for more
- **Named sessions** — conversations are stored in `~/.claude-agent/sessions/` keyed by working directory. You can create, switch, and delete named sessions to keep separate threads (e.g. "feature-x" vs "bug-triage") in the same repo. Auto-saved after every agent turn; auto-loaded on startup.
- **Markdown export** — `/export [filename]` writes the current user/agent conversation to a Markdown file for documentation or sharing, excluding raw tool calls and tool output.
- **Token + cost tracking** — a status bar above the input shows lifetime tokens in / out and total spend in USD, updated after every agent turn (e.g. `session: ↑ 12,400 · ↓ 3,100 · $0.0420`). Cost is computed by OpenRouter at the model's current rate, so no hardcoded pricing to maintain. Totals persist through `/clear` (the dollars don't refund) and reset only on app restart.
- **Model switching** — swap between models mid-session (e.g. haiku for speed, sonnet for capability) without losing context
- **Tool permission gates** — before the agent runs a destructive `Bash` command (`rm`, `git push`, `sudo`, `chmod`, `... | sh`, etc.) or a `Write` / `Edit` that targets a path outside the current working directory, the agent pauses and asks for approval inline in the conversation. Type `y` to approve or `n` to deny in the normal input box — denying tells the model "user denied this; do not retry" so it adapts instead of looping. (`Esc` still interrupts the whole turn.)

### Commands

| Command | Description |
|---|---|
| `/help` | Show all available commands |
| `/clear` | Clear the current conversation |
| `/export [filename]` | Export the current conversation to Markdown |
| `/model` | Show current model and available options |
| `/model <name>` | Switch to a different model (e.g. `haiku`, `sonnet`) |
| `/sessions` | List all sessions for this directory |
| `/sessions new <name>` | Create and switch to a new named session |
| `/sessions load <name>` | Switch to an existing session |
| `/sessions delete <name>` | Delete a saved session |
| `/todo-clear` | Clear the todo panel |

Every command also supports a `help` subcommand (e.g. `/model help`, `/sessions help`).

**Keyboard shortcuts:** `Ctrl+X` to quit, `Escape` to interrupt the agent mid-turn.

---

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) for dependency management
- An [OpenRouter](https://openrouter.ai) API key

---

## Setup

**1. Clone the repo**

```bash
git clone https://github.com/LorinczDaniel/coding-agent.git
cd coding-agent
```

**2. Install dependencies**

```bash
uv sync
```

**3. Create a `.env` file**

```bash
cp .env.example .env   # or create it manually
```

Add your OpenRouter key:

```
OPENROUTER_API_KEY=sk-or-...
```

Optionally override the base URL (defaults to OpenRouter):

```
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

---

## Running

```bash
uv run -m app.main
```

The Textual TUI opens in your terminal. The input box at the bottom is focused automatically.

---

## Usage

Type a message and press **Enter** or click **Send**. The agent streams its response and shows any tool calls inline. Input is locked while the agent is working and re-enabled when it finishes.

### Keybindings

| Key | Action |
|---|---|
| `Enter` | Send message |
| `Esc` | Interrupt the running agent. Drops any partial response from the conversation, keeps your last user message, and re-enables input so you can steer or retry. |
| `Ctrl+X` | Quit |

### Commands

| Command | Action |
|---|---|
| `/clear` | Reset the conversation back to just the system prompt and delete the saved session file. Useful when the context gets long, expensive, or off-track. |
| `/export [filename]` | Write the current conversation to Markdown. If no filename is provided, exports to `conversation.md`. |

### Example prompts

**Explore a codebase**
```
What files are in this project and what does each one do?
```

**Read and explain code**
```
Read app/agent.py and explain how the streaming loop works
```

**Make a change**
```
Add error handling to the Bash tool so it returns the exit code alongside the output
```

**Run commands**
```
Run the tests and tell me if anything is failing
```

**Multi-step tasks**
```
Find all TODO comments in the codebase, then create a TODO.md that lists them by file
```

---

## Configuration

Drop an optional `.agent_config.json` in the project root to tune permission prompts:

```json
{
  "auto_allow": ["git push", "pytest", "uv run"]
}
```

`auto_allow` is a list of **whole-word prefixes**. A command is allowed without prompting if its leading tokens match one of these prefixes (word-bounded — `chm` will NOT match `chmod`). With no config file or an empty list, the built-in risky list is the only thing that prompts.

The built-in risky list (always prompts unless overridden by `auto_allow`):
`rm`, `rmdir`, `git push`, `git reset --hard`, `git checkout --`, `git clean -f*`, `sudo`, `shutdown`, `reboot`, `halt`, `mkfs`, `dd`, `chmod`, `chown`, `kill`, `killall`, `pkill`, `npm publish`, `pip uninstall`, `uv remove`, plus any `... | sh|bash|zsh|fish` pipe.

For `Write` and `Edit`, any `file_path` that resolves outside the current working directory also prompts.

---

## Model

The agent uses `anthropic/claude-haiku-4.5` via OpenRouter by default. To change the model, edit the `model` field in `app/agent.py`:

```python
model="anthropic/claude-sonnet-4-5",  # more capable, higher cost
```

Any OpenAI-compatible model available on OpenRouter will work.

---

## Project structure

```
app/
  main.py      # entry point — launches the Textual app
  tui.py       # Textual App, layout, streaming callbacks, /clear handling
  agent.py     # async agent loop, OpenRouter streaming, tool dispatch
  tools.py     # Read, Write, Edit, Bash, Glob, Grep implementations + tool schemas
  config.py    # system prompt + working-directory / project-type injection
  session.py   # save/load/clear sessions and export conversations to Markdown
  format.py    # UI-agnostic formatting helpers (usage / cost line)
  permissions.py    # risky-pattern detection, auto-allow config, .agent_config.json loader
  widgets.py        # ToolBlock / ToolToggle widgets + build_tool_body (diff/syntax/exit rendering)
```

---

## Limitations

- Tool output shows the first 15 lines by default; click `▸ show N more lines` to expand. `Read` and `Bash` results are capped at 50KB before display and model context to avoid terminal freezes.
- No parallel tool execution — tools run sequentially
- Session file is per-directory — launching the agent from a different cwd starts a fresh conversation
- `Esc` only takes effect at the next `await` — if the agent is blocked inside a long-running synchronous tool call (e.g. a slow `Bash` command), the interrupt waits until that tool returns
- Permission gates are a **guardrail, not a sandbox**: the heuristic checks the leading tokens of each pipeline segment, so `python -c "import os; os.remove(...)"`, `xargs rm`, `eval "$risky"`, and other obfuscations slip through. The point is to catch obvious foot-guns, not stop a determined attacker
- `.agent_config.json` is read on every tool call but the system prompt is captured at startup, so cwd changes mid-session require a restart
