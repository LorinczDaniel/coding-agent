from app.format import format_usage
from app.tui import AgentApp, CONTEXT_WINDOWS, MODELS, _refresh_system_prompt, _session_transcript


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


def _make_app():
    app = AgentApp()
    app._model = "haiku"
    app._session_name = "default"
    app._messages = [{"role": "system", "content": "sys"}]
    app._history = []
    app._history_index = 0
    app._history_draft = ""
    app._pending_confirm = None
    app._current_tool_block = None
    app._total_in = 1234
    app._total_out = 567
    app._total_cost = 0.42
    return app


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
    monkeypatch.setattr("app.tui.load_system_prompt", lambda: "new system")

    app._send("/clear")

    assert reset_calls == [True]
    assert container.removed is True
    assert app._messages == [{"role": "system", "content": "new system"}]
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
    monkeypatch.setattr("app.tui.load_system_prompt", lambda: "new system")

    app._handle_sessions_command("/sessions new fresh")

    assert reset_calls == [True]
    assert container.removed is True
    assert app._session_name == "fresh"
    assert app._messages == [{"role": "system", "content": "new system"}]
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
    monkeypatch.setattr("app.tui.load_system_prompt", lambda: "new coach system")

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
