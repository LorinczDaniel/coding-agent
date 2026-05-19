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
| **Bash** | Runs any shell command and returns stdout + stderr |
| **Glob** | Finds files matching a glob pattern (e.g. `**/*.py`) |
| **Grep** | Searches file contents with a regex |

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
  └──────────────────────────────────────
  ```
- **Markdown rendering** — bold, inline code, and other formatting renders properly in the terminal
- **Multi-turn conversation** — the full message history is kept in memory for the session, so you can follow up, correct, or ask for more
- **Session persistence** — conversation history is auto-saved to `.agent_session.json` in the working directory after every agent turn, and auto-loaded on startup. Quit and relaunch and the agent picks up where you left off.
- **Token + cost tracking** — a status bar above the input shows lifetime tokens in / out and total spend in USD, updated after every agent turn (e.g. `session: ↑ 12,400 · ↓ 3,100 · $0.0420`). Cost is computed by OpenRouter at the model's current rate, so no hardcoded pricing to maintain. Totals persist through `/clear` (the dollars don't refund) and reset only on app restart.
- **Tool permission gates** — before the agent runs a destructive `Bash` command (`rm`, `git push`, `sudo`, `chmod`, `... | sh`, etc.) or a `Write` / `Edit` that targets a path outside the current working directory, a yellow confirmation modal pops up. Press `y` to approve, `n` (or `Esc`) to deny — denying tells the model "user denied this; do not retry" so it adapts instead of looping.

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
  session.py   # save/load/clear the .agent_session.json conversation file
  format.py    # UI-agnostic formatting helpers (usage / cost line)
  permissions.py    # risky-pattern detection, auto-allow config, .agent_config.json loader
  confirm_modal.py  # Textual ModalScreen for tool-call y/n confirmation
```

---

## Limitations

- Tool output is capped at 15 lines in the UI (full output is still sent to the model)
- No parallel tool execution — tools run sequentially
- Session file is per-directory — launching the agent from a different cwd starts a fresh conversation
- `Esc` only takes effect at the next `await` — if the agent is blocked inside a long-running synchronous tool call (e.g. a slow `Bash` command), the interrupt waits until that tool returns
- Permission gates are a **guardrail, not a sandbox**: the heuristic checks the leading tokens of each pipeline segment, so `python -c "import os; os.remove(...)"`, `xargs rm`, `eval "$risky"`, and other obfuscations slip through. The point is to catch obvious foot-guns, not stop a determined attacker
- `.agent_config.json` is read on every tool call but the system prompt is captured at startup, so cwd changes mid-session require a restart
