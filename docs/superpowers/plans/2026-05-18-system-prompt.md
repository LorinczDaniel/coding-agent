# System Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a two-layer system prompt — a hardcoded coding-assistant base plus a user-editable `system.md` — loaded via a new `app/config.py` module.

**Architecture:** `app/config.py` exposes `load_system_prompt()` which concatenates a hardcoded base with the contents of `system.md` (if present). `app/tui.py` calls it once on mount and pre-populates the message history. `app/agent.py` is untouched.

**Tech Stack:** Python 3.14, pytest, uv

---

## File Map

| File | Action |
|---|---|
| `pyproject.toml` | Modify — add pytest dev dependency |
| `pytest.ini` | Create |
| `tests/__init__.py` | Create (empty) |
| `tests/test_config.py` | Create |
| `app/config.py` | Create |
| `app/tui.py` | Modify — `on_mount` only |
| `system.md.example` | Create |
| `.gitignore` | Modify — add `system.md` |

---

### Task 1: Add pytest and create test infrastructure

**Files:**
- Modify: `pyproject.toml`
- Create: `pytest.ini`
- Create: `tests/__init__.py`

- [ ] **Step 1: Add pytest to pyproject.toml**

Replace the contents of `pyproject.toml` with:

```toml
[project]
name = "claude-agent"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
    "openai>=2.15.0",
    "python-dotenv>=1.0.0",
    "textual>=0.80.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
]
```

- [ ] **Step 2: Install dev dependencies**

```bash
uv sync --group dev
```

Expected: resolves and installs pytest, updates `uv.lock`.

- [ ] **Step 3: Create pytest.ini**

```ini
[pytest]
testpaths = tests
```

- [ ] **Step 4: Create tests/__init__.py**

Create an empty file at `tests/__init__.py`.

- [ ] **Step 5: Verify pytest runs**

```bash
uv run pytest -v
```

Expected:
```
============ no tests ran ============
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock pytest.ini tests/__init__.py
git commit -m "feat: add pytest infrastructure"
```

---

### Task 2: Create app/config.py with TDD

**Files:**
- Create: `tests/test_config.py`
- Create: `app/config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
import pytest
from app.config import _BASE_PROMPT, load_system_prompt


def test_no_system_md_returns_base(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_system_prompt() == _BASE_PROMPT


def test_with_system_md_appends_custom(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "system.md").write_text("Be concise.", encoding="utf-8")
    result = load_system_prompt()
    assert result == f"{_BASE_PROMPT}\n\nBe concise."


def test_base_always_present_when_system_md_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "system.md").write_text("Custom.", encoding="utf-8")
    assert load_system_prompt().startswith(_BASE_PROMPT)


def test_unreadable_system_md_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    system_md = tmp_path / "system.md"
    system_md.write_text("content", encoding="utf-8")
    system_md.chmod(0o000)
    try:
        with pytest.raises(RuntimeError, match="Could not read system.md"):
            load_system_prompt()
    finally:
        system_md.chmod(0o644)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Create app/config.py**

```python
from pathlib import Path

_BASE_PROMPT = """\
You are a coding assistant running in a terminal. You have access to three tools:

- **Read** — read the full contents of a file
- **Write** — create or overwrite a file with new content
- **Bash** — execute a shell command and return its output

Guidelines:
- Read relevant files before making changes
- Make targeted, minimal edits — don't rewrite what doesn't need to change
- After completing a task, briefly explain what you did and why\
"""


def load_system_prompt() -> str:
    custom_path = Path("system.md")
    if not custom_path.exists():
        return _BASE_PROMPT
    try:
        custom = custom_path.read_text(encoding="utf-8").strip()
    except OSError as e:
        raise RuntimeError(f"Could not read system.md: {e}") from e
    return f"{_BASE_PROMPT}\n\n{custom}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected:
```
PASSED tests/test_config.py::test_no_system_md_returns_base
PASSED tests/test_config.py::test_with_system_md_appends_custom
PASSED tests/test_config.py::test_base_always_present_when_system_md_exists
PASSED tests/test_config.py::test_unreadable_system_md_raises
```

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add config module with load_system_prompt"
```

---

### Task 3: Add system.md.example and update .gitignore

**Files:**
- Create: `system.md.example`
- Modify: `.gitignore`

- [ ] **Step 1: Create system.md.example**

```markdown
# Custom instructions

Add your personal instructions below. This file is appended to the agent's
built-in system prompt. Copy this file to `system.md` to activate it.

Examples:
- Prefer Python over shell scripts when both would work
- Always write tests alongside new code
- Keep responses concise — skip the preamble
- When editing files, show a summary of what changed
```

- [ ] **Step 2: Add system.md to .gitignore**

Add this line at the end of `.gitignore`:

```
# User-local agent instructions
system.md
```

- [ ] **Step 3: Verify system.md is ignored**

```bash
touch system.md && git status
```

Expected: `system.md` does not appear in untracked files.

```bash
rm system.md
```

- [ ] **Step 4: Commit**

```bash
git add system.md.example .gitignore
git commit -m "feat: add system.md.example and gitignore rule"
```

---

### Task 4: Wire load_system_prompt into tui.py

**Files:**
- Modify: `app/tui.py`

- [ ] **Step 1: Update the import block in app/tui.py**

At the top of `app/tui.py`, add the import alongside the existing ones:

```python
from .config import load_system_prompt
```

- [ ] **Step 2: Update on_mount to pre-populate messages**

Replace:

```python
    def on_mount(self) -> None:
        self.query_one("#user-input", Input).focus()
        self._messages: list = []
```

With:

```python
    def on_mount(self) -> None:
        self.query_one("#user-input", Input).focus()
        self._messages: list = [{"role": "system", "content": load_system_prompt()}]
```

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all 4 tests pass, none fail.

- [ ] **Step 4: Commit**

```bash
git add app/tui.py
git commit -m "feat: wire system prompt into agent on startup"
```

- [ ] **Step 5: Push**

```bash
git push
```
