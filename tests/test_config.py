import pytest
from unittest.mock import patch
from app.agents import COACH_SYSTEM_ADDENDUM
from app.config import _BASE_PROMPT, _detect_project_type, load_system_prompt


def test_no_system_md_returns_base_with_cwd_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = load_system_prompt()
    assert result.startswith(_BASE_PROMPT)
    assert str(tmp_path) in result
    assert COACH_SYSTEM_ADDENDUM.strip() in result


def test_with_system_md_includes_custom_before_coach_addendum(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "system.md").write_text("Be concise.", encoding="utf-8")
    result = load_system_prompt()
    assert result.startswith(_BASE_PROMPT)
    assert result.index("Be concise.") < result.index(COACH_SYSTEM_ADDENDUM.strip())
    assert result.endswith(COACH_SYSTEM_ADDENDUM.strip())
    assert str(tmp_path) in result


def test_base_always_present_when_system_md_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "system.md").write_text("Custom.", encoding="utf-8")
    assert load_system_prompt().startswith(_BASE_PROMPT)


def test_load_system_prompt_rejects_unknown_profile(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="Unknown agent profile: missing"):
        load_system_prompt("missing")


def test_unreadable_system_md_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "system.md").write_text("content", encoding="utf-8")
    with patch("pathlib.Path.read_text", side_effect=OSError("permission denied")):
        with pytest.raises(RuntimeError, match="Could not read system.md"):
            load_system_prompt()


def test_detect_python_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    assert _detect_project_type(tmp_path) == "a Python project"


def test_detect_node_project(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert _detect_project_type(tmp_path) == "a Node.js/JavaScript project"


def test_detect_unknown_project(tmp_path):
    assert _detect_project_type(tmp_path) == "a project"
