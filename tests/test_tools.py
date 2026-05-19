from app.tools import Glob


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
