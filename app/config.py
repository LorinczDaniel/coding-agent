from pathlib import Path

from .agents import DEFAULT_PROFILE, get_profile
from .skills import discover_skills, skills_prompt_section
from .tools import TOOL_REGISTRY

_BASE_PROMPT = """\
You are a coding assistant running in a terminal.

Guidelines:
- Read relevant files before making changes
- Prefer Edit over Write when modifying an existing file — only fall back to Write for new files or full rewrites
- For Edit, `old_string` must match exactly (whitespace counts); include enough surrounding context to make it unique
- After completing a task, briefly explain what you did and why\
"""


def _tool_summary(name: str) -> str:
    description = TOOL_REGISTRY[name].schema["function"]["description"]
    return description.split(". ")[0].rstrip(".")


def _tools_section(allowed_tools: tuple[str, ...]) -> str:
    lines = [
        f"- **{name}** — {_tool_summary(name)}"
        for name in allowed_tools
        if name in TOOL_REGISTRY
    ]
    if not lines:
        return "You have no tools available; answer from knowledge alone."
    return "You have access to these tools:\n" + "\n".join(lines)


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
    parts = [_BASE_PROMPT, _tools_section(profile.allowed_tools), context]

    if "Skill" in profile.allowed_tools:
        skills = discover_skills(cwd)
        if skills:
            parts.append(skills_prompt_section(skills))

    custom_path = Path("system.md")
    if custom_path.exists():
        try:
            custom = custom_path.read_text(encoding="utf-8").strip()
        except OSError:
            custom = ""
        if custom:
            parts.append(custom)

    if profile.system_addendum:
        parts.append(profile.system_addendum.strip())

    return "\n\n".join(parts)
