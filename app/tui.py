import asyncio
import json
import re
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Input, Static
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual import work
from rich.markup import escape
from rich.text import Text
from .agent import run_agent, MODELS, CONTEXT_WINDOWS, DEFAULT_MODEL
from .agents import (
    AgentProfile,
    COACH_PROFILE,
    DEFAULT_PROFILE,
    available_tool_names,
    get_profile,
    list_profiles,
    save_custom_profile,
    validate_allowed_tools,
    validate_profile_name,
)
from .config import load_system_prompt
from .format import format_usage
from .session import (
    clear_session, load_session, save_session, list_sessions,
    clear_lesson, load_lesson, save_lesson, LessonState,
    DEFAULT_SESSION, _validate_name, export_conversation, rename_session,
)
from .widgets import ToolBlock, TodoPanel, build_tool_body


def _md_to_rich(text: str) -> str:
    s = escape(text)
    s = re.sub(r'\*\*(.+?)\*\*', r'[bold]\1[/bold]', s)
    s = re.sub(r'`(.+?)`', r'[code]\1[/code]', s)
    return s


def _format_tool_args(args: dict) -> str:
    parts = []
    for k, v in args.items():
        text = str(v)
        if len(text) > 200:
            text = text[:200] + "\u2026"
        parts.append(f"{k}: {text}")
    return "\n".join(parts)


def _message_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, indent=2)
    except TypeError:
        return str(content)


def _session_transcript(messages: list) -> list[tuple[str, str]]:
    transcript: list[tuple[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _message_text(message.get("content"))
        if not text.strip():
            continue
        transcript.append((role, text))
    return transcript


def _refresh_system_prompt(messages: list, system_prompt: str) -> list:
    refreshed = list(messages)
    system_message = {"role": "system", "content": system_prompt}
    if refreshed and isinstance(refreshed[0], dict) and refreshed[0].get("role") == "system":
        refreshed[0] = system_message
    else:
        refreshed.insert(0, system_message)
    return refreshed


def _learn_goal_prompt(goal: str) -> str:
    return (
        f"I want to build my own {goal}.\n\n"
        "Create a CodeCrafters-style learning path for this goal. "
        "Break it into 5-10 small milestones, then start with task 1 only. "
        "For task 1, include the expected outcome, a small implementation target, "
        "and how we will check it. Wait for my attempt before moving to task 2."
    )


HINT_LEVELS: tuple[tuple[str, str], ...] = (
    ("question", "Ask me one guiding question that points me toward the next step. Do not reveal the approach."),
    ("nudge", "Give a short nudge naming the concept or area to focus on. Still no code."),
    ("focused example", "Show a small, focused example of the technique in isolation, not the full solution for my task."),
    ("near-solution", "Walk me through the solution for the current task step by step, stopping just short of writing the complete final code unless I ask."),
)

MAX_HINT_LEVEL = len(HINT_LEVELS)


def _hint_prompt(level: int) -> str:
    label, instruction = HINT_LEVELS[level - 1]
    return (
        f"I'm stuck on the current task. Give me a hint at strength {level} of "
        f"{MAX_HINT_LEVEL} ({label}). {instruction} Keep it focused on the current "
        "task only and stay in teaching mode."
    )


class AgentApp(App):
    TITLE = "Agent Daniel"
    BINDINGS = [
        Binding("ctrl+x", "quit", "Quit", priority=True),
        Binding("escape", "interrupt", "Interrupt", priority=True),
    ]

    CSS = """
    #chat-log {
        height: 1fr;
        padding: 0 1;
    }

    #chat-log > Static {
        height: auto;
    }

    ToolBlock {
        height: auto;
        margin: 1 0;
    }

    ToolToggle {
        height: 1;
    }

    ToolToggle:hover {
        background: $boost;
    }

    #main-area {
        height: 1fr;
    }

    #todo-panel {
        width: 30;
        dock: right;
        padding: 1;
        border-left: solid $accent;
        display: none;
    }

    #bottom-bar {
        height: 4;
        dock: bottom;
    }

    #usage-bar {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $panel;
    }

    #input-bar {
        height: 3;
        padding: 0 1;
    }

    #user-input {
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-area"):
            yield VerticalScroll(id="chat-log")
            yield TodoPanel(id="todo-panel")
        with Vertical(id="bottom-bar"):
            yield Static(
                format_usage(
                    0,
                    0,
                    0.0,
                    DEFAULT_MODEL,
                    CONTEXT_WINDOWS.get(MODELS[DEFAULT_MODEL], 0),
                    DEFAULT_PROFILE,
                ),
                id="usage-bar",
            )
            yield Horizontal(
                Input(placeholder="Type a message...", id="user-input"),
                id="input-bar",
            )

    def on_mount(self) -> None:
        self.query_one("#user-input", Input).focus()
        self._pending_confirm: asyncio.Future[bool] | None = None
        self._pending_agent_create: dict[str, object] | None = None
        self._pending_agent_switch: str | None = None
        self._current_tool_block: ToolBlock | None = None
        self._history: list[str] = []
        self._history_index: int = 0
        self._history_draft: str = ""
        self._model = DEFAULT_MODEL
        self._agent_profile = DEFAULT_PROFILE
        self._session_name = DEFAULT_SESSION
        self._lesson: LessonState | None = None
        self._reset_usage()
        saved = load_session(self._session_name)
        if saved is not None:
            self._lesson = load_lesson(self._session_name)
            if self._lesson is not None:
                self._agent_profile = COACH_PROFILE
            self._messages: list = _refresh_system_prompt(saved, load_system_prompt(self._agent_profile))
            self._history = [m["content"] for m in saved if m.get("role") == "user"]
            self._history_index = len(self._history)
            user_turns = len(self._history)
            self._append_sync(Static(Text.assemble(
                ("Loaded session ", "dim"),
                (self._session_name, "bold"),
                (f" ({user_turns} user turn{'s' if user_turns != 1 else ''}). ", "dim"),
                ("Type ", "dim"),
                ("/clear", "bold yellow"),
                (" to start fresh.", "dim"),
            )))
            if self._lesson is not None:
                self._append_sync(Static(Text.assemble(
                    ("Resumed lesson: ", "dim"),
                    (self._lesson.goal, "bold"),
                )))
            self._append_session_transcript(self._messages)
        else:
            self._messages = [{"role": "system", "content": load_system_prompt(self._agent_profile)}]

    def _container(self) -> VerticalScroll:
        return self.query_one("#chat-log", VerticalScroll)

    def _append_sync(self, widget) -> None:
        container = self._container()
        container.mount(widget)
        container.scroll_end(animate=False)

    def _append_session_transcript(self, messages: list) -> None:
        for role, text in _session_transcript(messages):
            if role == "user":
                self._append_sync(Static(Text.assemble(("You: ", "bold green"), (text, "white"))))
            else:
                rendered = _md_to_rich(text)
                self._append_sync(Static(Text.from_markup(f"[bold blue]Agent:[/bold blue] {rendered}")))

    async def _append(self, widget):
        container = self._container()
        await container.mount(widget)
        container.scroll_end(animate=False)
        return widget

    def _context_window(self) -> int:
        return CONTEXT_WINDOWS.get(MODELS[self._model], 0)

    def _update_usage_bar(self) -> None:
        self.query_one("#usage-bar", Static).update(
            format_usage(
                self._total_in,
                self._total_out,
                self._total_cost,
                self._model,
                self._context_window(),
                self._agent_profile,
            )
        )

    def _reset_usage(self) -> None:
        self._total_in = 0
        self._total_out = 0
        self._total_cost = 0.0
        self._update_usage_bar()

    def on_key(self, event) -> None:
        inp = self.query_one("#user-input", Input)
        if not inp.has_focus:
            return
        if event.key == "up":
            if not self._history:
                return
            event.prevent_default()
            event.stop()
            if self._history_index == len(self._history):
                self._history_draft = inp.value
            if self._history_index > 0:
                self._history_index -= 1
                inp.value = self._history[self._history_index]
                inp.cursor_position = len(inp.value)
        elif event.key == "down":
            if self._history_index >= len(self._history):
                return
            event.prevent_default()
            event.stop()
            self._history_index += 1
            if self._history_index == len(self._history):
                inp.value = self._history_draft
            else:
                inp.value = self._history[self._history_index]
            inp.cursor_position = len(inp.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._send(event.value)

    def _send(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        inp = self.query_one("#user-input", Input)
        inp.value = ""

        self._history.append(text)
        self._history_index = len(self._history)
        self._history_draft = ""

        if self._pending_confirm is not None and not self._pending_confirm.done():
            self._answer_confirm(text)
            return

        if self._pending_agent_create is not None:
            self._answer_agent_create(text)
            return

        if self._pending_agent_switch is not None:
            self._answer_agent_switch(text)
            return

        if text == "/help":
            for line in [
                "/help                          Show this help message",
                "/clear                         Clear current conversation",
                "/export [filename]             Export conversation to Markdown",
                "/learn <thing>                 Start a guided build-your-own lesson",
                "/hint                          Get the next-strongest hint for the current task",
                "/agent [name]                  Show or switch the active agent profile",
                "/agent create [name]           Create a custom agent profile",
                "/model [name]                  Show or switch the active model",
                "/sessions [list|new|load|delete|rename]  Manage named sessions",
                "/todo-clear                    Clear the todo panel",
                "",
                "Ctrl+X to quit, Escape to interrupt the agent.",
            ]:
                self._append_sync(Static(Text(f"  {line}", style="dim")))
            return

        if text == "/clear":
            self._messages = [{"role": "system", "content": load_system_prompt(self._agent_profile)}]
            clear_session(self._session_name)
            self._lesson = None
            self._current_tool_block = None
            self._history.clear()
            self._history_index = 0
            self._container().remove_children()
            self._reset_usage()
            self._append_sync(Static(Text("Conversation cleared.", style="dim")))
            return

        if text == "/todo-clear":
            panel = self.query_one("#todo-panel", TodoPanel)
            panel.todos = []
            panel.display = False
            self._append_sync(Static(Text("Todo list cleared.", style="dim")))
            return

        if text == "/export" or text.startswith("/export "):
            filename = text[7:].strip()
            try:
                path = export_conversation(self._messages, filename or None)
            except OSError as exc:
                self._append_sync(Static(Text.assemble(
                    ("Export failed: ", "bold red"),
                    (str(exc), "white"),
                )))
            else:
                self._append_sync(Static(Text.assemble(
                    ("Exported conversation to ", "dim"),
                    (str(path), "bold"),
                )))
            return

        if text.startswith("/sessions"):
            self._handle_sessions_command(text)
            return

        if text == "/learn" or text.startswith("/learn "):
            self._handle_learn_command(text)
            return

        if text == "/hint" or text.startswith("/hint "):
            self._handle_hint_command(text)
            return

        if text == "/agent" or text.startswith("/agent "):
            self._handle_agent_command(text)
            return

        if text == "/model" or text.startswith("/model "):
            arg = text[7:].strip()
            if arg == "help":
                for line in [
                    "/model               Show current model and available options",
                    "/model <name>        Switch to a different model",
                ]:
                    self._append_sync(Static(Text(f"  {line}", style="dim")))
                return
            if not arg:
                options = ", ".join(MODELS)
                self._append_sync(Static(Text.assemble(
                    ("Current model: ", "dim"),
                    (self._model, "bold"),
                    (" \u2014 available: ", "dim"),
                    (options, "bold"),
                )))
            elif arg in MODELS:
                self._model = arg
                self._append_sync(Static(Text.assemble(
                    ("Switched to ", "dim"),
                    (arg, "bold"),
                )))
                self._update_usage_bar()
            else:
                options = ", ".join(MODELS)
                self._append_sync(Static(Text.assemble(
                    (f"Unknown model: {arg}", "bold red"),
                    (" \u2014 available: ", "dim"),
                    (options, "bold"),
                )))
            return

        inp.disabled = True
        self._append_sync(Static(Text.assemble(("You: ", "bold green"), (text, "white"))))
        self._messages.append({"role": "user", "content": text})
        self._safe_msg_count = len(self._messages)
        self._run_agent()

    def _answer_confirm(self, text: str) -> None:
        answer = text.strip().lower()
        if answer in ("y", "yes"):
            self._append_sync(Static(Text.assemble(("You: ", "bold green"), ("approved", "white"))))
            self._pending_confirm.set_result(True)
        elif answer in ("n", "no"):
            self._append_sync(Static(Text.assemble(("You: ", "bold green"), ("denied", "white"))))
            self._pending_confirm.set_result(False)
        else:
            self._append_sync(Static(Text("Please answer y (approve) or n (deny).", style="dim")))

    def _validate_new_agent_profile_name(self, name: str) -> str | None:
        err = validate_profile_name(name)
        if err:
            return err
        try:
            get_profile(name)
        except ValueError:
            return None
        return f"Agent profile '{name}' already exists."

    def _parse_agent_tools(self, text: str) -> tuple[tuple[str, ...] | None, str | None]:
        value = text.strip()
        if value.lower() == "all":
            return available_tool_names(), None

        names = [part for part in re.split(r"[\s,]+", value) if part]
        by_lower = {tool_name.lower(): tool_name for tool_name in available_tool_names()}
        normalized = [by_lower.get(name.lower(), name) for name in names]
        return validate_allowed_tools(normalized)

    def _append_agent_create_prompt(self) -> None:
        state = self._pending_agent_create
        if state is None:
            return
        step = state.get("step")
        if step == "name":
            self._append_sync(Static(Text(
                "Profile name: lowercase letters, digits, hyphens, and underscores; start with a letter.",
                style="dim",
            )))
        elif step == "title":
            self._append_sync(Static(Text("Display title:", style="dim")))
        elif step == "description":
            self._append_sync(Static(Text("Description:", style="dim")))
        elif step == "allowed_tools":
            tools = ", ".join(available_tool_names())
            self._append_sync(Static(Text(
                f"Allowed tools (comma-separated, or all). Available: {tools}",
                style="dim",
            )))
        elif step == "system_addendum":
            self._append_sync(Static(Text("Prompt instructions:", style="dim")))

    def _start_agent_create(self, name: str = "") -> None:
        state: dict[str, object] = {
            "step": "name",
            "name": "",
            "title": "",
            "description": "",
            "allowed_tools": (),
            "system_addendum": "",
        }
        self._pending_agent_create = state
        self._append_sync(Static(Text("Creating a custom agent profile. Type cancel to stop.", style="dim")))

        if name:
            err = self._validate_new_agent_profile_name(name)
            if err:
                self._pending_agent_create = None
                self._append_sync(Static(Text(err, style="bold red")))
                return
            state["name"] = name
            state["step"] = "title"

        self._append_agent_create_prompt()

    def _answer_agent_create(self, text: str) -> None:
        state = self._pending_agent_create
        if state is None:
            return
        value = text.strip()
        if value.lower() == "cancel":
            self._pending_agent_create = None
            self._append_sync(Static(Text("Agent profile creation cancelled.", style="dim")))
            return

        step = state.get("step")
        if step == "name":
            err = self._validate_new_agent_profile_name(value)
            if err:
                self._append_sync(Static(Text(err, style="bold red")))
                self._append_agent_create_prompt()
                return
            state["name"] = value
            state["step"] = "title"
            self._append_agent_create_prompt()
            return

        if step == "title":
            if not value:
                self._append_sync(Static(Text("Agent profile title cannot be empty.", style="bold red")))
                self._append_agent_create_prompt()
                return
            state["title"] = value
            state["step"] = "description"
            self._append_agent_create_prompt()
            return

        if step == "description":
            if not value:
                self._append_sync(Static(Text("Agent profile description cannot be empty.", style="bold red")))
                self._append_agent_create_prompt()
                return
            state["description"] = value
            state["step"] = "allowed_tools"
            self._append_agent_create_prompt()
            return

        if step == "allowed_tools":
            tools, err = self._parse_agent_tools(value)
            if err:
                self._append_sync(Static(Text(err, style="bold red")))
                self._append_agent_create_prompt()
                return
            state["allowed_tools"] = tools
            state["step"] = "system_addendum"
            self._append_agent_create_prompt()
            return

        if step == "system_addendum":
            if not value:
                self._append_sync(Static(Text("Agent profile instructions cannot be empty.", style="bold red")))
                self._append_agent_create_prompt()
                return
            state["system_addendum"] = value
            allowed_tools = state["allowed_tools"]
            if not isinstance(allowed_tools, tuple):
                self._append_sync(Static(Text("Allowed tools were not captured correctly.", style="bold red")))
                state["step"] = "allowed_tools"
                self._append_agent_create_prompt()
                return
            profile = AgentProfile(
                name=str(state["name"]),
                title=str(state["title"]),
                description=str(state["description"]),
                allowed_tools=allowed_tools,
                system_addendum=str(state["system_addendum"]),
            )
            err = save_custom_profile(profile)
            if err:
                self._append_sync(Static(Text(err, style="bold red")))
                self._append_agent_create_prompt()
                return
            self._pending_agent_create = None
            self._append_sync(Static(Text.assemble(
                ("Created agent profile ", "dim"),
                (profile.name, "bold"),
                (". Switch with ", "dim"),
                (f"/agent {profile.name}", "bold yellow"),
                (".", "dim"),
            )))

    def _handle_sessions_command(self, text: str) -> None:
        parts = text.split()
        sub = parts[1] if len(parts) > 1 else ""
        arg = parts[2] if len(parts) > 2 else ""

        if sub == "help":
            for line in [
                "/sessions              List all sessions (same as /sessions list)",
                "/sessions list         List all sessions for this directory",
                "/sessions new <name>   Create and switch to a new session",
                "/sessions load <name>  Switch to an existing session",
                "/sessions delete <name>  Delete a saved session",
                "/sessions rename <old> <new>  Rename a saved session",
            ]:
                self._append_sync(Static(Text(f"  {line}", style="dim")))
            return

        if sub == "list" or not sub:
            names = list_sessions()
            if not names:
                self._append_sync(Static(Text("No saved sessions.", style="dim")))
            else:
                for n in names:
                    marker = " \u2190 current" if n == self._session_name else ""
                    style = "bold" if n == self._session_name else "dim"
                    self._append_sync(Static(Text(f"  {n}{marker}", style=style)))
            return

        if sub == "new":
            if not arg:
                self._append_sync(Static(Text("Usage: /sessions new <name>", style="dim")))
                return
            err = _validate_name(arg)
            if err:
                self._append_sync(Static(Text(err, style="bold red")))
                return
            if load_session(arg) is not None:
                self._append_sync(Static(Text(f"Session '{arg}' already exists. Use /sessions load {arg}.", style="bold red")))
                return
            save_session(self._messages, self._session_name)
            self._session_name = arg
            self._messages = [{"role": "system", "content": load_system_prompt(self._agent_profile)}]
            self._current_tool_block = None
            self._history.clear()
            self._history_index = 0
            self._container().remove_children()
            self._reset_usage()
            self._append_sync(Static(Text.assemble(
                ("Created and switched to session ", "dim"),
                (arg, "bold"),
            )))
            return

        if sub == "load":
            if not arg:
                self._append_sync(Static(Text("Usage: /sessions load <name>", style="dim")))
                return
            saved = load_session(arg)
            if saved is None:
                self._append_sync(Static(Text(f"Session '{arg}' not found.", style="bold red")))
                return
            save_session(self._messages, self._session_name)
            self._session_name = arg
            self._messages = _refresh_system_prompt(saved, load_system_prompt(self._agent_profile))
            self._current_tool_block = None
            self._history = [m["content"] for m in saved if m.get("role") == "user"]
            self._history_index = len(self._history)
            self._container().remove_children()
            self._reset_usage()
            user_turns = len(self._history)
            self._append_sync(Static(Text.assemble(
                ("Loaded session ", "dim"),
                (arg, "bold"),
                (f" ({user_turns} user turn{'s' if user_turns != 1 else ''}).", "dim"),
            )))
            self._append_session_transcript(self._messages)
            return

        if sub == "delete":
            if not arg:
                self._append_sync(Static(Text("Usage: /sessions delete <name>", style="dim")))
                return
            if arg == self._session_name:
                self._append_sync(Static(Text("Cannot delete the current session.", style="bold red")))
                return
            if load_session(arg) is None:
                self._append_sync(Static(Text(f"Session '{arg}' not found.", style="bold red")))
                return
            clear_session(arg)
            self._append_sync(Static(Text.assemble(
                ("Deleted session ", "dim"),
                (arg, "bold"),
            )))
            return

        if sub == "rename":
            new_name = parts[3] if len(parts) > 3 else ""
            if not arg or not new_name or len(parts) > 4:
                self._append_sync(Static(Text("Usage: /sessions rename <old> <new>", style="dim")))
                return
            if arg == self._session_name:
                save_session(self._messages, self._session_name)
            err = rename_session(arg, new_name)
            if err:
                self._append_sync(Static(Text(err, style="bold red")))
                return
            if arg == self._session_name:
                self._session_name = new_name
            self._append_sync(Static(Text.assemble(
                ("Renamed session ", "dim"),
                (arg, "bold"),
                (" to ", "dim"),
                (new_name, "bold"),
            )))
            return

        self._append_sync(Static(Text("Unknown subcommand. Type /sessions help for usage.", style="dim")))

    def _handle_learn_command(self, text: str) -> None:
        goal = text[6:].strip()

        if goal == "help":
            for line in [
                "/learn <thing>       Start a guided build-your-own lesson",
                "/learn redis         Build a tiny Redis-like server step by step",
                "/learn grep          Build a grep-like search tool step by step",
                "/learn http server   Build an HTTP server step by step",
            ]:
                self._append_sync(Static(Text(f"  {line}", style="dim")))
            return

        if not goal:
            self._append_sync(Static(Text("Usage: /learn <thing>  (try /learn redis or /learn grep)", style="dim")))
            return

        save_session(self._messages, self._session_name)
        self._agent_profile = COACH_PROFILE
        prompt = _learn_goal_prompt(goal)
        self._messages = [{"role": "system", "content": load_system_prompt(self._agent_profile)}]
        self._messages.append({"role": "user", "content": prompt})
        self._lesson = LessonState(goal=goal)
        save_lesson(self._lesson, self._session_name)
        self._current_tool_block = None
        self._history.clear()
        self._history.append(prompt)
        self._history_index = len(self._history)
        self._history_draft = ""
        self._container().remove_children()
        self._reset_usage()
        self._append_sync(Static(Text.assemble(
            ("Learning goal: ", "dim"),
            (goal, "bold"),
        )))
        self._append_sync(Static(Text.assemble(("You: ", "bold green"), (prompt, "white"))))
        self._safe_msg_count = len(self._messages)
        self.query_one("#user-input", Input).disabled = True
        self._run_agent()

    def _handle_hint_command(self, text: str) -> None:
        arg = text[5:].strip()

        if arg == "help":
            for line in [
                "/hint                Get the next-strongest hint for the current task",
                "",
                "Hints escalate one level each time you ask:",
                "  1 question         A guiding question, no approach revealed",
                "  2 nudge            Names the concept or area to focus on",
                "  3 focused example  A small example of the technique in isolation",
                "  4 near-solution    Step-by-step walkthrough of the current task",
                "",
                "The level resets to 1 when a new task or lesson starts.",
            ]:
                self._append_sync(Static(Text(f"  {line}", style="dim")))
            return

        if arg:
            self._append_sync(Static(Text("Usage: /hint  (type /hint help for details)", style="dim")))
            return

        if self._lesson is None:
            self._append_sync(Static(Text.assemble(
                ("No active lesson. Start one with ", "dim"),
                ("/learn <thing>", "bold yellow"),
                (" before asking for a hint.", "dim"),
            )))
            return

        self._lesson = self._lesson.escalated(MAX_HINT_LEVEL)
        save_lesson(self._lesson, self._session_name)
        level = self._lesson.hint_level
        label = HINT_LEVELS[level - 1][0]
        prompt = _hint_prompt(level)
        self._messages.append({"role": "user", "content": prompt})
        self._history.append(prompt)
        self._history_index = len(self._history)
        self._history_draft = ""
        self._append_sync(Static(Text.assemble(
            ("Hint ", "dim"),
            (f"{level}/{MAX_HINT_LEVEL}", "bold"),
            (f" ({label})", "dim"),
        )))
        self._append_sync(Static(Text.assemble(("You: ", "bold green"), (prompt, "white"))))
        self._safe_msg_count = len(self._messages)
        self.query_one("#user-input", Input).disabled = True
        self._run_agent()


    def _handle_agent_command(self, text: str) -> None:
        arg = text[7:].strip()

        if arg == "help":
            for line in [
                "/agent               Show current agent and available profiles",
                "/agent <name>        Switch to an agent profile",
                "/agent create [name] Create a custom agent profile",
            ]:
                self._append_sync(Static(Text(f"  {line}", style="dim")))
            return

        if arg == "create" or arg.startswith("create "):
            create_arg = arg[len("create"):].strip()
            parts = create_arg.split()
            if len(parts) > 1:
                self._append_sync(Static(Text("Usage: /agent create [name]", style="dim")))
                return
            self._start_agent_create(parts[0] if parts else "")
            return

        if not arg:
            current = get_profile(self._agent_profile)
            self._append_sync(Static(Text.assemble(
                ("Current agent: ", "dim"),
                (current.name, "bold"),
                (f" — {current.title}", "dim"),
            )))
            for profile in list_profiles():
                marker = " ← current" if profile.name == self._agent_profile else ""
                style = "bold" if profile.name == self._agent_profile else "dim"
                self._append_sync(Static(Text(
                    f"  {profile.name}{marker} — {profile.description}",
                    style=style,
                )))
            return

        try:
            profile = get_profile(arg)
        except ValueError:
            options = ", ".join(profile.name for profile in list_profiles())
            self._append_sync(Static(Text.assemble(
                (f"Unknown agent: {arg}", "bold red"),
                (" — available: ", "dim"),
                (options, "bold"),
            )))
            return

        if profile.name == self._agent_profile:
            self._append_sync(Static(Text.assemble(
                ("Already using agent ", "dim"),
                (profile.name, "bold"),
                (".", "dim"),
            )))
            return

        self._pending_agent_switch = profile.name
        self._append_sync(Static(Text.assemble(
            ("Switching to agent ", "dim"),
            (profile.name, "bold"),
            (" starts a fresh conversation and clears the current one. Continue? (y/n)", "dim"),
        )))

    def _answer_agent_switch(self, text: str) -> None:
        target = self._pending_agent_switch
        answer = text.strip().lower()
        if answer in ("y", "yes"):
            self._pending_agent_switch = None
            try:
                profile = get_profile(target)
            except ValueError:
                self._append_sync(Static(Text(f"Agent '{target}' is no longer available.", style="bold red")))
                return
            self._perform_agent_switch(profile)
        elif answer in ("n", "no"):
            self._pending_agent_switch = None
            self._append_sync(Static(Text("Kept the current agent.", style="dim")))
        else:
            self._append_sync(Static(Text("Please answer y (switch) or n (keep current).", style="dim")))

    def _perform_agent_switch(self, profile: AgentProfile) -> None:
        save_session(self._messages, self._session_name)
        self._agent_profile = profile.name
        self._messages = [{"role": "system", "content": load_system_prompt(self._agent_profile)}]
        self._current_tool_block = None
        self._history.clear()
        self._history_index = 0
        self._container().remove_children()
        self._reset_usage()
        self._append_sync(Static(Text.assemble(
            ("Switched to agent ", "dim"),
            (profile.name, "bold"),
            (" and started a fresh conversation.", "dim"),
        )))

    def action_interrupt(self) -> None:
        self.workers.cancel_all()

    @work(exclusive=True)
    async def _run_agent(self) -> None:
        first_text_chunk = True
        text_buffer: list[str] = []

        async def flush_buffer() -> None:
            nonlocal first_text_chunk
            text = "".join(text_buffer)
            text_buffer.clear()
            if not text:
                return
            rendered = _md_to_rich(text)
            if first_text_chunk:
                await self._append(Static(Text.from_markup(f"[bold blue]Agent:[/bold blue] {rendered}")))
                first_text_chunk = False
            else:
                await self._append(Static(Text.from_markup(rendered)))

        async def on_text(delta: str) -> None:
            text_buffer.append(delta)
            combined = "".join(text_buffer)
            if "\n" in combined:
                lines = combined.split("\n")
                incomplete = lines[-1]
                for line in lines[:-1]:
                    text_buffer.clear()
                    text_buffer.append(line)
                    await flush_buffer()
                text_buffer.clear()
                text_buffer.append(incomplete)

        async def on_tool_start(name: str, args_json: str) -> None:
            nonlocal first_text_chunk
            await flush_buffer()
            first_text_chunk = True
            try:
                args = json.loads(args_json)
                args_str = "  ".join(f"{k}={v}" for k, v in args.items())
            except Exception:
                args_str = args_json
            block = ToolBlock(name, args_str)
            self._current_tool_block = block
            await self._append(block)

        async def on_tool_result(name: str, result: str, args: dict) -> None:
            nonlocal first_text_chunk
            first_text_chunk = True
            block = self._current_tool_block
            self._current_tool_block = None
            preview, hidden, hidden_count, exit_code = build_tool_body(name, result, args)
            if block is not None:
                await block.populate(preview, hidden, hidden_count, exit_code)
            self._container().scroll_end(animate=False)

        def on_usage(prompt: int, completion: int, cost: float) -> None:
            self._total_in += prompt
            self._total_out += completion
            self._total_cost += cost
            ctx_window = self._context_window()
            self._update_usage_bar()
            if ctx_window > 0:
                ratio = self._total_in / ctx_window
                if ratio >= 0.9:
                    self._append_sync(Static(Text(
                        f"⚠ Context {ratio:.0%} full — start a new session (/sessions new <name>) to avoid silent truncation.",
                        style="bold red",
                    )))
                elif ratio >= 0.75:
                    self._append_sync(Static(Text(
                        f"⚠ Context {ratio:.0%} full — consider starting a new session soon.",
                        style="bold yellow",
                    )))

        async def on_tool_confirm(name: str, args: dict, reason: str) -> bool:
            await flush_buffer()
            await self._append(Static(Text.assemble(
                ("\u26a0 Approve ", "bold yellow"),
                (name, "bold yellow"),
                (f"? ({reason})", "yellow"),
            )))
            for line in _format_tool_args(args).splitlines():
                await self._append(Static(Text.assemble(("\u2502 ", "dim"), (line, "dim white"))))
            await self._append(Static(Text("Type y to approve, n to deny.", style="dim italic")))

            self._pending_confirm = asyncio.get_running_loop().create_future()
            inp = self.query_one("#user-input", Input)
            inp.disabled = False
            inp.placeholder = "Approve? (y / n)"
            inp.focus()
            try:
                return await self._pending_confirm
            finally:
                self._pending_confirm = None
                inp.placeholder = "Type a message..."
                inp.disabled = True

        async def on_todo(todos: list[dict]) -> None:
            panel = self.query_one("#todo-panel", TodoPanel)
            panel.display = True
            panel.todos = todos

        try:
            await run_agent(
                self._messages,
                MODELS[self._model],
                on_text,
                on_tool_start,
                on_tool_result,
                on_usage,
                on_tool_confirm,
                on_todo,
                tool_allowlist=get_profile(self._agent_profile).allowed_tools,
            )
            await flush_buffer()
        except asyncio.CancelledError:
            del self._messages[self._safe_msg_count:]
            if self._current_tool_block is not None:
                self._current_tool_block.remove()
                self._current_tool_block = None
            self._append_sync(Static(Text("[interrupted]", style="dim italic")))
        except Exception as e:
            await flush_buffer()
            self._append_sync(Static(Text.assemble(("Error: ", "bold red"), (str(e), "white"))))
        finally:
            save_session(self._messages, self._session_name)
            inp = self.query_one("#user-input", Input)
            inp.disabled = False
            inp.focus()
