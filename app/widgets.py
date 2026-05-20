from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from .format import diff_line_style, is_diff, parse_exit_code

MAX_BLOCK_LINES = 15


def _join(text_lines: list[Text]) -> Text:
    return Text("\n").join(text_lines)


def _line_renderables(lines: list[str], style):
    def mk(line: str) -> Text:
        st = style(line) if callable(style) else style
        return Text.assemble(("│ ", "dim"), (line, st))

    preview = [mk(line) for line in lines[:MAX_BLOCK_LINES]]
    hidden_lines = lines[MAX_BLOCK_LINES:]
    hidden = _join([mk(line) for line in hidden_lines]) if hidden_lines else None
    return _join(preview), hidden, len(hidden_lines)


def _read_renderables(result: str, file_path: str):
    all_lines = result.splitlines()
    shown = "\n".join(all_lines[:MAX_BLOCK_LINES])
    rest_lines = all_lines[MAX_BLOCK_LINES:]
    try:
        lexer = Syntax.guess_lexer(file_path, code=shown)
    except Exception:
        lexer = "text"

    def syn(code: str, start: int) -> Syntax:
        return Syntax(
            code, lexer,
            theme="ansi_dark",
            line_numbers=True,
            start_line=start,
            background_color="default",
            word_wrap=True,
        )

    preview = syn(shown, 1)
    hidden = syn("\n".join(rest_lines), MAX_BLOCK_LINES + 1) if rest_lines else None
    return preview, hidden, len(rest_lines)


def build_tool_body(name: str, result: str, args: dict):
    """Return (preview, hidden_or_None, hidden_count, exit_code_or_None)."""
    if name == "Bash":
        code, body = parse_exit_code(result)
        preview, hidden, count = _line_renderables(body.strip().splitlines(), "white")
        return preview, hidden, count, code
    if name in ("Write", "Edit") and is_diff(result):
        preview, hidden, count = _line_renderables(result.splitlines(), diff_line_style)
        return preview, hidden, count, None
    if name == "Read" and not result.startswith("Error"):
        preview, hidden, count = _read_renderables(result, args.get("file_path", ""))
        return preview, hidden, count, None
    preview, hidden, count = _line_renderables(result.strip().splitlines(), "white")
    return preview, hidden, count, None


def _footer(exit_code: int | None) -> Text:
    if exit_code is None:
        return Text("└" + "─" * 42, style="dim")
    code_style = "bold green" if exit_code == 0 else "bold red"
    return Text.assemble(("└─ ", "dim"), (f"exit {exit_code} ", code_style), ("─" * 32, "dim"))


class ToolToggle(Static):
    def __init__(self, hidden_count: int, target: Static) -> None:
        self._hidden_count = hidden_count
        self._target = target
        self._expanded = False
        super().__init__(self._label())

    def _label(self) -> Text:
        arrow = "▾" if self._expanded else "▸"
        verb = "hide" if self._expanded else f"show {self._hidden_count} more lines"
        return Text(f"│ {arrow} {verb}", style="dim")

    def on_click(self) -> None:
        self._expanded = not self._expanded
        self.update(self._label())
        self._target.display = self._expanded


class ToolBlock(Vertical):
    def __init__(self, name: str, args_str: str) -> None:
        super().__init__()
        self._name = name
        self._args_str = args_str
        self._running: Static | None = None

    def compose(self) -> ComposeResult:
        sep = "─" * max(4, 40 - len(self._name))
        yield Static(Text.assemble(("┌─ ", "dim"), (self._name, "bold yellow"), (f" {sep}", "dim")))
        if self._args_str:
            yield Static(Text.assemble(("│ ", "dim"), (self._args_str, "dim white")))
        self._running = Static(Text("│ running…", style="dim italic"))
        yield self._running

    async def populate(self, preview, hidden, hidden_count: int, exit_code: int | None) -> None:
        if self._running is not None:
            await self._running.remove()
            self._running = None
        await self.mount(Static(preview))
        if hidden is not None:
            box = Static(hidden)
            box.display = False
            await self.mount(box)
            await self.mount(ToolToggle(hidden_count, box))
        await self.mount(Static(_footer(exit_code)))
