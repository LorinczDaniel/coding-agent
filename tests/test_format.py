from app.format import diff_line_style, format_usage, is_diff, parse_exit_code


def test_format_usage_zero():
    assert format_usage(0, 0, 0.0) == "session: ↑ 0 · ↓ 0 · $0.0000"


def test_format_usage_thousands_separator():
    assert format_usage(12400, 3100, 0.042) == "session: ↑ 12,400 · ↓ 3,100 · $0.0420"


def test_format_usage_four_decimal_cost():
    assert format_usage(1, 1, 0.0001) == "session: ↑ 1 · ↓ 1 · $0.0001"


def test_format_usage_rounds_cost_to_four_decimals():
    assert format_usage(0, 0, 0.123456) == "session: ↑ 0 · ↓ 0 · $0.1235"


# --- parse_exit_code ---

def test_parse_exit_code_zero():
    code, body = parse_exit_code("[exit 0]\nhello\n")
    assert code == 0
    assert body == "hello\n"


def test_parse_exit_code_nonzero():
    code, body = parse_exit_code("[exit 127]\ncommand not found\n")
    assert code == 127
    assert body == "command not found\n"


def test_parse_exit_code_negative():
    code, _ = parse_exit_code("[exit -1]\n")
    assert code == -1


def test_parse_exit_code_no_marker():
    code, body = parse_exit_code("just some output")
    assert code is None
    assert body == "just some output"


# --- diff_line_style ---

def test_diff_style_addition():
    assert diff_line_style("+new line") == "green"


def test_diff_style_deletion():
    assert diff_line_style("-old line") == "red"


def test_diff_style_hunk_header():
    assert diff_line_style("@@ -1,3 +1,4 @@") == "cyan"


def test_diff_style_file_headers_not_treated_as_add_remove():
    assert diff_line_style("+++ b/file.py") == "bold dim"
    assert diff_line_style("--- a/file.py") == "bold dim"


def test_diff_style_context_line():
    assert diff_line_style(" unchanged") == "dim white"


# --- is_diff ---

def test_is_diff_true_for_unified_diff():
    assert is_diff("--- a/foo.py\n+++ b/foo.py\n") is True


def test_is_diff_false_for_status_message():
    assert is_diff("Wrote foo.py (no changes)") is False


# --- format_usage with model ---

def test_format_usage_with_model():
    assert format_usage(100, 50, 0.01, "haiku") == "session: ↑ 100 · ↓ 50 · $0.0100 · haiku"


def test_format_usage_with_model_sonnet():
    assert format_usage(100, 50, 0.05, "sonnet") == "session: ↑ 100 · ↓ 50 · $0.0500 · sonnet"


# --- format_usage with context window ---

def test_format_usage_with_context_window():
    result = format_usage(12400, 3100, 0.042, "haiku", 200_000)
    assert "ctx 12.4k/200.0k" in result
    assert result.endswith("· haiku")


def test_format_usage_context_window_millions():
    result = format_usage(1_200_000, 50_000, 0.5, "sonnet", 2_000_000)
    assert "ctx 1.2M/2.0M" in result


def test_format_usage_context_window_zero_omitted():
    result = format_usage(100, 50, 0.01, "haiku", 0)
    assert "ctx" not in result


def test_format_usage_context_window_small_tokens():
    result = format_usage(500, 100, 0.001, "haiku", 200_000)
    assert "ctx 500/200.0k" in result
