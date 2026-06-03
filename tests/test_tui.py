from app.agents import COACH_PROFILE, DEFAULT_PROFILE, AgentProfile, get_profile, save_custom_profile
from app.format import format_usage
from app.tui import (
    AgentApp, CONTEXT_WINDOWS, MODELS,
    _learn_goal_prompt, _refresh_system_prompt, _session_transcript,
)


class DummyInput:
    def __init__(self):
        self.value = ""


class DummyContainer:
    def __init__(self):
        self.removed = False

    def remove_children(self):
        self.removed = True


class DummyUsageBar:
    def __init__(self):
        self.value = None

    def update(self, value):
        self.value = value


def _rendered_text(widget) -> str:
    renderable = getattr(widget, "content", "")
    return renderable.plain if hasattr(renderable, "plain") else str(renderable)


def _make_app():
    app = AgentApp()
    app._model = "haiku"
    app._agent_profile = DEFAULT_PROFILE
    app._session_name = "default"
    app._messages = [{"role": "system", "content": "sys"}]
    app._history = []
    app._history_index = 0
    app._history_draft = ""
    app._pending_confirm = None
    app._pending_agent_create = None
    app._current_tool_block = None
    app._total_in = 1234
    app._total_out = 567
    app._total_cost = 0.42
    return app


def _custom_profile(name: str = "reviewer") -> AgentProfile:
    return AgentProfile(
        name=name,
        title="Code Reviewer",
        description="Reviews code changes.",
        allowed_tools=("Read", "Grep"),
        system_addendum="Review the code and report risks first.",
    )


def test_reset_usage_clears_counters_and_updates_bar(monkeypatch):
    app = _make_app()
    usage_bar = DummyUsageBar()
    monkeypatch.setattr(app, "query_one", lambda *args: usage_bar)

    app._reset_usage()

    assert app._total_in == 0
    assert app._total_out == 0
    assert app._total_cost == 0.0
    assert usage_bar.value == format_usage(
        0,
        0,
        0.0,
        "haiku",
        CONTEXT_WINDOWS[MODELS["haiku"]],
        "coach",
    )


def test_clear_resets_usage(monkeypatch):
    app = _make_app()
    container = DummyContainer()
    input_widget = DummyInput()
    reset_calls = []

    monkeypatch.setattr(app, "query_one", lambda *args: input_widget)
    monkeypatch.setattr(app, "_container", lambda: container)
    monkeypatch.setattr(app, "_append_sync", lambda widget: None)
    monkeypatch.setattr(app, "_reset_usage", lambda: reset_calls.append(True))
    monkeypatch.setattr("app.tui.clear_session", lambda name: None)
    monkeypatch.setattr("app.tui.load_system_prompt", lambda profile_name=DEFAULT_PROFILE: f"new system {profile_name}")

    app._send("/clear")

    assert reset_calls == [True]
    assert container.removed is True
    assert app._messages == [{"role": "system", "content": "new system coach"}]
    assert app._history == []
    assert app._history_index == 0


def test_sessions_new_resets_usage(monkeypatch):
    app = _make_app()
    container = DummyContainer()
    reset_calls = []

    monkeypatch.setattr(app, "_container", lambda: container)
    monkeypatch.setattr(app, "_append_sync", lambda widget: None)
    monkeypatch.setattr(app, "_reset_usage", lambda: reset_calls.append(True))
    monkeypatch.setattr("app.tui.load_session", lambda name: None)
    monkeypatch.setattr("app.tui.save_session", lambda messages, name: None)
    monkeypatch.setattr("app.tui.load_system_prompt", lambda profile_name=DEFAULT_PROFILE: f"new system {profile_name}")

    app._handle_sessions_command("/sessions new fresh")

    assert reset_calls == [True]
    assert container.removed is True
    assert app._session_name == "fresh"
    assert app._messages == [{"role": "system", "content": "new system coach"}]
    assert app._history == []
    assert app._history_index == 0


def test_sessions_load_resets_usage(monkeypatch):
    app = _make_app()
    container = DummyContainer()
    reset_calls = []
    replayed = []
    saved = [
        {"role": "system", "content": "saved system"},
        {"role": "user", "content": "hello"},
    ]

    monkeypatch.setattr(app, "_container", lambda: container)
    monkeypatch.setattr(app, "_append_sync", lambda widget: None)
    monkeypatch.setattr(app, "_reset_usage", lambda: reset_calls.append(True))
    monkeypatch.setattr(app, "_append_session_transcript", lambda messages: replayed.append(messages))
    monkeypatch.setattr("app.tui.load_session", lambda name: saved)
    monkeypatch.setattr("app.tui.save_session", lambda messages, name: None)
    monkeypatch.setattr("app.tui.load_system_prompt", lambda profile_name=DEFAULT_PROFILE: f"new {profile_name} system")

    app._handle_sessions_command("/sessions load saved")

    assert reset_calls == [True]
    assert container.removed is True
    assert app._session_name == "saved"
    assert app._messages == [
        {"role": "system", "content": "new coach system"},
        {"role": "user", "content": "hello"},
    ]
    assert app._history == ["hello"]
    assert app._history_index == 1
    assert replayed == [app._messages]


def test_help_includes_agent_command(monkeypatch):
    app = _make_app()
    input_widget = DummyInput()
    appended = []

    monkeypatch.setattr(app, "query_one", lambda *args: input_widget)
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._send("/help")

    assert any("/agent [name]" in _rendered_text(widget) for widget in appended)
    assert any("/agent create [name]" in _rendered_text(widget) for widget in appended)
    assert any("/learn <thing>" in _rendered_text(widget) for widget in appended)


def test_learn_help_shows_examples(monkeypatch):
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_learn_command("/learn help")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "/learn redis" in text
    assert "/learn grep" in text
    assert "/learn http server" in text


def test_empty_learn_shows_usage(monkeypatch):
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_learn_command("/learn")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "Usage: /learn <thing>" in text
    assert "/learn redis" in text


def test_learn_goal_switches_to_coach_and_starts_fresh(monkeypatch):
    app = _make_app()
    container = DummyContainer()
    input_widget = DummyInput()
    appended = []
    saved = []
    reset_calls = []
    run_calls = []
    app._agent_profile = "other"
    app._messages = [
        {"role": "system", "content": "old system"},
        {"role": "user", "content": "old question"},
    ]
    app._history = ["old question"]
    app._history_index = 1

    monkeypatch.setattr(app, "query_one", lambda *args: input_widget)
    monkeypatch.setattr(app, "_container", lambda: container)
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))
    monkeypatch.setattr(app, "_reset_usage", lambda: reset_calls.append(True))
    monkeypatch.setattr(app, "_run_agent", lambda: run_calls.append(True))
    monkeypatch.setattr("app.tui.save_session", lambda messages, name: saved.append((messages, name)))
    monkeypatch.setattr("app.tui.load_system_prompt", lambda profile_name=DEFAULT_PROFILE: f"system {profile_name}")

    app._handle_learn_command("/learn redis")

    prompt = _learn_goal_prompt("redis")
    assert saved == [([
        {"role": "system", "content": "old system"},
        {"role": "user", "content": "old question"},
    ], "default")]
    assert app._agent_profile == COACH_PROFILE
    assert app._messages == [
        {"role": "system", "content": "system coach"},
        {"role": "user", "content": prompt},
    ]
    assert "5-10 small milestones" in prompt
    assert "task 1" in prompt
    assert app._history == [prompt]
    assert app._history_index == 1
    assert container.removed is True
    assert reset_calls == [True]
    assert run_calls == [True]
    assert input_widget.disabled is True
    assert any("Learning goal: redis" in _rendered_text(widget) for widget in appended)


def test_agent_command_lists_current_and_available(monkeypatch):
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent")

    texts = [_rendered_text(widget) for widget in appended]
    assert any("Current agent: coach" in text for text in texts)
    assert any("coach ← current" in text for text in texts)


def test_agent_command_lists_custom_profiles(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert save_custom_profile(_custom_profile()) is None
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "reviewer" in text
    assert "Reviews code changes." in text


def test_agent_help_explains_usage(monkeypatch):
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent help")

    texts = [_rendered_text(widget) for widget in appended]
    assert any("/agent" in text and "Show current agent" in text for text in texts)
    assert any("/agent <name>" in text and "Switch" in text for text in texts)
    assert any("/agent create [name]" in text and "Create" in text for text in texts)


def test_agent_create_without_name_prompts_for_name(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent create")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert app._pending_agent_create["step"] == "name"
    assert "Creating a custom agent profile" in text
    assert "Profile name" in text


def test_agent_create_prefills_name(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent create reviewer")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert app._pending_agent_create["name"] == "reviewer"
    assert app._pending_agent_create["step"] == "title"
    assert "Display title" in text


def test_agent_create_flow_saves_custom_profile(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = _make_app()
    input_widget = DummyInput()
    appended = []

    monkeypatch.setattr(app, "query_one", lambda *args: input_widget)
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._send("/agent create reviewer")
    app._send("Code Reviewer")
    app._send("Reviews code changes.")
    app._send("Read, grep")
    app._send("Review the code and report risks first.")

    profile = get_profile("reviewer")
    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert app._pending_agent_create is None
    assert profile.title == "Code Reviewer"
    assert profile.allowed_tools == ("Read", "Grep")
    assert "Created agent profile reviewer" in text
    assert "/agent reviewer" in text


def test_agent_create_reprompts_for_invalid_name(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent create")
    app._answer_agent_create("Bad Name")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert app._pending_agent_create["step"] == "name"
    assert "must start with a lowercase letter" in text
    assert text.count("Profile name") == 2


def test_agent_create_reprompts_for_invalid_tools(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent create reviewer")
    app._answer_agent_create("Code Reviewer")
    app._answer_agent_create("Reviews code changes.")
    app._answer_agent_create("Read Nope")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert app._pending_agent_create["step"] == "allowed_tools"
    assert "Unknown tool: Nope" in text
    assert "Available tools" in text


def test_agent_create_can_be_cancelled(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent create reviewer")
    app._answer_agent_create("cancel")

    assert app._pending_agent_create is None
    assert any("cancelled" in _rendered_text(widget) for widget in appended)


def test_agent_unknown_profile_shows_available_options(monkeypatch):
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent missing")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "Unknown agent: missing" in text
    assert "available:" in text
    assert "coach" in text


def test_agent_switch_saves_and_starts_fresh(monkeypatch):
    app = _make_app()
    container = DummyContainer()
    appended = []
    saved = []
    reset_calls = []
    app._messages = [
        {"role": "system", "content": "old system"},
        {"role": "user", "content": "old question"},
    ]
    app._history = ["old question"]
    app._history_index = 1

    monkeypatch.setattr(app, "_container", lambda: container)
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))
    monkeypatch.setattr(app, "_reset_usage", lambda: reset_calls.append(True))
    monkeypatch.setattr("app.tui.save_session", lambda messages, name: saved.append((messages, name)))
    monkeypatch.setattr("app.tui.load_system_prompt", lambda profile_name=DEFAULT_PROFILE: f"system {profile_name}")

    app._handle_agent_command("/agent coach")

    assert saved == [([
        {"role": "system", "content": "old system"},
        {"role": "user", "content": "old question"},
    ], "default")]
    assert app._agent_profile == "coach"
    assert app._messages == [{"role": "system", "content": "system coach"}]
    assert app._history == []
    assert app._history_index == 0
    assert container.removed is True
    assert reset_calls == [True]
    assert any("Switched to agent coach" in _rendered_text(widget) for widget in appended)


def test_agent_switches_to_custom_profile(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert save_custom_profile(_custom_profile()) is None
    app = _make_app()
    container = DummyContainer()
    usage_bar = DummyUsageBar()
    appended = []
    saved = []
    app._messages = [
        {"role": "system", "content": "old system"},
        {"role": "user", "content": "old question"},
    ]
    app._history = ["old question"]
    app._history_index = 1

    monkeypatch.setattr(app, "query_one", lambda *args: usage_bar)
    monkeypatch.setattr(app, "_container", lambda: container)
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))
    monkeypatch.setattr("app.tui.save_session", lambda messages, name: saved.append((messages, name)))
    monkeypatch.setattr("app.tui.load_system_prompt", lambda profile_name=DEFAULT_PROFILE: f"system {profile_name}")

    app._handle_agent_command("/agent reviewer")

    assert saved == [([
        {"role": "system", "content": "old system"},
        {"role": "user", "content": "old question"},
    ], "default")]
    assert app._agent_profile == "reviewer"
    assert app._messages == [{"role": "system", "content": "system reviewer"}]
    assert app._history == []
    assert app._history_index == 0
    assert container.removed is True
    assert usage_bar.value == format_usage(
        0,
        0,
        0.0,
        "haiku",
        CONTEXT_WINDOWS[MODELS["haiku"]],
        "reviewer",
    )
    assert any("Switched to agent reviewer" in _rendered_text(widget) for widget in appended)


def test_refresh_system_prompt_replaces_existing_system_message():
    messages = [
        {"role": "system", "content": "old system"},
        {"role": "user", "content": "hello"},
    ]

    assert _refresh_system_prompt(messages, "coach system") == [
        {"role": "system", "content": "coach system"},
        {"role": "user", "content": "hello"},
    ]


def test_refresh_system_prompt_inserts_missing_system_message():
    messages = [{"role": "user", "content": "hello"}]

    assert _refresh_system_prompt(messages, "coach system") == [
        {"role": "system", "content": "coach system"},
        {"role": "user", "content": "hello"},
    ]


def test_session_transcript_excludes_system_tools_and_empty_assistant_calls():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "I'll check.", "tool_calls": [{"id": "call_1"}]},
        {"role": "tool", "content": "raw tool output"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_2"}]},
        {"role": "assistant", "content": "Final answer"},
    ]

    assert _session_transcript(messages) == [
        ("user", "first question"),
        ("assistant", "I'll check."),
        ("assistant", "Final answer"),
    ]
