from app.widgets import build_tool_body


def _styles_for(text, needle: str) -> list[str]:
    start = text.plain.index(needle)
    end = start + len(needle)
    return [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= end
    ]


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