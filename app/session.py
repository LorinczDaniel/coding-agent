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
