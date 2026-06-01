import hashlib
import json
import re
from pathlib import Path

DEFAULT_SESSION = "default"

_VALID_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


def _sessions_dir(cwd: Path | None = None) -> Path:
    cwd = cwd or Path.cwd()
    cwd_hash = hashlib.sha256(str(cwd).encode()).hexdigest()[:12]
    return Path.home() / ".claude-agent" / "sessions" / cwd_hash


def _session_path(name: str, cwd: Path | None = None) -> Path:
    return _sessions_dir(cwd) / f"{name}.json"


def _validate_name(name: str) -> str | None:
    if not name:
        return "Session name cannot be empty."
    if not _VALID_NAME.match(name):
        return "Session name must contain only letters, digits, hyphens, and underscores."
    return None


def save_session(messages: list, name: str = DEFAULT_SESSION) -> None:
    path = _session_path(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(messages, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_session(name: str = DEFAULT_SESSION) -> list | None:
    path = _session_path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, list) or not data:
        return None
    return data


def clear_session(name: str = DEFAULT_SESSION) -> None:
    _session_path(name).unlink(missing_ok=True)


def list_sessions() -> list[str]:
    d = _sessions_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def _message_content_to_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, indent=2)
    except TypeError:
        return str(content)


def conversation_to_markdown(messages: list) -> str:
    lines = ["# Conversation Export", ""]
    exported = False

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "user":
            heading = "User"
        elif role == "assistant":
            heading = "Agent"
        else:
            continue

        content = _message_content_to_text(message.get("content"))
        if not content.strip():
            continue

        lines.extend([f"## {heading}", "", content.rstrip(), ""])
        exported = True

    if not exported:
        lines.extend(["_No user or agent messages to export._", ""])

    return "\n".join(lines).rstrip() + "\n"


def export_conversation(messages: list, filename: str | Path | None = None) -> Path:
    raw_filename = str(filename or "").strip()
    path = Path(raw_filename) if raw_filename else Path("conversation.md")
    path = path.expanduser()
    if not path.suffix:
        path = path.with_suffix(".md")
    if not path.is_absolute():
        path = Path.cwd() / path

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(conversation_to_markdown(messages), encoding="utf-8")
    return path
