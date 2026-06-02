import shlex
import sys

from app.tools import Bash, MAX_TOOL_OUTPUT_CHARS, Read


def test_read_truncates_large_file_output(tmp_path):
    f = tmp_path / "large.txt"
    content = "".join(f"line-{i:04d} {'x' * 30}\n" for i in range(8000))
    f.write_text(content)

    result = Read(str(f))

    assert len(result) <= MAX_TOOL_OUTPUT_CHARS
    assert "[output truncated:" in result
    assert "line-0000" in result
    assert "line-7999" in result
    assert "line-4000" not in result


def test_bash_truncates_large_stdout():
    code = "for i in range(8000): print(f'line-{i:04d} ' + 'x' * 30)"

    result = Bash(f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}")

    assert len(result) <= MAX_TOOL_OUTPUT_CHARS
    assert result.startswith("[exit 0]")
    assert "[stdout]" in result
    assert "[output truncated:" in result
    assert "line-0000" in result
    assert "line-7999" in result
    assert "line-4000" not in result


def test_bash_truncates_stdout_and_stderr_under_one_cap():
    code = (
        "import sys\n"
        "for i in range(5000): print(f'out-{i:04d} ' + 'x' * 20)\n"
        "for i in range(5000): print(f'err-{i:04d} ' + 'y' * 20, file=sys.stderr)"
    )

    result = Bash(f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}")

    assert len(result) <= MAX_TOOL_OUTPUT_CHARS
    assert "[stdout]" in result
    assert "[stderr]" in result
    assert result.count("[output truncated:") == 2
    assert "out-0000" in result
    assert "out-4999" in result
    assert "err-0000" in result
    assert "err-4999" in result
    assert "out-2500" not in result
    assert "err-2500" not in result
