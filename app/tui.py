import json
import re
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, RichLog, Input, Button, Static
from textual.containers import Horizontal
from textual import work
from rich.markup import escape
from rich.text import Text
from .agent import run_agent
from .config import load_system_prompt
from .format import format_usage
from .session import clear_session, load_session, save_session


def _md_to_rich(text: str) -> str:
    s = escape(text)
    s = re.sub(r'\*\*(.+?)\*\*', r'[bold]\1[/bold]', s)
    s = re.sub(r'`(.+?)`', r'[code]\1[/code]', s)
    return s


class AgentApp(App):
    TITLE = "Agent Daniel"
    BINDINGS = [Binding("ctrl+x", "quit", "Quit", priority=True)]

    CSS = """
    #chat-log {
        height: 1fr;
        padding: 0 1;
    }

    #usage-bar {
        height: 1;
        dock: bottom;
        padding: 0 1;
        color: $text-muted;
        background: $panel;
    }

    #input-bar {
        height: 3;
        dock: bottom;
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
        yield RichLog(id="chat-log", wrap=True, highlight=False, markup=True)
        yield Horizontal(
            Input(placeholder="Type a message...", id="user-input"),
            Button("Send", id="send-btn", variant="success"),
            id="input-bar",
        )
        yield Static(format_usage(0, 0, 0.0), id="usage-bar")

    def on_mount(self) -> None:
        self.query_one("#user-input", Input).focus()
        self._total_in = 0
        self._total_out = 0
        self._total_cost = 0.0
        log = self.query_one("#chat-log", RichLog)
        saved = load_session()
        if saved is not None:
            self._messages: list = saved
            user_turns = sum(1 for m in saved if m.get("role") == "user")
            log.write(Text.assemble(
                ("Loaded previous session ", "dim"),
                (f"({user_turns} user turn{'s' if user_turns != 1 else ''}). ", "dim"),
                ("Type ", "dim"),
                ("/clear", "bold yellow"),
                (" to start fresh.", "dim"),
            ))
            log.write("")
        else:
            self._messages = [{"role": "system", "content": load_system_prompt()}]

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._send(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "send-btn":
            self._send(self.query_one("#user-input", Input).value)

    def _send(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        log = self.query_one("#chat-log", RichLog)
        inp = self.query_one("#user-input", Input)
        inp.value = ""

        if text == "/clear":
            self._messages = [{"role": "system", "content": load_system_prompt()}]
            clear_session()
            log.clear()
            log.write(Text("Conversation cleared.", style="dim"))
            log.write("")
            return

        inp.disabled = True
        self.query_one("#send-btn", Button).disabled = True
        log.write("")
        log.write(Text.assemble(("You: ", "bold green"), (text, "white")))
        self._messages.append({"role": "user", "content": text})
        self._run_agent()

    @work(exclusive=True)
    async def _run_agent(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        first_text_chunk = True
        text_buffer: list[str] = []

        def flush_buffer() -> None:
            nonlocal first_text_chunk
            text = "".join(text_buffer)
            text_buffer.clear()
            if not text:
                return
            rendered = _md_to_rich(text)
            if first_text_chunk:
                log.write("")
                log.write(f"[bold blue]Agent:[/bold blue] {rendered}")
                first_text_chunk = False
            else:
                log.write(rendered)

        def on_text(delta: str) -> None:
            text_buffer.append(delta)
            combined = "".join(text_buffer)
            if "\n" in combined:
                lines = combined.split("\n")
                incomplete = lines[-1]
                for line in lines[:-1]:
                    text_buffer.clear()
                    text_buffer.append(line)
                    flush_buffer()
                text_buffer.clear()
                text_buffer.append(incomplete)

        def on_tool_start(name: str, args_json: str) -> None:
            nonlocal first_text_chunk
            flush_buffer()
            if not first_text_chunk:
                first_text_chunk = True
            try:
                args = json.loads(args_json)
                args_str = "  ".join(f"{k}={v}" for k, v in args.items())
            except Exception:
                args_str = args_json
            sep = "─" * max(4, 40 - len(name))
            log.write(Text.assemble(("┌─ ", "dim"), (name, "bold yellow"), (f" {sep}", "dim")))
            log.write(Text.assemble(("│ ", "dim"), (args_str, "dim white")))

        def on_tool_result(_name: str, result: str) -> None:
            nonlocal first_text_chunk
            first_text_chunk = True
            lines = result.strip().splitlines()
            for line in lines[:15]:
                log.write(Text.assemble(("│ ", "dim"), (line, "white")))
            if len(lines) > 15:
                log.write(Text.assemble(("│ ", "dim"), (f"... ({len(lines) - 15} more lines)", "dim")))
            log.write(Text("└" + "─" * 42, style="dim"))
            log.write("")

        def on_usage(prompt: int, completion: int, cost: float) -> None:
            self._total_in += prompt
            self._total_out += completion
            self._total_cost += cost
            self.query_one("#usage-bar", Static).update(
                format_usage(self._total_in, self._total_out, self._total_cost)
            )

        try:
            await run_agent(self._messages, on_text, on_tool_start, on_tool_result, on_usage)
        except Exception as e:
            log.write(Text.assemble(("Error: ", "bold red"), (str(e), "white")))
        finally:
            flush_buffer()
            save_session(self._messages)
            inp = self.query_one("#user-input", Input)
            inp.disabled = False
            self.query_one("#send-btn", Button).disabled = False
            inp.focus()
