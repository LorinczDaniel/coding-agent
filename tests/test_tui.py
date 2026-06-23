from app.agents import COACH_PROFILE, DEFAULT_PROFILE, AgentProfile, get_profile, save_custom_profile
from app.format import format_usage
from app.tui import (
    AgentApp, CONTEXT_WINDOWS, MODELS,
    _learn_goal_prompt, _refresh_system_prompt, _session_transcript,
    MAX_HINT_LEVEL, _hint_prompt,
)
from app.session import LessonState


class DummyInput:
    def __init__(self):
        self.value = ""

    def focus(self):
        pass


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
    app._pending_agent_switch = None
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


def test_model_switch_updates_usage_bar_and_keeps_agent_label(monkeypatch):
    app = _make_app()
    input_widget = DummyInput()
    usage_bar = DummyUsageBar()
    appended = []

    def query_one(selector, *args):
        if selector == "#usage-bar":
            return usage_bar
        return input_widget

    monkeypatch.setattr(app, "query_one", query_one)
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._send("/model sonnet")

    assert app._model == "sonnet"
    assert usage_bar.value == format_usage(
        1234,
        567,
        0.42,
        "sonnet",
        CONTEXT_WINDOWS[MODELS["sonnet"]],
        "coach",
    )
    assert any("Switched to sonnet" in _rendered_text(widget) for widget in appended)


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


def test_hint_help_shows_ladder(monkeypatch):
    app = _make_app()
    appended = []
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_hint_command("/hint help")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "question" in text
    assert "nudge" in text
    assert "focused example" in text
    assert "near-solution" in text
    assert "resets" in text


def test_hint_without_lesson_prompts_to_learn(monkeypatch):
    app = _make_app()
    app._lesson = None
    appended = []
    run_calls = []
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))
    monkeypatch.setattr(app, "_run_agent", lambda: run_calls.append(True))

    app._handle_hint_command("/hint")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "No active lesson" in text
    assert run_calls == []


def test_hint_with_extra_arg_shows_usage(monkeypatch):
    app = _make_app()
    app._lesson = LessonState(goal="redis")
    appended = []
    run_calls = []
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))
    monkeypatch.setattr(app, "_run_agent", lambda: run_calls.append(True))

    app._handle_hint_command("/hint please")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "Usage: /hint" in text
    assert run_calls == []


def test_hint_escalates_level_and_runs_agent(monkeypatch):
    app = _make_app()
    app._lesson = LessonState(goal="redis")
    appended = []
    run_calls = []
    saved = []
    input_widget = DummyInput()
    monkeypatch.setattr(app, "query_one", lambda *args: input_widget)
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))
    monkeypatch.setattr(app, "_run_agent", lambda: run_calls.append(True))
    monkeypatch.setattr("app.tui.save_lesson", lambda state, name: saved.append((state, name)))

    app._handle_hint_command("/hint")

    assert app._lesson.hint_level == 1
    assert saved == [(app._lesson, "default")]
    assert app._messages[-1]["content"] == _hint_prompt(1)
    assert run_calls == [True]
    assert input_widget.disabled is True
    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "Hint 1/4" in text

    app._handle_hint_command("/hint")
    assert app._lesson.hint_level == 2
    assert app._messages[-1]["content"] == _hint_prompt(2)


def test_hint_level_clamps_at_max(monkeypatch):
    app = _make_app()
    app._lesson = LessonState(goal="redis", hint_level=MAX_HINT_LEVEL)
    monkeypatch.setattr(app, "query_one", lambda *args: DummyInput())
    monkeypatch.setattr(app, "_append_sync", lambda widget: None)
    monkeypatch.setattr(app, "_run_agent", lambda: None)
    monkeypatch.setattr("app.tui.save_lesson", lambda state, name: None)

    app._handle_hint_command("/hint")

    assert app._lesson.hint_level == MAX_HINT_LEVEL
    assert app._messages[-1]["content"] == _hint_prompt(MAX_HINT_LEVEL)


def test_new_lesson_resets_hint_level(monkeypatch):
    app = _make_app()
    app._lesson = LessonState(goal="redis", hint_level=3)
    container = DummyContainer()
    input_widget = DummyInput()
    monkeypatch.setattr(app, "query_one", lambda *args: input_widget)
    monkeypatch.setattr(app, "_container", lambda: container)
    monkeypatch.setattr(app, "_append_sync", lambda widget: None)
    monkeypatch.setattr(app, "_reset_usage", lambda: None)
    monkeypatch.setattr(app, "_run_agent", lambda: None)
    monkeypatch.setattr("app.tui.save_session", lambda messages, name: None)
    monkeypatch.setattr("app.tui.save_lesson", lambda state, name: None)
    monkeypatch.setattr("app.tui.load_system_prompt", lambda profile_name=DEFAULT_PROFILE: f"system {profile_name}")

    app._handle_learn_command("/learn grep")

    assert app._lesson.goal == "grep"
    assert app._lesson.hint_level == 0


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


def test_agent_create_rejects_multiple_name_tokens(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent create foo bar")

    assert app._pending_agent_create is None
    assert any("Usage: /agent create [name]" in _rendered_text(widget) for widget in appended)


def test_agent_create_inline_invalid_name_aborts(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent create Bad")

    assert app._pending_agent_create is None
    assert any("must start with a lowercase letter" in _rendered_text(widget) for widget in appended)


def test_agent_create_inline_existing_name_aborts(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent create coach")

    assert app._pending_agent_create is None
    assert any("built in" in _rendered_text(widget) for widget in appended)


def test_agent_create_reprompts_for_empty_title(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent create reviewer")
    app._answer_agent_create("   ")

    assert app._pending_agent_create["step"] == "title"
    assert any("title cannot be empty" in _rendered_text(widget) for widget in appended)


def test_agent_create_reprompts_for_empty_tools(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = _make_app()
    appended = []

    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent create reviewer")
    app._answer_agent_create("Code Reviewer")
    app._answer_agent_create("Reviews code changes.")
    app._answer_agent_create("")

    assert app._pending_agent_create["step"] == "allowed_tools"
    assert any("At least one allowed tool is required" in _rendered_text(widget) for widget in appended)


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

    app._handle_agent_command("/agent mentor")

    # Switch only happens after confirmation; nothing reset yet.
    assert app._pending_agent_switch == "mentor"
    assert saved == []
    assert app._agent_profile == "coach"
    assert container.removed is False
    assert any("starts a fresh conversation" in _rendered_text(widget) for widget in appended)

    app._answer_agent_switch("y")

    assert app._pending_agent_switch is None
    assert saved == [([
        {"role": "system", "content": "old system"},
        {"role": "user", "content": "old question"},
    ], "default")]
    assert app._agent_profile == "mentor"
    assert app._messages == [{"role": "system", "content": "system mentor"}]
    assert app._history == []
    assert app._history_index == 0
    assert container.removed is True
    assert reset_calls == [True]
    assert any("Switched to agent mentor" in _rendered_text(widget) for widget in appended)


def test_agent_switch_declined_keeps_current(monkeypatch):
    app = _make_app()
    container = DummyContainer()
    appended = []
    saved = []
    app._messages = [{"role": "system", "content": "old system"}]

    monkeypatch.setattr(app, "_container", lambda: container)
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))
    monkeypatch.setattr("app.tui.save_session", lambda messages, name: saved.append((messages, name)))

    app._handle_agent_command("/agent mentor")
    app._answer_agent_switch("n")

    assert app._pending_agent_switch is None
    assert app._agent_profile == "coach"
    assert app._messages == [{"role": "system", "content": "old system"}]
    assert saved == []
    assert container.removed is False
    assert any("Kept the current agent" in _rendered_text(widget) for widget in appended)


def test_agent_switch_invalid_answer_reprompts(monkeypatch):
    app = _make_app()
    appended = []
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent mentor")
    app._answer_agent_switch("maybe")

    assert app._pending_agent_switch == "mentor"
    assert any("y (switch) or n (keep current)" in _rendered_text(widget) for widget in appended)


def test_agent_switch_to_current_is_noop(monkeypatch):
    app = _make_app()
    appended = []
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_agent_command("/agent coach")

    assert app._pending_agent_switch is None
    assert any("Already using agent coach" in _rendered_text(widget) for widget in appended)


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
    app._answer_agent_switch("yes")

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


async def test_run_agent_uses_active_profile_tool_allowlist(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert save_custom_profile(_custom_profile()) is None
    app = _make_app()
    input_widget = DummyInput()
    captured = []
    saved = []
    app._agent_profile = "reviewer"

    async def fake_run_agent(*args, **kwargs):
        captured.append(kwargs["tool_allowlist"])

    monkeypatch.setattr(app, "query_one", lambda *args: input_widget)
    monkeypatch.setattr(app, "_append_sync", lambda widget: None)
    monkeypatch.setattr("app.tui.run_agent", fake_run_agent)
    monkeypatch.setattr("app.tui.save_session", lambda messages, name: saved.append((messages, name)))

    await AgentApp._run_agent.__wrapped__(app)

    assert captured == [("Read", "Grep")]
    assert saved == [(app._messages, "default")]


async def test_run_agent_hides_todowrite_chat_output_but_updates_panel(monkeypatch):
    app = _make_app()
    input_widget = DummyInput()
    panel = DummyTodoPanel()
    appended = []
    saved = []
    todos = [{"id": 1, "title": "plan next step", "status": "in-progress"}]

    async def fake_append(widget):
        appended.append(widget)

    async def fake_run_agent(
        messages,
        model,
        on_text,
        on_tool_start,
        on_tool_result,
        on_usage,
        on_tool_confirm,
        on_todo,
        **kwargs,
    ):
        await on_tool_start("TodoWrite", '{"todos": []}')
        await on_todo(todos)
        await on_tool_result(
            "TodoWrite",
            "Todo list updated:\n● plan next step",
            {"todos": todos},
        )

    def query_one(selector, *args):
        if selector == "#todo-panel":
            return panel
        return input_widget

    monkeypatch.setattr(app, "query_one", query_one)
    monkeypatch.setattr(app, "_append", fake_append)
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))
    monkeypatch.setattr("app.tui.run_agent", fake_run_agent)
    monkeypatch.setattr("app.tui.save_session", lambda messages, name: saved.append((messages, name)))

    await AgentApp._run_agent.__wrapped__(app)

    rendered = "\n".join(_rendered_text(widget) for widget in appended)
    assert "TodoWrite" not in rendered
    assert "todos=" not in rendered
    assert "Todo list updated" not in rendered
    assert panel.display is True
    assert panel.todos == todos
    assert saved == [(app._messages, "default")]


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


class DummyTodoPanel:
    def __init__(self):
        self.todos = [{"title": "task", "status": "in-progress"}]
        self.display = True


def _dispatch_app(monkeypatch, appended):
    app = _make_app()
    input_widget = DummyInput()
    monkeypatch.setattr(app, "query_one", lambda *args: input_widget)
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))
    return app


def test_send_routes_learn_to_handler(monkeypatch):
    app = _make_app()
    calls = []
    monkeypatch.setattr(app, "query_one", lambda *args: DummyInput())
    monkeypatch.setattr(app, "_handle_learn_command", lambda text: calls.append(text))

    app._send("/learn redis")

    assert calls == ["/learn redis"]


def test_send_routes_hint_to_handler(monkeypatch):
    app = _make_app()
    calls = []
    monkeypatch.setattr(app, "query_one", lambda *args: DummyInput())
    monkeypatch.setattr(app, "_handle_hint_command", lambda text: calls.append(text))

    app._send("/hint")

    assert calls == ["/hint"]


def test_send_routes_agent_to_handler(monkeypatch):
    app = _make_app()
    calls = []
    monkeypatch.setattr(app, "query_one", lambda *args: DummyInput())
    monkeypatch.setattr(app, "_handle_agent_command", lambda text: calls.append(text))

    app._send("/agent mentor")

    assert calls == ["/agent mentor"]


def test_send_routes_sessions_to_handler(monkeypatch):
    app = _make_app()
    calls = []
    monkeypatch.setattr(app, "query_one", lambda *args: DummyInput())
    monkeypatch.setattr(app, "_handle_sessions_command", lambda text: calls.append(text))

    app._send("/sessions list")

    assert calls == ["/sessions list"]


def test_send_help_lists_all_commands(monkeypatch):
    appended = []
    app = _dispatch_app(monkeypatch, appended)

    app._send("/help")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    for expected in ["/help", "/clear", "/export", "/learn", "/hint", "/agent", "/model", "/sessions", "/todo-clear"]:
        assert expected in text


def test_send_todo_clear_empties_panel(monkeypatch):
    app = _make_app()
    panel = DummyTodoPanel()
    appended = []
    monkeypatch.setattr(app, "query_one", lambda *args: panel)
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._send("/todo-clear")

    assert panel.todos == []
    assert panel.display is False
    assert any("Todo list cleared" in _rendered_text(widget) for widget in appended)


def test_send_model_help_explains_usage(monkeypatch):
    appended = []
    app = _dispatch_app(monkeypatch, appended)

    app._send("/model help")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "/model <name>" in text


def test_send_model_no_arg_shows_current_and_options(monkeypatch):
    appended = []
    app = _dispatch_app(monkeypatch, appended)

    app._send("/model")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "Current model: haiku" in text


def test_send_model_unknown_reports_options(monkeypatch):
    appended = []
    app = _dispatch_app(monkeypatch, appended)

    app._send("/model nope")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "Unknown model: nope" in text
    assert app._model == "haiku"


def test_sessions_help_lists_subcommands(monkeypatch):
    app = _make_app()
    appended = []
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_sessions_command("/sessions help")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "/sessions new <name>" in text
    assert "/sessions load <name>" in text
    assert "/sessions rename <old> <new>" in text


def test_sessions_unknown_subcommand_reports(monkeypatch):
    app = _make_app()
    appended = []
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))

    app._handle_sessions_command("/sessions bogus")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "Unknown subcommand" in text


def test_send_unknown_command_reports_not_found(monkeypatch):
    app = _make_app()
    appended = []
    run_calls = []
    monkeypatch.setattr(app, "query_one", lambda *args: DummyInput())
    monkeypatch.setattr(app, "_append_sync", lambda widget: appended.append(widget))
    monkeypatch.setattr(app, "_run_agent", lambda: run_calls.append(True))

    app._send("/bogus do something")

    text = "\n".join(_rendered_text(widget) for widget in appended)
    assert "Unknown command: /bogus" in text
    assert run_calls == []
    assert app._messages == [{"role": "system", "content": "sys"}]


def test_send_plain_message_goes_to_agent(monkeypatch):
    app = _make_app()
    input_widget = DummyInput()
    run_calls = []
    monkeypatch.setattr(app, "query_one", lambda *args: input_widget)
    monkeypatch.setattr(app, "_append_sync", lambda widget: None)
    monkeypatch.setattr(app, "_run_agent", lambda: run_calls.append(True))

    app._send("how do I parse RESP?")

    assert run_calls == [True]
    assert app._messages[-1] == {"role": "user", "content": "how do I parse RESP?"}
    assert input_widget.disabled is True
