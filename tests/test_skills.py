from pathlib import Path

from app.config import load_system_prompt
from app.skills import (
    Skill,
    discover_skills,
    get_skill,
    load_skill_file,
    skills_prompt_section,
)
from app.tools import execute_tool


def _write_skill(root: Path, name: str, description: str = "Does something useful.", body: str = "Follow these steps.") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


# --- parsing ---

def test_load_skill_file_parses_frontmatter(tmp_path):
    path = _write_skill(tmp_path / "skills", "review")

    skill = load_skill_file(path)

    assert skill == Skill(
        name="review",
        description="Does something useful.",
        path=path,
        body="Follow these steps.",
    )


def test_load_skill_file_name_falls_back_to_directory(tmp_path):
    skill_dir = tmp_path / "skills" / "deploy"
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text("---\ndescription: Deploys things.\n---\nbody\n", encoding="utf-8")

    skill = load_skill_file(path)

    assert skill is not None
    assert skill.name == "deploy"


def test_load_skill_file_rejects_missing_frontmatter(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("just markdown, no frontmatter\n", encoding="utf-8")
    assert load_skill_file(path) is None


def test_load_skill_file_rejects_missing_description(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: x\n---\nbody\n", encoding="utf-8")
    assert load_skill_file(path) is None


def test_load_skill_file_rejects_empty_body(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: x\ndescription: y\n---\n\n", encoding="utf-8")
    assert load_skill_file(path) is None


def test_load_skill_file_rejects_unterminated_frontmatter(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: x\ndescription: y\nbody without closing\n", encoding="utf-8")
    assert load_skill_file(path) is None


# --- discovery ---

def test_discover_skills_finds_both_roots(tmp_path):
    _write_skill(tmp_path / "skills", "alpha")
    _write_skill(tmp_path / ".claude-agent" / "skills", "beta")

    names = [skill.name for skill in discover_skills(tmp_path)]

    assert names == ["alpha", "beta"]


def test_discover_skills_project_dir_wins_on_name_clash(tmp_path):
    _write_skill(tmp_path / "skills", "alpha", description="project version")
    _write_skill(tmp_path / ".claude-agent" / "skills", "alpha", description="local version")

    skills = discover_skills(tmp_path)

    assert len(skills) == 1
    assert skills[0].description == "project version"


def test_discover_skills_empty_when_no_dirs(tmp_path):
    assert discover_skills(tmp_path) == []


def test_get_skill_by_name(tmp_path):
    _write_skill(tmp_path / "skills", "alpha")
    assert get_skill("alpha", tmp_path) is not None
    assert get_skill("missing", tmp_path) is None


# --- prompt section ---

def test_skills_prompt_section_lists_names_and_descriptions(tmp_path):
    path = _write_skill(tmp_path / "skills", "review", description="Reviews code.")
    section = skills_prompt_section([load_skill_file(path)])

    assert "- review: Reviews code." in section
    assert "Skill tool" in section


def test_system_prompt_advertises_skills(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_skill(tmp_path / "skills", "review", description="Reviews code.")

    prompt = load_system_prompt("coach")

    assert "- review: Reviews code." in prompt


def test_system_prompt_omits_skills_without_skill_tool(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_skill(tmp_path / "skills", "review", description="Reviews code.")
    from app.agents import AgentProfile, save_custom_profile

    profile = AgentProfile(
        name="no-skill",
        title="No Skill",
        description="Profile without the Skill tool.",
        allowed_tools=("Read",),
        system_addendum="Just read.",
    )
    assert save_custom_profile(profile) is None

    prompt = load_system_prompt("no-skill")

    assert "review: Reviews code." not in prompt


# --- Skill tool ---

def test_skill_tool_returns_body(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_skill(tmp_path / "skills", "review", body="Step one. Step two.")

    result = execute_tool("Skill", {"name": "review"})

    assert result.startswith("# Skill: review")
    assert "Step one. Step two." in result


def test_skill_tool_unknown_name_lists_available(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_skill(tmp_path / "skills", "review")

    result = execute_tool("Skill", {"name": "nope"})

    assert result.startswith("Error: unknown skill: nope")
    assert "review" in result
