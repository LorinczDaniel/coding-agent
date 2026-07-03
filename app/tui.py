import asyncio
import json
import os
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Header, Input, Static

from .agent import CONTEXT_WINDOWS, DEFAULT_MODEL, MODELS, has_api_key, run_agent
from .agents import (
    COACH_PROFILE,
    DEFAULT_PROFILE,
    AgentProfile,
    available_tool_names,
    get_profile,
    list_profiles,
    save_custom_profile,
    validate_allowed_tools,
    validate_profile_name,
)
from .config import load_system_prompt
from .format import format_usage
from .lessons import (
    HINT_LEVELS,
    MAX_HINT_LEVEL,
    check_commands_from_todos,
    check_prompt,
    current_check_command,
    current_index_from_todos,
    extract_learning_goal,
    hint_level_display,
    hint_prompt,
    learn_goal_prompt,
    lesson_session_name,
    lesson_todos,
    milestone_card,
    next_action_hint,
    read_task_card,
    scaffold_lesson_workspace,
)
from .onboarding import SIGNUP_URL, save_api_key
from .session import (
    DEFAULT_SESSION,
    LessonState,
    clear_session,
    export_conversation,
    list_sessions,
    load_lesson,
    load_session,
    load_session_profile,
    message_text,
    rename_session,
    save_lesson,
    save_session,
    save_session_profile,
    session_exists,
    validate_session_name,
)
from .skills import discover_skills
from .tools import Bash as run_check_command
from .widgets import TodoPanel, ToolBlock, build_tool_body

HIDDEN_CHAT_TOOLS = {"TodoWrite"}


@dataclass(frozen=True)
class Command:
    """A slash command: dispatch prefix, handler method, and help entries."""

    name: str
    handler: str
    help_lines: tuple[tuple[str, str], ...]


COMMANDS: tuple[Command, ...] = (
    Command("/help", "_handle_help_command", (
        ("/help", "Show this help message"),
    )),
    Command("/clear", "_handle_clear_command", (
        ("/clear", "Clear current conversation"),
    )),
    Command("/export", "_handle_export_command", (
        ("/export [filename]", "Export conversation to Markdown"),
    )),
    Command("/learn", "_handle_learn_command", (
        ("/learn <thing>", "Start a guided build-your-own lesson"),
    )),
    Command("/hint", "_handle_hint_command", (
        ("/hint", "Get the next-strongest hint for the current task"),
    )),
    Command("/check", "_handle_check_command", (
        ("/check", "Run the current milestone's check and get a verdict"),
    )),
    Command("/agent", "_handle_agent_command", (
        ("/agent [name]", "Show or switch the active agent profile"),
        ("/agent create [name]", "Create a custom agent profile"),
    )),
    Command("/model", "_handle_model_command", (
        ("/model [name]", "Show or switch the active model"),
    )),
    Command("/skills", "_handle_skills_command", (
        ("/skills", "List skills available to the agent"),
    )),
    Command("/sessions", "_handle_sessions_command", (
        ("/sessions [list|new|load|delete|rename]", "Manage named sessions"),
    )),
    Command("/todo-clear", "_handle_todo_clear_command", (
        ("/todo-clear", "Clear the todo panel"),
    )),
)


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
            text = text[:200] + "…"
        parts.append(f"{k}: {text}")
    return "\n".join(parts)


def _format_args_inline(args: dict, max_value_len: int = 120) -> str:
    """One-line summary of tool args for block headers; never floods the log."""
    parts = []
    for k, v in args.items():
        text = " ".join(str(v).split())
        if len(text) > max_value_len:
            text = text[:max_value_len] + "…"
        parts.append(f"{k}={text}")
    return "  ".join(parts)


def _session_transcript(messages: list) -> list[tuple[str, str]]:
    transcript: list[tuple[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        text = message_text(message.get("content"))
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


def _user_history(messages: list) -> list[str]:
    return [
        content
        for m in messages
        if isinstance(m, dict)
        and m.get("role") == "user"
        and isinstance(content := m.get("content"), str)
    ]


def _active_context_text(profile_name: str, lesson: LessonState | None) -> Text:
    parts: list[str | tuple[str, str]] = [
        ("Profile: ", "dim"),
        profile_name,
        ("  Lesson: ", "dim"),
    ]
    if lesson is None:
        parts.append("not started")
    else:
        parts.extend([
            lesson.goal,
            ("  Hint: ", "dim"),
            hint_level_display(lesson.hint_level),
        ])
    return Text.assemble(*parts)


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

    #lesson-banner {
        height: 1;
        padding: 0 1;
        color: $text;
        background: $panel;
        display: none;
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
        height: 5;
        dock: bottom;
    }

    #usage-bar {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $panel;
    }

    #active-context-bar {
        height: 1;
        padding: 0 1;
        color: $text;
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

    def __init__(self) -> None:
        super().__init__()
        self._pending_confirm: asyncio.Future[bool] | None = None
        self._pending_agent_create: dict[str, object] | None = None
        self._pending_agent_switch: str | None = None
        self._pending_api_key: bool = False
        self._pending_tool_blocks: deque[ToolBlock] = deque()
        self._history: list[str] = []
        self._history_index: int = 0
        self._history_draft: str = ""
        self._model = DEFAULT_MODEL
        self._agent_profile = DEFAULT_PROFILE
        self._session_name = DEFAULT_SESSION
        self._lesson: LessonState | None = None
        self._messages: list = []
        self._safe_msg_count: int = 0
        self._total_in = 0
        self._total_out = 0
        self._total_cost = 0.0
        self._ctx_tokens = 0
        self._ctx_warned = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="lesson-banner")
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
            yield Static("", id="active-context-bar")
            yield Horizontal(
                Input(placeholder="Type a message...", id="user-input"),
                id="input-bar",
            )

    def on_mount(self) -> None:
        self.query_one("#user-input", Input).focus()
        self._reset_usage()
        saved = load_session(self._session_name)
        if saved is not None:
            stored_profile = load_session_profile(self._session_name)
            if stored_profile is not None:
                try:
                    get_profile(stored_profile)
                except ValueError:
                    pass
                else:
                    self._agent_profile = stored_profile
            self._lesson = load_lesson(self._session_name)
            if self._lesson is not None:
                self._agent_profile = COACH_PROFILE
            self._messages = _refresh_system_prompt(saved, load_system_prompt(self._agent_profile))
            self._history = _user_history(saved)
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
                self._refresh_lesson_ui()
                self._append_sync(Static(Text.assemble(
                    ("Resumed lesson: ", "dim"),
                    (self._lesson.goal, "bold"),
                )))
            self._append_session_transcript(self._messages)
        else:
            self._messages = [{"role": "system", "content": load_system_prompt(self._agent_profile)}]
        self._update_active_context_bar()
        if not has_api_key():
            self._start_api_key_onboarding()

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
                context_used=self._ctx_tokens,
            )
        )

    def _reset_usage(self) -> None:
        self._total_in = 0
        self._total_out = 0
        self._total_cost = 0.0
        self._ctx_tokens = 0
        self._ctx_warned = 0
        self._update_usage_bar()

    def _update_active_context_bar(self) -> None:
        self.query_one("#active-context-bar", Static).update(
            _active_context_text(self._agent_profile, self._lesson)
        )

    def _persist_session(self) -> None:
        err = save_session(self._messages, self._session_name)
        if err:
            self._append_sync(Static(Text(f"⚠ {err}", style="bold yellow")))
        save_session_profile(self._agent_profile, self._session_name)

    def _drain_pending_tool_blocks(self) -> None:
        while self._pending_tool_blocks:
            self._pending_tool_blocks.popleft().remove()

    def _reset_conversation_state(self) -> None:
        """Shared reset for /clear, session switches, agent switches, and /learn."""
        self._lesson = None
        self._pending_tool_blocks.clear()
        self._history.clear()
        self._history_index = 0
        self._history_draft = ""
        panel = self.query_one("#todo-panel", TodoPanel)
        panel.todos = []
        panel.display = False
        self._refresh_lesson_ui()
        self._container().remove_children()
        self._reset_usage()

    def _maybe_start_coach_lesson_from_message(self, text: str) -> None:
        if self._agent_profile != COACH_PROFILE or self._lesson is not None:
            return
        goal = extract_learning_goal(text)
        if goal is None:
            return
        self._lesson = LessonState(goal=goal)
        save_lesson(self._lesson, self._session_name)
        self._refresh_lesson_ui()

    def _refresh_lesson_ui(self) -> None:
        banner = self.query_one("#lesson-banner", Static)
        panel = self.query_one("#todo-panel", TodoPanel)
        if self._lesson is None:
            banner.display = False
            self._update_active_context_bar()
            return

        banner.update(Text.assemble(
            ("Lesson: ", "dim"),
            self._lesson.goal,
            ("  Hint: ", "dim"),
            hint_level_display(self._lesson.hint_level),
        ))
        banner.display = True
        panel.todos = lesson_todos(self._lesson, next_hint=next_action_hint(self._lesson))
        panel.display = True
        self._update_active_context_bar()

    def _update_lesson_milestones(self, todos: list[dict]) -> None:
        if self._lesson is None:
            return
        milestones = tuple(
            item.get("title", "").strip()
            for item in todos
            if isinstance(item.get("title"), str) and item.get("title", "").strip()
        )
        current_index = current_index_from_todos(todos, self._lesson.current_index)
        hint_level = 0 if current_index != self._lesson.current_index else self._lesson.hint_level
        self._lesson = LessonState(
            goal=self._lesson.goal,
            milestones=milestones,
            check_commands=check_commands_from_todos(todos),
            current_index=current_index,
            hint_level=hint_level,
        )
        save_lesson(self._lesson, self._session_name)
        self._refresh_lesson_ui()

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

        # Handled before the history append so the key is never recorded.
        if self._pending_api_key:
            self._answer_api_key(text)
            return

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

        if text.startswith("/"):
            for command in COMMANDS:
                if text == command.name or text.startswith(command.name + " "):
                    getattr(self, command.handler)(text)
                    return
            self._append_sync(Static(Text.assemble(
                ("Unknown command: ", "bold red"),
                (text.split()[0], "bold"),
                (". Type ", "dim"),
                ("/help", "bold yellow"),
                (" for the list of commands.", "dim"),
            )))
            return

        inp.disabled = True
        self._append_sync(Static(Text.assemble(("You: ", "bold green"), (text, "white"))))
        self._maybe_start_coach_lesson_from_message(text)
        self._messages.append({"role": "user", "content": text})
        self._safe_msg_count = len(self._messages)
        self._run_agent()

    # --- command handlers -------------------------------------------------

    def _handle_help_command(self, text: str) -> None:
        entries = [line for command in COMMANDS for line in command.help_lines]
        width = max(len(usage) for usage, _ in entries)
        for usage, description in entries:
            self._append_sync(Static(Text(f"  {usage:<{width}}  {description}", style="dim")))
        self._append_sync(Static(Text("", style="dim")))
        self._append_sync(Static(Text(
            "  Ctrl+X to quit, Escape to interrupt the agent.", style="dim",
        )))

    def _handle_clear_command(self, text: str) -> None:
        self._messages = [{"role": "system", "content": load_system_prompt(self._agent_profile)}]
        clear_session(self._session_name)
        self._reset_conversation_state()
        self._append_sync(Static(Text("Conversation cleared.", style="dim")))

    def _handle_todo_clear_command(self, text: str) -> None:
        panel = self.query_one("#todo-panel", TodoPanel)
        panel.todos = []
        panel.display = False
        self._append_sync(Static(Text("Todo list cleared.", style="dim")))

    def _handle_export_command(self, text: str) -> None:
        filename = text[len("/export"):].strip()
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

    def _handle_model_command(self, text: str) -> None:
        arg = text[len("/model"):].strip()
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
                (" — available: ", "dim"),
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
                (" — available: ", "dim"),
                (options, "bold"),
            )))

    def _handle_skills_command(self, text: str) -> None:
        skills = discover_skills()
        if not skills:
            self._append_sync(Static(Text(
                "No skills found. Add SKILL.md files under skills/<name>/ or "
                ".claude-agent/skills/<name>/.",
                style="dim",
            )))
            return
        for skill in skills:
            self._append_sync(Static(Text.assemble(
                ("  ", "dim"),
                (skill.name, "bold"),
                (f" — {skill.description}", "dim"),
            )))

    def _start_api_key_onboarding(self) -> None:
        self._pending_api_key = True
        self._append_sync(Static(Text("Welcome! One thing before we start:", style="bold")))
        for line in [
            "No OpenRouter API key found (checked OPENROUTER_API_KEY and .env).",
            f"1. Create a key at {SIGNUP_URL}",
            "2. Paste it below and press Enter — I'll save it to .env for you.",
            "Type skip to set it up manually later.",
        ]:
            self._append_sync(Static(Text(f"  {line}", style="dim")))
        inp = self.query_one("#user-input", Input)
        inp.password = True
        inp.placeholder = "Paste your OpenRouter API key…"
        inp.focus()

    def _finish_api_key_onboarding(self) -> None:
        self._pending_api_key = False
        inp = self.query_one("#user-input", Input)
        inp.password = False
        inp.placeholder = "Type a message..."
        inp.focus()

    def _answer_api_key(self, text: str) -> None:
        if text.strip().lower() in ("skip", "cancel"):
            self._finish_api_key_onboarding()
            self._append_sync(Static(Text(
                "Skipped. Add OPENROUTER_API_KEY to .env yourself before sending a message.",
                style="dim",
            )))
            return
        err = save_api_key(text)
        if err:
            self._append_sync(Static(Text(err, style="bold red")))
            self._append_sync(Static(Text(
                f"Paste the key from {SIGNUP_URL}, or type skip.", style="dim",
            )))
            return
        self._finish_api_key_onboarding()
        self._append_sync(Static(Text.assemble(
            ("Key saved to ", "dim"),
            (".env", "bold"),
            (" — you're all set. Ask me anything!", "dim"),
        )))

    def _answer_confirm(self, text: str) -> None:
        pending = self._pending_confirm
        if pending is None:
            return
        answer = text.strip().lower()
        if answer in ("y", "yes"):
            self._append_sync(Static(Text.assemble(("You: ", "bold green"), ("approved", "white"))))
            pending.set_result(True)
        elif answer in ("n", "no"):
            self._append_sync(Static(Text.assemble(("You: ", "bold green"), ("denied", "white"))))
            pending.set_result(False)
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
                    marker = " ← current" if n == self._session_name else ""
                    style = "bold" if n == self._session_name else "dim"
                    self._append_sync(Static(Text(f"  {n}{marker}", style=style)))
            return

        if sub == "new":
            if not arg:
                self._append_sync(Static(Text("Usage: /sessions new <name>", style="dim")))
                return
            err = validate_session_name(arg)
            if err:
                self._append_sync(Static(Text(err, style="bold red")))
                return
            if session_exists(arg):
                self._append_sync(Static(Text(f"Session '{arg}' already exists. Use /sessions load {arg}.", style="bold red")))
                return
            save_session(self._messages, self._session_name)
            save_session_profile(self._agent_profile, self._session_name)
            self._session_name = arg
            self._messages = [{"role": "system", "content": load_system_prompt(self._agent_profile)}]
            self._reset_conversation_state()
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
            save_session_profile(self._agent_profile, self._session_name)
            self._session_name = arg
            stored_profile = load_session_profile(arg)
            if stored_profile is not None:
                try:
                    get_profile(stored_profile)
                except ValueError:
                    pass
                else:
                    self._agent_profile = stored_profile
            lesson = load_lesson(self._session_name)
            if lesson is not None:
                self._agent_profile = COACH_PROFILE
            self._messages = _refresh_system_prompt(saved, load_system_prompt(self._agent_profile))
            self._reset_conversation_state()
            self._lesson = lesson
            self._refresh_lesson_ui()
            self._history = _user_history(saved)
            self._history_index = len(self._history)
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
            if not session_exists(arg):
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
        goal = text[len("/learn"):].strip()

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

        # Park the current conversation under its own name, then run the
        # lesson in a fresh session so nothing gets clobbered.
        save_session(self._messages, self._session_name)
        save_session_profile(self._agent_profile, self._session_name)
        old_session = self._session_name
        self._session_name = lesson_session_name(goal, session_exists)
        self._agent_profile = COACH_PROFILE
        # TASK.md is scaffolded here so the task card exists even if the
        # coach never writes the starter file it is prompted to create.
        workspace_display: str | None = None
        try:
            workspace = scaffold_lesson_workspace(goal, Path.cwd())
            workspace_display = os.path.relpath(workspace, Path.cwd()).replace(os.sep, "/")
        except OSError as exc:
            self._append_sync(Static(Text(
                f"Could not create the lesson workspace ({exc}); continuing without it.",
                style="dim",
            )))
        prompt = learn_goal_prompt(goal, workspace=workspace_display)
        self._messages = [{"role": "system", "content": load_system_prompt(self._agent_profile)}]
        self._messages.append({"role": "user", "content": prompt})
        self._reset_conversation_state()
        self._lesson = LessonState(goal=goal)
        save_lesson(self._lesson, self._session_name)
        self._refresh_lesson_ui()
        self._history.append(prompt)
        self._history_index = len(self._history)
        self._append_sync(Static(Text.assemble(
            ("Learning goal: ", "dim"),
            (goal, "bold"),
            ("  (session ", "dim"),
            (self._session_name, "bold"),
            (f"; your previous conversation is saved as {old_session})", "dim"),
        )))
        if workspace_display:
            self._append_sync(Static(Text.assemble(
                ("Workspace: ", "dim"),
                (workspace_display, "bold"),
                ("  (task card in TASK.md)", "dim"),
            )))
        self._append_sync(Static(Text.assemble(("You: ", "bold green"), (prompt, "white"))))
        self._safe_msg_count = len(self._messages)
        self.query_one("#user-input", Input).disabled = True
        self._run_agent()

    def _handle_hint_command(self, text: str) -> None:
        arg = text[len("/hint"):].strip()

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
        self._refresh_lesson_ui()
        level = self._lesson.hint_level
        label = HINT_LEVELS[level - 1][0]
        prompt = hint_prompt(level)
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

    def _handle_check_command(self, text: str) -> None:
        arg = text[len("/check"):].strip()

        if arg == "help":
            for line in [
                "/check               Run the current milestone's check command",
                "",
                "The coach sets a check command for each milestone when it plans",
                "the lesson. /check runs it, shows the output, and asks the coach",
                "to judge it: advance to the next task, or give a hint.",
            ]:
                self._append_sync(Static(Text(f"  {line}", style="dim")))
            return

        if arg:
            self._append_sync(Static(Text("Usage: /check  (type /check help for details)", style="dim")))
            return

        if self._lesson is None:
            self._append_sync(Static(Text.assemble(
                ("No active lesson. Start one with ", "dim"),
                ("/learn <thing>", "bold yellow"),
                (" before running a check.", "dim"),
            )))
            return

        command = current_check_command(self._lesson)
        if command is None:
            self._append_sync(Static(Text(
                "No check command for the current milestone yet. Ask the coach to "
                "plan the milestones (it sets a check for each one).",
                style="dim",
            )))
            return

        milestone = self._lesson.milestones[self._lesson.current_index]
        self._append_sync(Static(Text.assemble(
            ("Check: ", "dim"),
            (command, "bold"),
        )))
        self.query_one("#user-input", Input).disabled = True
        self._run_check(command, milestone)

    @work(exclusive=True)
    async def _run_check(self, command: str, milestone: str) -> None:
        await self._run_check_turn(command, milestone)

    async def _run_check_turn(self, command: str, milestone: str) -> None:
        # This runs before _run_agent_turn's error handling exists, so failures
        # here must re-enable the input themselves or the UI locks up.
        try:
            # run_check_command blocks (subprocess + timeout); keep the UI alive.
            output = await asyncio.to_thread(run_check_command, command)
        except asyncio.CancelledError:
            self._append_sync(Static(Text("[interrupted]", style="dim italic")))
            self._reenable_input()
            return
        except Exception as e:
            self._append_sync(Static(Text.assemble(("Error: ", "bold red"), (str(e), "white"))))
            self._reenable_input()
            return
        for line in output.splitlines() or ["(no output)"]:
            self._append_sync(Static(Text.assemble(("│ ", "dim"), (line, "dim white"))))
        prompt = check_prompt(milestone, command, output)
        self._messages.append({"role": "user", "content": prompt})
        self._safe_msg_count = len(self._messages)
        await self._run_agent_turn()

    def _reenable_input(self) -> None:
        inp = self.query_one("#user-input", Input)
        inp.disabled = False
        inp.focus()

    def _handle_agent_command(self, text: str) -> None:
        arg = text[len("/agent"):].strip()

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
        if target is None:
            return
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
        save_session_profile(self._agent_profile, self._session_name)
        self._agent_profile = profile.name
        self._messages = [{"role": "system", "content": load_system_prompt(self._agent_profile)}]
        self._reset_conversation_state()
        self._append_sync(Static(Text.assemble(
            ("Switched to agent ", "dim"),
            (profile.name, "bold"),
            (" and started a fresh conversation.", "dim"),
        )))

    def action_interrupt(self) -> None:
        self.workers.cancel_all()

    def action_show_milestone(self, index: int) -> None:
        """Show a task card for a clicked panel item in the chat log."""
        if self._lesson is not None:
            if not (0 <= index < len(self._lesson.milestones)):
                return
            is_current = index == self._lesson.current_index
            card = milestone_card(
                self._lesson,
                index,
                next_hint=next_action_hint(self._lesson) if is_current else None,
            )
            self._append_sync(Static(Text(card[0], style="bold")))
            for line in card[1:]:
                self._append_sync(Static(Text(f"  {line}", style="dim")))
            if is_current:
                task_card = read_task_card(self._lesson.goal)
                if task_card:
                    for line in task_card.rstrip().splitlines():
                        self._append_sync(Static(Text.assemble(("│ ", "dim"), (line, "dim white"))))
            return

        todos = self.query_one("#todo-panel", TodoPanel).todos
        if 0 <= index < len(todos):
            item = todos[index]
            self._append_sync(Static(Text.assemble(
                (str(item.get("title", "")), "bold"),
                (f"  ({item.get('status', 'unknown')})", "dim"),
            )))

    @work(exclusive=True)
    async def _run_agent(self) -> None:
        await self._run_agent_turn()

    async def _run_agent_turn(self) -> None:
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
            if name in HIDDEN_CHAT_TOOLS:
                return
            try:
                args_str = _format_args_inline(json.loads(args_json))
            except Exception:
                args_str = args_json
            block = ToolBlock(name, args_str)
            self._pending_tool_blocks.append(block)
            await self._append(block)

        async def on_tool_result(name: str, result: str, args: dict) -> None:
            nonlocal first_text_chunk
            first_text_chunk = True
            if name in HIDDEN_CHAT_TOOLS:
                return
            block = self._pending_tool_blocks.popleft() if self._pending_tool_blocks else None
            preview, hidden, hidden_count, exit_code = build_tool_body(name, result, args)
            if block is not None:
                await block.populate(preview, hidden, hidden_count, exit_code)
            self._container().scroll_end(animate=False)

        def on_usage(prompt: int, completion: int, cost: float) -> None:
            self._total_in += prompt
            self._total_out += completion
            self._total_cost += cost
            # Context occupancy is the LAST request's tokens — each request
            # already contains the whole conversation, so summing across tool
            # rounds would wildly overstate it.
            self._ctx_tokens = prompt + completion
            self._update_usage_bar()
            ctx_window = self._context_window()
            if ctx_window <= 0:
                return
            ratio = self._ctx_tokens / ctx_window
            if ratio >= 0.9 and self._ctx_warned < 2:
                self._ctx_warned = 2
                self._append_sync(Static(Text(
                    f"⚠ Context {ratio:.0%} full — start a new session (/sessions new <name>) to avoid silent truncation.",
                    style="bold red",
                )))
            elif 0.75 <= ratio < 0.9 and self._ctx_warned < 1:
                self._ctx_warned = 1
                self._append_sync(Static(Text(
                    f"⚠ Context {ratio:.0%} full — consider starting a new session soon.",
                    style="bold yellow",
                )))

        async def on_tool_confirm(name: str, args: dict, reason: str) -> bool:
            await flush_buffer()
            await self._append(Static(Text.assemble(
                ("⚠ Approve ", "bold yellow"),
                (name, "bold yellow"),
                (f"? ({reason})", "yellow"),
            )))
            for line in _format_tool_args(args).splitlines():
                await self._append(Static(Text.assemble(("│ ", "dim"), (line, "dim white"))))
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
            if self._lesson is not None:
                self._update_lesson_milestones(todos)
            else:
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
            self._drain_pending_tool_blocks()
            self._append_sync(Static(Text("[interrupted]", style="dim italic")))
        except Exception as e:
            # Roll back exactly like an interrupt: a partial turn may have
            # left an assistant tool_calls message without tool results, and
            # persisting that would poison every subsequent API request.
            del self._messages[self._safe_msg_count:]
            self._drain_pending_tool_blocks()
            self._append_sync(Static(Text.assemble(("Error: ", "bold red"), (str(e), "white"))))
        finally:
            self._persist_session()
            self._reenable_input()
