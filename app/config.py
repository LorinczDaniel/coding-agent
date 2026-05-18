from pathlib import Path

_BASE_PROMPT = """\
You are a coding assistant running in a terminal. You have access to three tools:

- **Read** — read the full contents of a file
- **Write** — create or overwrite a file with new content
- **Bash** — execute a shell command and return its output

Guidelines:
- Read relevant files before making changes
- Make targeted, minimal edits — don't rewrite what doesn't need to change
- After completing a task, briefly explain what you did and why\
"""


def load_system_prompt() -> str:
    custom_path = Path("system.md")
    if not custom_path.exists():
        return _BASE_PROMPT
    try:
        custom = custom_path.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise RuntimeError(f"Could not read system.md: {e}") from e
    return f"{_BASE_PROMPT}\n\n{custom}"
