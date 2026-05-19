import re
import subprocess
import sys
from pathlib import Path

_SKIP_DIRS = {".git", ".venv"}


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
        "description": "Write content to a file.",
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


def Read(file_path: str) -> str:
    try:
        with open(file_path) as f:
            return f.read()
    except Exception as e:
        error_msg = f"Error reading file: {e}"
        print(error_msg, file=sys.stderr)
        return error_msg


def Write(file_path: str, content: str) -> str:
    try:
        with open(file_path, "w") as f:
            f.write(content)
        return f"Successfully wrote to {file_path}"
    except Exception as e:
        error_msg = f"Error writing to file: {e}"
        print(error_msg, file=sys.stderr)
        return error_msg


def Bash(command: str) -> str:
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    output = result.stdout
    if result.stderr:
        output += result.stderr
    return output


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