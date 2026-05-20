import difflib
import re
import subprocess
import sys
from pathlib import Path

_SKIP_DIRS = {".git", ".venv"}


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
        "description": "Read and return the content of a file.",
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
        "description": "Execute a shell command.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute."}
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
            return f.read()
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


def Bash(command: str) -> str:
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    output = result.stdout
    if result.stderr:
        output += result.stderr
    return f"[exit {result.returncode}]\n{output}"


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