import pytest
from app.config import _BASE_PROMPT, load_system_prompt


def test_no_system_md_returns_base(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_system_prompt() == _BASE_PROMPT


def test_with_system_md_appends_custom(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "system.md").write_text("Be concise.", encoding="utf-8")
    result = load_system_prompt()
    assert result == f"{_BASE_PROMPT}\n\nBe concise."


def test_base_always_present_when_system_md_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "system.md").write_text("Custom.", encoding="utf-8")
    assert load_system_prompt().startswith(_BASE_PROMPT)


def test_unreadable_system_md_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    system_md = tmp_path / "system.md"
    system_md.write_text("content", encoding="utf-8")
    system_md.chmod(0o000)
    try:
        with pytest.raises(RuntimeError, match="Could not read system.md"):
            load_system_prompt()
    finally:
        system_md.chmod(0o644)
