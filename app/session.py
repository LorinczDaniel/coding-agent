import json
from pathlib import Path

SESSION_FILE = Path(".agent_session.json")


def save_session(messages: list) -> None:
    try:
        SESSION_FILE.write_text(json.dumps(messages, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_session() -> list | None:
    if not SESSION_FILE.exists():
        return None
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, list) or not data:
        return None
    return data


def clear_session() -> None:
    SESSION_FILE.unlink(missing_ok=True)
