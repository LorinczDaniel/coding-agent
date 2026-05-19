from app.tools import Glob, Grep


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
