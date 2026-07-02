"""Skill discovery and loading.

A skill is a reusable instruction pack: a `SKILL.md` file with a small
frontmatter block (name + description) followed by markdown instructions.
The available skills are advertised in the system prompt; the agent loads
one on demand with the Skill tool and follows its instructions.

Skills are discovered from `skills/<name>/SKILL.md` and
`.claude-agent/skills/<name>/SKILL.md` under the working directory.
"""

import re
from dataclasses import dataclass
from pathlib import Path

SKILL_DIRS = ("skills", ".claude-agent/skills")
_FRONTMATTER_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    body: str


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """Split '---\\nkey: value\\n---\\nbody' into (fields, body)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body = "\n".join(lines[index + 1:]).strip()
            return fields, body
        match = _FRONTMATTER_KEY.match(line.strip())
        if match:
            fields[match.group(1).lower()] = match.group(2).strip()
    return None


def load_skill_file(path: Path) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    parsed = _parse_frontmatter(text)
    if parsed is None:
        return None
    fields, body = parsed
    name = fields.get("name") or path.parent.name
    description = fields.get("description", "")
    if not name or not description or not body:
        return None
    return Skill(name=name, description=description, path=path, body=body)


def discover_skills(cwd: Path | None = None) -> list[Skill]:
    base = cwd or Path.cwd()
    found: dict[str, Skill] = {}
    for rel in SKILL_DIRS:
        root = base / rel
        if not root.is_dir():
            continue
        for skill_md in sorted(root.glob("*/SKILL.md")):
            skill = load_skill_file(skill_md)
            if skill is not None and skill.name not in found:
                found[skill.name] = skill
    return [found[name] for name in sorted(found)]


def get_skill(name: str, cwd: Path | None = None) -> Skill | None:
    for skill in discover_skills(cwd):
        if skill.name == name:
            return skill
    return None


def skills_prompt_section(skills: list[Skill]) -> str:
    lines = [f"- {skill.name}: {skill.description}" for skill in skills]
    return (
        "Skills are reusable instruction packs for specific kinds of tasks. "
        "When a task matches a skill's description, call the Skill tool with "
        "its name BEFORE starting, then follow the loaded instructions.\n"
        "Available skills:\n" + "\n".join(lines)
    )
