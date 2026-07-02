import shlex
import sys

from app.tools import Bash, Edit, Glob, Grep, Read, TodoWrite, Write

# --- Glob ---

def test_glob_finds_matching_files(tmp_path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.py").write_text("x")
    (tmp_path / "c.txt").write_text("x")
    result = Glob("*.py", str(tmp_path))
    assert "a.py" in result
    assert "b.py" in result
    assert "c.txt" not in result


def test_glob_recursive_pattern(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text("x")
    result = Glob("**/*.py", str(tmp_path))
    assert "deep.py" in result


def test_glob_skips_git_and_venv(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("x")
    (tmp_path / "real.py").write_text("x")
    result = Glob("**/*", str(tmp_path))
    assert ".git" not in result
    assert ".venv" not in result
    assert "real.py" in result


def test_glob_truncates_at_50(tmp_path):
    for i in range(60):
        (tmp_path / f"file{i}.py").write_text("x")
    result = Glob("*.py", str(tmp_path))
    assert "showing 50 of 60" in result


def test_glob_nonexistent_path():
    result = Glob("*.py", "/nonexistent/path/xyz123")
    assert result.startswith("Error:")


def test_glob_no_matches(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    result = Glob("*.py", str(tmp_path))
    assert result == "No files found."


# --- Grep ---

def test_grep_finds_matches(tmp_path):
    (tmp_path / "a.py").write_text("hello world\nfoo bar\n")
    result = Grep("hello", str(tmp_path))
    assert "a.py:1: hello world" in result


def test_grep_include_filter(tmp_path):
    (tmp_path / "a.py").write_text("hello\n")
    (tmp_path / "b.txt").write_text("hello\n")
    result = Grep("hello", str(tmp_path), include="*.py")
    assert "a.py" in result
    assert "b.txt" not in result


def test_grep_skips_git_and_venv(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("hello\n")
    (tmp_path / "real.py").write_text("hello\n")
    result = Grep("hello", str(tmp_path))
    assert ".git" not in result
    assert "real.py" in result


def test_grep_skips_binary_files(tmp_path):
    (tmp_path / "binary.bin").write_bytes(b"\x00\x01\xff\xfe")
    (tmp_path / "text.py").write_text("hello\n")
    result = Grep("hello", str(tmp_path))
    assert "text.py" in result


def test_grep_truncates_at_100(tmp_path):
    content = "\n".join(f"match {i}" for i in range(110)) + "\n"
    (tmp_path / "big.py").write_text(content)
    result = Grep("match", str(tmp_path))
    assert "showing 100 of 110" in result


def test_grep_invalid_regex():
    result = Grep("[invalid", ".")
    assert result.startswith("Error: invalid pattern")


def test_grep_nonexistent_path():
    result = Grep("hello", "/nonexistent/path/xyz123")
    assert result.startswith("Error:")


def test_grep_no_matches(tmp_path):
    (tmp_path / "a.py").write_text("nothing here\n")
    result = Grep("zzznomatch", str(tmp_path))
    assert result == "No matches found."


# --- Edit ---

def test_edit_unique_match(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\ny = 2\n")
    result = Edit(str(f), "x = 1", "x = 42")
    assert "-x = 1" in result
    assert "+x = 42" in result
    assert f.read_text() == "x = 42\ny = 2\n"


def test_edit_preserves_indentation(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n")
    result = Edit(str(f), "    return 1", "    return 2")
    assert "-    return 1" in result
    assert "+    return 2" in result
    assert f.read_text() == "def f():\n    return 2\n"


def test_edit_no_match(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("hello\n")
    result = Edit(str(f), "world", "earth")
    assert result.startswith("Error:")
    assert "not found" in result
    assert f.read_text() == "hello\n"


def test_edit_multiple_matches_without_replace_all(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x\nx\nx\n")
    result = Edit(str(f), "x", "y")
    assert result.startswith("Error:")
    assert "3 locations" in result
    assert f.read_text() == "x\nx\nx\n"


def test_edit_replace_all(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x\nx\nx\n")
    result = Edit(str(f), "x", "y", replace_all=True)
    assert result.startswith("--- a/")
    assert f.read_text() == "y\ny\ny\n"


def test_edit_empty_old_string(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("hello\n")
    result = Edit(str(f), "", "x")
    assert result.startswith("Error:")
    assert "Use Write" in result


def test_edit_identical_strings(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("hello\n")
    result = Edit(str(f), "hello", "hello")
    assert result.startswith("Error:")
    assert "identical" in result


def test_edit_missing_file(tmp_path):
    result = Edit(str(tmp_path / "nope.py"), "a", "b")
    assert result.startswith("Error:")
    assert "not found" in result


def test_edit_binary_file_reports_error(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\xff\xfe\x01")
    result = Edit(str(f), "a", "b")
    assert result.startswith("Error:")
    assert "UTF-8" in result
    assert f.read_bytes() == b"\x00\xff\xfe\x01"


# --- Write ---

def test_write_new_file_shows_additions(tmp_path):
    f = tmp_path / "new.py"
    result = Write(str(f), "line1\nline2\n")
    assert result.startswith("--- a/")
    assert "+line1" in result
    assert "+line2" in result
    assert f.read_text() == "line1\nline2\n"


def test_write_existing_file_shows_diff(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\ny = 2\n")
    result = Write(str(f), "x = 1\ny = 3\n")
    assert "-y = 2" in result
    assert "+y = 3" in result
    assert "x = 1" in result  # unchanged context line present


def test_write_no_change_reports_no_change(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("same\n")
    result = Write(str(f), "same\n")
    assert "no changes" in result


def test_write_over_binary_file_does_not_crash(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\xff\xfe\x01")
    result = Write(str(f), "now text\n")
    assert result.startswith("--- a/")
    assert f.read_text() == "now text\n"


# --- Read ---

def test_read_returns_file_content(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello\n")
    assert Read(str(f)) == "hello\n"


def test_read_missing_file_reports_error(tmp_path):
    result = Read(str(tmp_path / "nope.txt"))
    assert result.startswith("Error reading file:")


def test_read_binary_file_does_not_crash(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\xff\xfe\x01")
    result = Read(str(f))
    assert not result.startswith("Error")


# --- Bash ---

def test_bash_success_exit_zero():
    result = Bash("exit 0")
    assert result.startswith("[exit 0]")


def test_bash_nonzero_exit_captured():
    result = Bash("exit 3")
    assert result.startswith("[exit 3]")


def test_bash_stdout_after_exit_marker():
    result = Bash("echo hello")
    assert result.startswith("[exit 0]")
    assert "hello" in result


def test_bash_timeout_kills_and_returns_partial_output():
    code = "import sys, time; print('partial', flush=True); time.sleep(30)"
    result = Bash(f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}", timeout=1)

    assert result.startswith("[error] Command timed out after 1s")
    assert "partial" in result


def test_bash_keeps_stdout_and_stderr_separate():
    code = "import sys; print('out'); print('warn', file=sys.stderr)"
    result = Bash(f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}")

    assert result.startswith("[exit 0]")
    assert "[stdout]\nout\n" in result
    assert "[stderr]\nwarn\n" in result
    assert result.index("[stdout]") < result.index("[stderr]")


# --- TodoWrite ---

def test_todo_write_valid_list():
    todos = [
        {"id": 1, "title": "First task", "status": "completed"},
        {"id": 2, "title": "Second task", "status": "in-progress"},
        {"id": 3, "title": "Third task", "status": "not-started"},
    ]
    result = TodoWrite(todos)
    assert "Todo list updated" in result
    assert "✓ First task" in result
    assert "● Second task" in result
    assert "○ Third task" in result


def test_todo_write_empty_list():
    result = TodoWrite([])
    assert "Todo list updated" in result


def test_todo_write_invalid_not_list():
    result = TodoWrite("oops")
    assert result.startswith("Error")


def test_todo_write_missing_field():
    result = TodoWrite([{"id": 1, "title": "x"}])
    assert "missing required field: status" in result


def test_todo_write_invalid_status():
    result = TodoWrite([{"id": 1, "title": "x", "status": "done"}])
    assert "invalid status" in result


def test_todo_write_invalid_item_type():
    result = TodoWrite(["not a dict"])
    assert result.startswith("Error")
