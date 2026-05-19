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
```

---

## Limitations

- Tool output is capped at 15 lines in the UI (full output is still sent to the model)
- No parallel tool execution — tools run sequentially
- Session file is per-directory — launching the agent from a different cwd starts a fresh conversation
