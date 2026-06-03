from pathlib import Path

from .agents import DEFAULT_PROFILE, get_profile

_BASE_PROMPT = """\
You are a coding assistant running in a terminal. You have access to these tools:

- **Read** — read the full contents of a file
- **Write** — create a new file or fully overwrite one
- **Edit** — replace an exact string in an existing file (preferred for modifications)
- **Bash** — execute a shell command and return its output
- **Glob** — find files matching a pattern
- **Grep** — search file contents with a regex

Guidelines:
- Read relevant files before making changes
- Prefer Edit over Write when modifying an existing file — only fall back to Write for new files or full rewrites
- For Edit, `old_string` must match exactly (whitespace counts); include enough surrounding context to make it unique
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


def load_system_prompt(profile_name: str = DEFAULT_PROFILE) -> str:
    cwd = Path.cwd()
    context = f"You are working in `{cwd}`, {_detect_project_type(cwd)}."
    profile = get_profile(profile_name)
    parts = [_BASE_PROMPT, context]

    custom_path = Path("system.md")
    if custom_path.exists():
        try:
            custom = custom_path.read_text(encoding="utf-8").strip()
        except OSError as e:
            raise RuntimeError(f"Could not read system.md: {e}") from e
        if custom:
            parts.append(custom)

    if profile.system_addendum:
        parts.append(profile.system_addendum.strip())

    return "\n\n".join(parts)
