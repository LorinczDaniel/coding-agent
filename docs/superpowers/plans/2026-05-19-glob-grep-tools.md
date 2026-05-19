# Glob and Grep Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `Glob` (file pattern matching) and `Grep` (content search) tools to the agent so the model can navigate codebases without resorting to Bash one-liners.

**Architecture:** Both tools are Python-native implementations added to `app/tools.py` following the existing pattern (function + OpenAI schema dict). `app/agent.py` imports and registers them. Output is capped to prevent context flooding.

**Tech Stack:** Python 3.14, pathlib, re, pytest

---

## File Map

| File | Action |
|---|---|
| `app/tools.py` | Add `import re`, `from pathlib import Path`, `_SKIP_DIRS`, `Glob`, `Grep`, `GLOB_TOOL`, `GREP_TOOL` |
| `app/agent.py` | Update import, tools list, and dispatch chain |
| `tests/test_tools.py` | Create — unit tests for Glob and Grep |

---

### Task 1: Implement Glob with TDD

**Files:**
- Create: `tests/test_tools.py`
- Modify: `app/tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tools.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
wsl -d Ubuntu -- bash -c "cd /home/daniellorincz/personal/codecrafters-claude-code-python && ~/.local/bin/uv run pytest tests/test_tools.py -v 2>&1"
```

Expected: `ImportError: cannot import name 'Glob' from 'app.tools'`

- [ ] **Step 3: Add imports and Glob to app/tools.py**

Add `import re` and `from pathlib import Path` after the existing `import sys` line, and add `_SKIP_DIRS`, `GLOB_TOOL`, and `Glob` after the existing `BASH_TOOL` dict and `Bash` function. The full additions are:

At the top of `app/tools.py`, replace:
```python
import subprocess
import sys
```
With:
```python
import re
import subprocess
import sys
from pathlib import Path

_SKIP_DIRS = {".git", ".venv"}
```

After the existing `BASH_TOOL` dict (after line 49), add:

```python
GLOB_TOOL = {
    "type": "function",
    "function": {
        "name": "Glob",
        "description": "Find files matching a glob pattern. Use ** for recursive search (e.g. **/*.py).",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py' or 'src/*.ts'"},
                "path": {"type": "string", "description": "Directory to search in (default: current directory)"},
            },
            "required": ["pattern"],
        },
    },
}
```

After the existing `Bash` function (at the end of the file), add:

```python
def Glob(pattern: str, path: str = ".") -> str:
    try:
        base = Path(path)
        if not base.exists():
            return f"Error: path does not exist: {path}"
        matches = sorted(
            str(p.relative_to(base))
            for p in base.glob(pattern)
            if not any(part in _SKIP_DIRS for part in p.parts)
        )
        if not matches:
            return "No files found."
        total = len(matches)
        cap = 50
        result = "\n".join(matches[:cap])
        if total > cap:
            result += f"\n(showing {cap} of {total} results)"
        return result
    except Exception as e:
        return f"Error: {e}"
```

- [ ] **Step 4: Run Glob tests to verify they pass**

```bash
wsl -d Ubuntu -- bash -c "cd /home/daniellorincz/personal/codecrafters-claude-code-python && ~/.local/bin/uv run pytest tests/test_tools.py -k glob -v 2>&1"
```

Expected:
```
PASSED tests/test_tools.py::test_glob_finds_matching_files
PASSED tests/test_tools.py::test_glob_recursive_pattern
PASSED tests/test_tools.py::test_glob_skips_git_and_venv
PASSED tests/test_tools.py::test_glob_truncates_at_50
PASSED tests/test_tools.py::test_glob_nonexistent_path
PASSED tests/test_tools.py::test_glob_no_matches
```

- [ ] **Step 5: Commit**

```bash
wsl -d Ubuntu -- bash -c "cd /home/daniellorincz/personal/codecrafters-claude-code-python && git add app/tools.py tests/test_tools.py && git commit -m 'feat: add Glob tool'"
```

---

### Task 2: Implement Grep with TDD

**Files:**
- Modify: `tests/test_tools.py`
- Modify: `app/tools.py`

- [ ] **Step 1: Add Grep tests to tests/test_tools.py**

Append these tests to the end of `tests/test_tools.py`:

```python
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
```

- [ ] **Step 2: Run Grep tests to verify they fail**

```bash
wsl -d Ubuntu -- bash -c "cd /home/daniellorincz/personal/codecrafters-claude-code-python && ~/.local/bin/uv run pytest tests/test_tools.py -k grep -v 2>&1"
```

Expected: `ImportError: cannot import name 'Grep' from 'app.tools'`

- [ ] **Step 3: Add GREP_TOOL schema and Grep function to app/tools.py**

After `GLOB_TOOL` dict, add:

```python
GREP_TOOL = {
    "type": "function",
    "function": {
        "name": "Grep",
        "description": "Search file contents for lines matching a regex pattern.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "Directory or file to search in (default: current directory)"},
                "include": {"type": "string", "description": "Filename glob filter, e.g. '*.py' (default: '*')"},
            },
            "required": ["pattern"],
        },
    },
}
```

After the `Glob` function, add:

```python
def Grep(pattern: str, path: str = ".", include: str = "*") -> str:
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid pattern: {e}"
    try:
        base = Path(path)
        if not base.exists():
            return f"Error: path does not exist: {path}"
        files = (
            [base] if base.is_file()
            else sorted(
                p for p in base.rglob(include)
                if p.is_file() and not any(part in _SKIP_DIRS for part in p.parts)
            )
        )
        base_for_rel = base.parent if base.is_file() else base
        matches: list[str] = []
        total = 0
        cap = 100
        for filepath in files:
            try:
                lines = filepath.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(lines, 1):
                if regex.search(line):
                    total += 1
                    if total <= cap:
                        rel = filepath.relative_to(base_for_rel)
                        matches.append(f"{rel}:{lineno}: {line}")
        if not matches:
            return "No matches found."
        result = "\n".join(matches)
        if total > cap:
            result += f"\n(showing {cap} of {total} matches)"
        return result
    except Exception as e:
        return f"Error: {e}"
```

- [ ] **Step 4: Run all tool tests to verify they pass**

```bash
wsl -d Ubuntu -- bash -c "cd /home/daniellorincz/personal/codecrafters-claude-code-python && ~/.local/bin/uv run pytest tests/test_tools.py -v 2>&1"
```

Expected: 14 tests passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
wsl -d Ubuntu -- bash -c "cd /home/daniellorincz/personal/codecrafters-claude-code-python && git add app/tools.py tests/test_tools.py && git commit -m 'feat: add Grep tool'"
```

---

### Task 3: Register Glob and Grep in agent.py

**Files:**
- Modify: `app/agent.py`

- [ ] **Step 1: Update the import line in app/agent.py**

Replace:
```python
from .tools import Read, Write, Bash, READ_TOOL, WRITE_TOOL, BASH_TOOL
```
With:
```python
from .tools import Bash, Glob, Grep, Read, Write, BASH_TOOL, GLOB_TOOL, GREP_TOOL, READ_TOOL, WRITE_TOOL
```

- [ ] **Step 2: Update the tools list in run_agent()**

Replace:
```python
            tools=[READ_TOOL, WRITE_TOOL, BASH_TOOL],
```
With:
```python
            tools=[READ_TOOL, WRITE_TOOL, BASH_TOOL, GLOB_TOOL, GREP_TOOL],
```

- [ ] **Step 3: Update the dispatch chain**

Replace:
```python
            if tc["name"] == "Read":
                result = Read(args["file_path"])
            elif tc["name"] == "Write":
                result = Write(args["file_path"], args["content"])
            elif tc["name"] == "Bash":
                result = Bash(args["command"])
            else:
                result = f"Unknown tool: {tc['name']}"
```
With:
```python
            if tc["name"] == "Read":
                result = Read(args["file_path"])
            elif tc["name"] == "Write":
                result = Write(args["file_path"], args["content"])
            elif tc["name"] == "Bash":
                result = Bash(args["command"])
            elif tc["name"] == "Glob":
                result = Glob(args["pattern"], args.get("path", "."))
            elif tc["name"] == "Grep":
                result = Grep(args["pattern"], args.get("path", "."), args.get("include", "*"))
            else:
                result = f"Unknown tool: {tc['name']}"
```

- [ ] **Step 4: Run the full test suite**

```bash
wsl -d Ubuntu -- bash -c "cd /home/daniellorincz/personal/codecrafters-claude-code-python && ~/.local/bin/uv run pytest -v 2>&1"
```

Expected: 18 tests passed (4 config + 14 tools), 0 failed.

- [ ] **Step 5: Commit and push**

```bash
wsl -d Ubuntu -- bash -c "cd /home/daniellorincz/personal/codecrafters-claude-code-python && git add app/agent.py && git commit -m 'feat: register Glob and Grep in agent' && git push"
```
