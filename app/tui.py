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
from .config import load_system_prompt
from .format import format_usage
from .session import (
    clear_session, load_session, save_session, list_sessions,
    DEFAULT_SESSION, _validate_name,
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
            yield Static(format_usage(0, 0, 0.0, DEFAULT_MODEL, CONTEXT_WINDOWS.get(MODELS[DEFAULT_MODEL], 0)), id="usage-bar")
            yield Horizontal(
                Input(placeholder="Type a message...", id="user-input"),
                id="input-bar",
            )

    def on_mount(self) -> None:
        self.query_one("#user-input", Input).focus()
        self._total_in = 0
        self._total_out = 0
        self._total_cost = 0.0
        self._pending_confirm: asyncio.Future[bool] | None = None
        self._current_tool_block: ToolBlock | None = None
        self._history: list[str] = []
        self._history_index: int = 0
        self._history_draft: str = ""
        self._model = DEFAULT_MODEL
        self._session_name = DEFAULT_SESSION
        saved = load_session(self._session_name)
        if saved is not None:
            self._messages: list = saved
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
        else:
            self._messages = [{"role": "system", "content": load_system_prompt()}]

    def _container(self) -> VerticalScroll:
        return self.query_one("#chat-log", VerticalScroll)

    def _append_sync(self, widget) -> None:
        container = self._container()
        container.mount(widget)
        container.scroll_end(animate=False)

    async def _append(self, widget):
        container = self._container()
        await container.mount(widget)
        container.scroll_end(animate=False)
        return widget

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

        if text == "/help":
            for line in [
                "/help                          Show this help message",
                "/clear                         Clear current conversation",
                "/model [name]                  Show or switch the active model",
                "/sessions [list|new|load|delete]  Manage named sessions",
                "/todo-clear                    Clear the todo panel",
                "",
                "Ctrl+X to quit, Escape to interrupt the agent.",
            ]:
                self._append_sync(Static(Text(f"  {line}", style="dim")))
            return

        if text == "/clear":
            self._messages = [{"role": "system", "content": load_system_prompt()}]
            clear_session(self._session_name)
            self._current_tool_block = None
            self._history.clear()
            self._history_index = 0
            self._container().remove_children()
            self._append_sync(Static(Text("Conversation cleared.", style="dim")))
            return

        if text == "/todo-clear":
            panel = self.query_one("#todo-panel", TodoPanel)
            panel.todos = []
            panel.display = False
            self._append_sync(Static(Text("Todo list cleared.", style="dim")))
            return

        if text.startswith("/sessions"):
            self._handle_sessions_command(text)
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
                self.query_one("#usage-bar", Static).update(
                    format_usage(self._total_in, self._total_out, self._total_cost, self._model, CONTEXT_WINDOWS.get(MODELS[self._model], 0))
                )
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
            self._messages = [{"role": "system", "content": load_system_prompt()}]
            self._current_tool_block = None
            self._history.clear()
            self._history_index = 0
            self._container().remove_children()
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
            self._messages = saved
            self._current_tool_block = None
            self._history = [m["content"] for m in saved if m.get("role") == "user"]
            self._history_index = len(self._history)
            self._container().remove_children()
            user_turns = len(self._history)
            self._append_sync(Static(Text.assemble(
                ("Loaded session ", "dim"),
                (arg, "bold"),
                (f" ({user_turns} user turn{'s' if user_turns != 1 else ''}).", "dim"),
            )))
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

        self._append_sync(Static(Text("Unknown subcommand. Type /sessions help for usage.", style="dim")))

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
            ctx_window = CONTEXT_WINDOWS.get(MODELS[self._model], 0)
            self.query_one("#usage-bar", Static).update(
                format_usage(self._total_in, self._total_out, self._total_cost, self._model, ctx_window)
            )
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
