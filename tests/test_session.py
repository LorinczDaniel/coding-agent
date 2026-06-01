import json
from pathlib import Path

from app.session import (
    _sessions_dir,
    _validate_name,
    save_session,
    load_session,
    clear_session,
    list_sessions,
    conversation_to_markdown,
    export_conversation,
    DEFAULT_SESSION,
)


def test_validate_name_valid():
    assert _validate_name("feature-x") is None
    assert _validate_name("bug_triage") is None
    assert _validate_name("session1") is None


def test_validate_name_empty():
    assert _validate_name("") is not None


def test_validate_name_invalid_chars():
    assert _validate_name("has spaces") is not None
    assert _validate_name("a/b") is not None
    assert _validate_name("a.b") is not None


def test_sessions_dir_uses_cwd_hash(tmp_path):
    d1 = _sessions_dir(tmp_path / "project-a")
    d2 = _sessions_dir(tmp_path / "project-b")
    assert d1 != d2
    assert d1.parent == d2.parent  # both under ~/.claude-agent/sessions


def test_sessions_dir_deterministic(tmp_path):
    assert _sessions_dir(tmp_path) == _sessions_dir(tmp_path)


def test_save_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    msgs = [{"role": "system", "content": "hello"}]
    save_session(msgs, "test-sess")
    loaded = load_session("test-sess")
    assert loaded == msgs


def test_load_nonexistent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    assert load_session("nope") is None


def test_load_corrupt_json(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    assert load_session("bad") is None


def test_load_empty_list(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    (tmp_path / "empty.json").write_text("[]", encoding="utf-8")
    assert load_session("empty") is None


def test_clear_session(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "hi"}], "doomed")
    assert (tmp_path / "doomed.json").exists()
    clear_session("doomed")
    assert not (tmp_path / "doomed.json").exists()


def test_clear_nonexistent(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    clear_session("ghost")  # should not raise


def test_list_sessions_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path / "nope")
    assert list_sessions() == []


def test_list_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "a"}], "beta")
    save_session([{"role": "user", "content": "b"}], "alpha")
    names = list_sessions()
    assert names == ["alpha", "beta"]


def test_default_session_name():
    assert DEFAULT_SESSION == "default"


def test_save_load_default_name(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    msgs = [{"role": "system", "content": "sys"}]
    save_session(msgs)
    assert load_session() == msgs
    assert (tmp_path / "default.json").exists()


def test_clear_removes_specific_session(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "a"}], "keep")
    save_session([{"role": "user", "content": "b"}], "remove")
    assert list_sessions() == ["keep", "remove"]
    clear_session("remove")
    assert list_sessions() == ["keep"]
    assert load_session("keep") is not None


def test_conversation_to_markdown_filters_tools_and_system():
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "Please inspect app.py"},
        {
            "role": "assistant",
            "content": "I'll inspect it.",
            "tool_calls": [{"function": {"name": "Read"}}],
        },
        {"role": "tool", "content": "SECRET RAW TOOL OUTPUT"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1"}]},
        {"role": "assistant", "content": "The issue is fixed."},
    ]

    markdown = conversation_to_markdown(messages)

    assert markdown == (
        "# Conversation Export\n\n"
        "## User\n\n"
        "Please inspect app.py\n\n"
        "## Agent\n\n"
        "I'll inspect it.\n\n"
        "## Agent\n\n"
        "The issue is fixed.\n"
    )
    assert "system prompt" not in markdown
    assert "SECRET RAW TOOL OUTPUT" not in markdown
    assert "tool_calls" not in markdown
    assert "call_1" not in markdown


def test_export_conversation_writes_markdown_file(tmp_path):
    messages = [
        {"role": "user", "content": "Document this"},
        {"role": "assistant", "content": "Done"},
        {"role": "tool", "content": "raw output"},
    ]

    path = export_conversation(messages, tmp_path / "shared-chat")

    assert path == tmp_path / "shared-chat.md"
    assert path.read_text(encoding="utf-8") == (
        "# Conversation Export\n\n"
        "## User\n\n"
        "Document this\n\n"
        "## Agent\n\n"
        "Done\n"
    )
