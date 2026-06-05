from app.widgets import build_tool_body

from textual.app import App, ComposeResult
from textual.widgets import Static

from app.widgets import ToolBlock, ToolToggle, TodoPanel


def _styles_for(text, needle: str) -> list[str]:
    start = text.plain.index(needle)
    end = start + len(needle)
    return [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= end
    ]


class _Harness(App):
    """Minimal app used to mount widgets for testing."""

    def __init__(self, *widgets):
        super().__init__()
        self._widgets = widgets

    def compose(self) -> ComposeResult:
        for widget in self._widgets:
            yield widget


def test_bash_tool_body_separates_stdout_and_stderr_styles():
    result = "[exit 0]\n[stdout]\nnormal\n[stderr]\nwarning\n"

    preview, hidden, hidden_count, exit_code = build_tool_body("Bash", result, {})

    assert exit_code == 0
    assert hidden is None
    assert hidden_count == 0
    assert "stdout" in preview.plain
    assert "normal" in preview.plain
    assert "stderr" in preview.plain
    assert "warning" in preview.plain
    assert "white" in _styles_for(preview, "normal")
    assert "dim red" in _styles_for(preview, "warning")


def test_todo_panel_renders_no_tasks_when_empty():
    panel = TodoPanel()
    panel.todos = []

    rendered = panel.render()

    assert rendered.plain == "No tasks"


def test_todo_panel_renders_status_icons_and_titles():
    panel = TodoPanel()
    panel.todos = [
        {"title": "design api", "status": "completed"},
        {"title": "write code", "status": "in-progress"},
        {"title": "ship it", "status": "not-started"},
    ]

    rendered = panel.render()

    assert "design api" in rendered.plain
    assert "write code" in rendered.plain
    assert "ship it" in rendered.plain
    assert "✓" in rendered.plain
    assert "●" in rendered.plain
    assert "○" in rendered.plain
    assert "dim strike" in _styles_for(rendered, "design api")
    assert "white" in _styles_for(rendered, "write code")


def test_todo_panel_uses_fallback_icon_for_unknown_status():
    panel = TodoPanel()
    panel.todos = [{"title": "mystery", "status": "weird"}]

    rendered = panel.render()

    assert "?" in rendered.plain
    assert "red" in _styles_for(rendered, "?")


def test_tool_toggle_label_starts_collapsed():
    toggle = ToolToggle(3, Static("hidden"))

    label = toggle._label()

    assert "▸" in label.plain
    assert "show 3 more lines" in label.plain


async def test_tool_toggle_on_click_expands_and_collapses():
    target = Static("hidden")
    target.display = False
    toggle = ToolToggle(2, target)
    app = _Harness(target, toggle)
    async with app.run_test():
        toggle.on_click()

        assert toggle._expanded is True
        assert target.display is True
        assert "▾" in toggle._label().plain
        assert "hide" in toggle._label().plain

        toggle.on_click()

        assert toggle._expanded is False
        assert target.display is False
        assert "▸" in toggle._label().plain
        assert "show 2 more lines" in toggle._label().plain


async def test_tool_block_populate_without_hidden_lines():
    block = ToolBlock("Read", "file_path=demo.py")
    app = _Harness(block)
    async with app.run_test():
        preview, hidden, hidden_count, exit_code = build_tool_body("Read", "line one\nline two", {"file_path": "demo.py"})
        await block.populate(preview, hidden, hidden_count, exit_code)

        statics = block.query(Static)
        assert block._running is None
        assert len(block.query(ToolToggle)) == 0
        assert len(statics) >= 1


async def test_tool_block_populate_with_hidden_lines_adds_toggle():
    block = ToolBlock("Bash", "cmd=ls")
    app = _Harness(block)
    async with app.run_test():
        lines = "\n".join(f"line {i}" for i in range(40))
        result = f"[exit 0]\n[stdout]\n{lines}\n"
        preview, hidden, hidden_count, exit_code = build_tool_body("Bash", result, {})
        assert hidden is not None

        await block.populate(preview, hidden, hidden_count, exit_code)

        toggles = block.query(ToolToggle)
        assert len(toggles) == 1
        toggle = toggles.first()
        hidden_box = toggle._target
        assert hidden_box.display is False

        toggle.on_click()
        assert hidden_box.display is True


async def test_tool_block_populate_removes_running_indicator():
    block = ToolBlock("Read", "")
    app = _Harness(block)
    async with app.run_test():
        assert block._running is not None
        preview, hidden, hidden_count, exit_code = build_tool_body("Read", "content", {"file_path": "x.txt"})
        await block.populate(preview, hidden, hidden_count, exit_code)

        assert block._running is None
