import json

from app.session import (
    DEFAULT_SESSION,
    LessonState,
    _sessions_dir,
    clear_lesson,
    clear_session,
    conversation_to_markdown,
    export_conversation,
    list_sessions,
    load_lesson,
    load_session,
    load_session_profile,
    rename_session,
    save_lesson,
    save_session,
    save_session_profile,
    session_exists,
    validate_session_name,
)


def test_validate_name_valid():
    assert validate_session_name("feature-x") is None
    assert validate_session_name("bug_triage") is None
    assert validate_session_name("session1") is None


def test_validate_name_empty():
    assert validate_session_name("") is not None


def test_validate_name_invalid_chars():
    assert validate_session_name("has spaces") is not None
    assert validate_session_name("a/b") is not None
    assert validate_session_name("a.b") is not None


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


def test_load_corrupt_json_quarantines_file(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    assert load_session("bad") is None
    assert not (tmp_path / "bad.json").exists()
    assert (tmp_path / "bad.json.corrupt").read_text(encoding="utf-8") == "not json"


def test_load_rejects_non_message_elements(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    (tmp_path / "weird.json").write_text(json.dumps(["x", 5]), encoding="utf-8")
    assert load_session("weird") is None
    assert (tmp_path / "weird.json.corrupt").exists()


def test_session_exists(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    assert session_exists("live") is False
    save_session([{"role": "user", "content": "hi"}], "live")
    assert session_exists("live") is True


def test_save_and_load_session_profile(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    assert load_session_profile("s") is None
    assert save_session_profile("mentor", "s") is None
    assert load_session_profile("s") == "mentor"


def test_clear_session_removes_profile_meta(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "hi"}], "s")
    save_session_profile("mentor", "s")
    clear_session("s")
    assert load_session_profile("s") is None


def test_rename_session_moves_profile_meta(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "hi"}], "old")
    save_session_profile("mentor", "old")
    assert rename_session("old", "new") is None
    assert load_session_profile("new") == "mentor"
    assert load_session_profile("old") is None


def test_meta_sidecar_excluded_from_list_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "hi"}], "live")
    save_session_profile("coach", "live")
    assert list_sessions() == ["live"]


def test_save_session_reports_write_failure(tmp_path, monkeypatch):
    target = tmp_path / "blocked"
    target.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: target)
    err = save_session([{"role": "user", "content": "hi"}], "s")
    assert err is not None


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


def test_rename_session_preserves_history(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    save_session(messages, "old-name")

    err = rename_session("old-name", "new-name")

    assert err is None
    assert load_session("old-name") is None
    assert load_session("new-name") == messages
    assert list_sessions() == ["new-name"]


def test_rename_session_refuses_existing_target(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "old"}], "old")
    save_session([{"role": "user", "content": "target"}], "target")

    err = rename_session("old", "target")
    assert err == "Session 'target' already exists."
    assert load_session("old") == [{"role": "user", "content": "old"}]
    assert load_session("target") == [{"role": "user", "content": "target"}]


def test_rename_session_missing_source(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)

    err = rename_session("missing", "new-name")
    assert err == "Session 'missing' not found."


def test_rename_session_invalid_name(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "old"}], "old")

    err = rename_session("old", "new name")
    assert err == "Session name must contain only letters, digits, hyphens, and underscores."
    assert load_session("old") is not None


def test_rename_session_same_name(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "old"}], "same")

    err = rename_session("same", "same")
    assert err == "New session name must be different."
    assert load_session("same") is not None


def test_save_and_load_lesson(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    state = LessonState(goal="redis", milestones=("parse RESP", "store keys"), current_index=1)

    save_lesson(state, "lesson-sess")

    assert (tmp_path / "lesson-sess.lesson.json").exists()
    assert load_lesson("lesson-sess") == state


def test_load_lesson_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    assert load_lesson("nope") is None


def test_load_lesson_corrupt_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    (tmp_path / "broken.lesson.json").write_text("{not json", encoding="utf-8")
    assert load_lesson("broken") is None


def test_load_lesson_rejects_missing_goal(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    (tmp_path / "bad.lesson.json").write_text(json.dumps({"milestones": []}), encoding="utf-8")
    assert load_lesson("bad") is None


def test_lesson_state_defaults():
    state = LessonState(goal="grep")
    assert state.milestones == ()
    assert state.current_index == 0
    assert state.hint_level == 0
    assert LessonState.from_dict(state.to_dict()) == state


def test_lesson_escalated_increments_and_clamps():
    state = LessonState(goal="grep")
    state = state.escalated(4)
    assert state.hint_level == 1
    state = state.escalated(4).escalated(4).escalated(4)
    assert state.hint_level == 4
    assert state.escalated(4).hint_level == 4


def test_lesson_with_task_resets_hint_level():
    state = LessonState(goal="grep", current_index=0, hint_level=3)
    advanced = state.with_task(1)
    assert advanced.current_index == 1
    assert advanced.hint_level == 0


def test_lesson_state_ignores_invalid_hint_level(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    (tmp_path / "bad.lesson.json").write_text(
        json.dumps({"goal": "grep", "hint_level": -5}), encoding="utf-8"
    )
    assert load_lesson("bad").hint_level == 0


def test_clear_lesson_removes_only_lesson(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "hi"}], "live")
    save_lesson(LessonState(goal="grep"), "live")

    clear_lesson("live")

    assert load_lesson("live") is None
    assert load_session("live") is not None


def test_clear_session_also_clears_lesson(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "hi"}], "live")
    save_lesson(LessonState(goal="grep"), "live")

    clear_session("live")

    assert load_lesson("live") is None
    assert load_session("live") is None


def test_lesson_sidecar_excluded_from_list_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "hi"}], "live")
    save_lesson(LessonState(goal="grep"), "live")

    assert list_sessions() == ["live"]


def test_rename_session_moves_lesson(tmp_path, monkeypatch):
    monkeypatch.setattr("app.session._sessions_dir", lambda cwd=None: tmp_path)
    save_session([{"role": "user", "content": "hi"}], "old")
    save_lesson(LessonState(goal="grep", current_index=2), "old")

    err = rename_session("old", "new")

    assert err is None
    assert load_lesson("old") is None
    assert load_lesson("new") == LessonState(goal="grep", current_index=2)


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
