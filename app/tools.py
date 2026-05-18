import subprocess
import sys


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