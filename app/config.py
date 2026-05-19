from pathlib import Path

_BASE_PROMPT = """\
You are a coding assistant running in a terminal. You have access to these tools:

- **Read** — read the full contents of a file
- **Write** — create or overwrite a file with new content
- **Bash** — execute a shell command and return its output
- **Glob** — find files matching a pattern
- **Grep** — search file contents with a regex

Guidelines:
- Read relevant files before making changes
- Make targeted, minimal edits — don't rewrite what doesn't need to change
- After completing a task, briefly explain what you did and why\
"""


def _detect_project_type(cwd: Path) -> str:
    if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists() or (cwd / "requirements.txt").exists():
        return "a Python project"
    if (cwd / "package.json").exists():
        return "a Node.js/JavaScript project"
    if (cwd / "Cargo.toml").exists():
        return "a Rust project"
    if (cwd / "go.mod").exists():
        return "a Go project"
    if (cwd / "pom.xml").exists() or (cwd / "build.gradle").exists():
        return "a Java project"
    return "a project"


def load_system_prompt() -> str:
    cwd = Path.cwd()
    context = f"You are working in `{cwd}`, {_detect_project_type(cwd)}."
    base = f"{_BASE_PROMPT}\n\n{context}"

    custom_path = Path("system.md")
    if not custom_path.exists():
        return base
    try:
        custom = custom_path.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise RuntimeError(f"Could not read system.md: {e}") from e
    return f"{base}\n\n{custom}"
