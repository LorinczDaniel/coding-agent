import difflib
import re
import subprocess
import sys
from pathlib import Path

_SKIP_DIRS = {".git", ".venv"}
MAX_TOOL_OUTPUT_CHARS = 50 * 1024
TRUNCATED_SECTION_LINES = 200


def _take_head(lines: list[str], budget: int) -> str:
    chunks: list[str] = []
    used = 0
    for line in lines[:TRUNCATED_SECTION_LINES]:
        if used + len(line) > budget:
            remaining = budget - used
            if remaining > 0:
                chunks.append(line[:remaining])
            break
        chunks.append(line)
        used += len(line)
    return "".join(chunks)


def _take_tail(lines: list[str], budget: int) -> str:
    chunks: list[str] = []
    used = 0
    for line in reversed(lines[-TRUNCATED_SECTION_LINES:]):
        if used + len(line) > budget:
            remaining = budget - used
            if remaining > 0:
                chunks.append(line[-remaining:])
            break
        chunks.append(line)
        used += len(line)
    return "".join(reversed(chunks))


def _truncate_output(text: str, max_chars: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(text) <= max_chars:
        return text

    lines = text.splitlines(keepends=True)
    marker = (
        f"\n[output truncated: original {len(text):,} chars across {len(lines):,} lines; "
        f"showing first and last up to {TRUNCATED_SECTION_LINES} lines]\n"
    )
    available = max_chars - len(marker)
    if available <= 0:
        return marker[:max_chars]

    head_budget = available // 2
    tail_budget = available - head_budget
    return _take_head(lines, head_budget) + marker + _take_tail(lines, tail_budget)


def _split_stream_budget(streams: list[tuple[str, str]], available: int) -> dict[str, int]:
    budgets: dict[str, int] = {}
    remaining = available
    pending = streams[:]

    while pending:
        share = max(1, remaining // len(pending))
        oversized: list[tuple[str, str]] = []
        for name, text in pending:
            if len(text) <= share:
                budgets[name] = len(text)
                remaining -= len(text)
            else:
                oversized.append((name, text))

        if len(oversized) == len(pending):
            for name, _ in oversized:
                budgets[name] = share
            break

        pending = oversized

    return budgets


def _format_bash_output(returncode: int, stdout: str, stderr: str) -> str:
    prefix = f"[exit {returncode}]\n"
    streams = [("stdout", stdout)] if stdout else []
    if stderr:
        streams.append(("stderr", stderr))
    if not streams:
        return prefix

    labels_size = sum(len(f"[{name}]\n") for name, _ in streams)
    available = max(1, MAX_TOOL_OUTPUT_CHARS - len(prefix) - labels_size)
    budgets = _split_stream_budget(streams, available)
    output = "".join(
        f"[{name}]\n{_truncate_output(text, budgets[name])}"
        for name, text in streams
    )
    return prefix + output


def _make_diff(old: str, new: str, path: str, max_lines: int = 300) -> str:
    lines = list(difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    ))
    if len(lines) > max_lines:
        extra = len(lines) - max_lines
        lines = lines[:max_lines] + [f"... (diff truncated, {extra} more lines)"]
    return "\n".join(lines)


READ_TOOL = {
    "type": "function",
    "function": {
        "name": "Read",
        "description": "Read and return the content of a file. Large results are truncated to 50KB with the beginning and end preserved.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path to the file to read."}
            },
            "required": ["file_path"],
        },
    },
}

WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "Write",
        "description": "Write content to a file. Overwrites the file if it exists. Prefer Edit for modifying existing files.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path of the file to write to."},
                "content": {"type": "string", "description": "The content to write to the file."},
            },
            "required": ["file_path", "content"],
        },
    },
}

EDIT_TOOL = {
    "type": "function",
    "function": {
        "name": "Edit",
        "description": (
            "Replace a string in a file. Prefer this over Write when modifying an existing file. "
            "`old_string` must match exactly, including whitespace and indentation. "
            "Fails if `old_string` is not found, or if it appears more than once unless `replace_all` is true. "
            "When the match is ambiguous, expand `old_string` with surrounding context until it is unique."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The path of the file to edit."},
                "old_string": {"type": "string", "description": "The exact text to replace."},
                "new_string": {"type": "string", "description": "The replacement text."},
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace every occurrence instead of requiring a unique match. Default false.",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
}

BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "Bash",
        "description": "Execute a shell command. Large stdout/stderr results are truncated to 50KB with the beginning and end preserved.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute."},
                "timeout": {
                    "type": "integer",
                    "description": "Max seconds to wait for the command to finish. Default 120.",
                },
            },
            "required": ["command"],
        },
    },
}

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


def Read(file_path: str) -> str:
    try:
        with open(file_path) as f:
            return _truncate_output(f.read())
    except Exception as e:
        error_msg = f"Error reading file: {e}"
        print(error_msg, file=sys.stderr)
        return error_msg


def Write(file_path: str, content: str) -> str:
    path = Path(file_path)
    try:
        old = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        old = ""
    try:
        path.write_text(content, encoding="utf-8")
    except Exception as e:
        error_msg = f"Error writing to file: {e}"
        print(error_msg, file=sys.stderr)
        return error_msg
    if old == content:
        return f"Wrote {file_path} (no changes)"
    return _make_diff(old, content, file_path)


def Edit(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    if old_string == "":
        return "Error: old_string is empty. Use Write to create a new file."
    if old_string == new_string:
        return "Error: old_string and new_string are identical — no edit to apply."
    path = Path(file_path)
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"Error: file not found: {file_path}"
    except OSError as e:
        return f"Error reading file: {e}"
    count = content.count(old_string)
    if count == 0:
        return (
            f"Error: old_string not found in {file_path}. "
            "Make sure whitespace and indentation match exactly."
        )
    if count > 1 and not replace_all:
        return (
            f"Error: old_string matches {count} locations in {file_path}. "
            "Expand it with surrounding context to make it unique, or pass replace_all=true."
        )
    new_content = content.replace(old_string, new_string)
    try:
        path.write_text(new_content, encoding="utf-8")
    except OSError as e:
        return f"Error writing file: {e}"
    return _make_diff(content, new_content, file_path)


def Bash(command: str, timeout: int = 120) -> str:
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"[error] Command timed out after {timeout}s: {command}"
    return _format_bash_output(result.returncode, result.stdout, result.stderr)


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


# --- TodoWrite ---

TODO_TOOL = {
    "type": "function",
    "function": {
        "name": "TodoWrite",
        "description": (
            "Create or update a todo list to track multi-step plans. "
            "Pass the COMPLETE list every time — it replaces the previous list. "
            "Use status 'in-progress' for at most one item at a time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The full todo list. Each item has id, title, and status.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer", "description": "Unique numeric id."},
                            "title": {"type": "string", "description": "Short task description."},
                            "status": {
                                "type": "string",
                                "enum": ["not-started", "in-progress", "completed"],
                                "description": "Current status of this item.",
                            },
                        },
                        "required": ["id", "title", "status"],
                    },
                },
            },
            "required": ["todos"],
        },
    },
}

_VALID_STATUSES = {"not-started", "in-progress", "completed"}


def TodoWrite(todos: list[dict]) -> str:
    if not isinstance(todos, list):
        return "Error: todos must be a list."
    for item in todos:
        if not isinstance(item, dict):
            return "Error: each todo must be an object with id, title, status."
        for key in ("id", "title", "status"):
            if key not in item:
                return f"Error: todo item missing required field: {key}"
        if item["status"] not in _VALID_STATUSES:
            return f"Error: invalid status '{item['status']}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}"
    lines = []
    for item in todos:
        icon = {"not-started": "○", "in-progress": "●", "completed": "✓"}[item["status"]]
        lines.append(f"{icon} {item['title']}")
    return "Todo list updated:\n" + "\n".join(lines)