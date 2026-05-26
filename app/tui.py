import asyncio
import json
import re
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Input, Button, Static
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual import work
from rich.markup import escape
from rich.text import Text
from .agent import run_agent, MODELS, DEFAULT_MODEL
from .config import load_system_prompt
from .format import format_usage
from .session import clear_session, load_session, save_session
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
            text = text[:200] + "…"
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

    #send-btn {
        width: 8;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-area"):
            yield VerticalScroll(id="chat-log")
            yield TodoPanel(id="todo-panel")
        with Vertical(id="bottom-bar"):
            yield Static(format_usage(0, 0, 0.0, DEFAULT_MODEL), id="usage-bar")
            yield Horizontal(
                Input(placeholder="Type a message...", id="user-input"),
                Button("Send", id="send-btn", variant="success"),
                id="input-bar",
            )

    def on_mount(self) -> None:
        self.query_one("#user-input", Input).focus()
        self._total_in = 0
        self._total_out = 0
        self._total_cost = 0.0
        self._pending_confirm: asyncio.Future[bool] | None = None
        self._current_tool_block: ToolBlock | None = None
        self._model = DEFAULT_MODEL
        saved = load_session()
        if saved is not None:
            self._messages: list = saved
            user_turns = sum(1 for m in saved if m.get("role") == "user")
            self._append_sync(Static(Text.assemble(
                ("Loaded previous session ", "dim"),
                (f"({user_turns} user turn{'s' if user_turns != 1 else ''}). ", "dim"),
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._send(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            self._send(self.query_one("#user-input", Input).value)

    def _send(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        inp = self.query_one("#user-input", Input)
        inp.value = ""

        if self._pending_confirm is not None and not self._pending_confirm.done():
            self._answer_confirm(text)
            return

        if text == "/clear":
            self._messages = [{"role": "system", "content": load_system_prompt()}]
            clear_session()
            self._current_tool_block = None
            self._container().remove_children()
            self._append_sync(Static(Text("Conversation cleared.", style="dim")))
            return

        if text == "/todo-clear":
            panel = self.query_one("#todo-panel", TodoPanel)
            panel.todos = []
            panel.display = False
            self._append_sync(Static(Text("Todo list cleared.", style="dim")))
            return

        if text == "/model" or text.startswith("/model "):
            arg = text[7:].strip()
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
                self.query_one("#usage-bar", Static).update(
                    format_usage(self._total_in, self._total_out, self._total_cost, self._model)
                )
            else:
                options = ", ".join(MODELS)
                self._append_sync(Static(Text.assemble(
                    (f"Unknown model: {arg}", "bold red"),
                    (" — available: ", "dim"),
                    (options, "bold"),
                )))
            return

        inp.disabled = True
        self.query_one("#send-btn", Button).disabled = True
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
            self.query_one("#usage-bar", Static).update(
                format_usage(self._total_in, self._total_out, self._total_cost, self._model)
            )

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
            send_btn = self.query_one("#send-btn", Button)
            inp.disabled = False
            send_btn.disabled = False
            inp.placeholder = "Approve? (y / n)"
            inp.focus()
            try:
                return await self._pending_confirm
            finally:
                self._pending_confirm = None
                inp.placeholder = "Type a message..."
                inp.disabled = True
                send_btn.disabled = True

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
            save_session(self._messages)
            inp = self.query_one("#user-input", Input)
            inp.disabled = False
            self.query_one("#send-btn", Button).disabled = False
            inp.focus()
