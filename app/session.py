import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

DEFAULT_SESSION = "default"

_VALID_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


@dataclass(frozen=True)
class LessonState:
    """Persisted state of an active Coach lesson."""

    goal: str
    milestones: tuple[str, ...] = ()
    current_index: int = 0
    hint_level: int = 0

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "milestones": list(self.milestones),
            "current_index": self.current_index,
            "hint_level": self.hint_level,
        }

    @classmethod
    def from_dict(cls, data) -> "LessonState | None":
        if not isinstance(data, dict):
            return None
        goal = data.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            return None

        raw_milestones = data.get("milestones", [])
        if not isinstance(raw_milestones, list):
            return None
        milestones = tuple(m for m in raw_milestones if isinstance(m, str))

        current_index = data.get("current_index", 0)
        if not isinstance(current_index, int) or isinstance(current_index, bool) or current_index < 0:
            current_index = 0
        if milestones:
            current_index = min(current_index, len(milestones))

        hint_level = data.get("hint_level", 0)
        if not isinstance(hint_level, int) or isinstance(hint_level, bool) or hint_level < 0:
            hint_level = 0

        return cls(
            goal=goal.strip(),
            milestones=milestones,
            current_index=current_index,
            hint_level=hint_level,
        )

    def escalated(self, max_level: int) -> "LessonState":
        """Return a copy with the hint level bumped by one, clamped at max_level."""
        return replace(self, hint_level=min(self.hint_level + 1, max_level))

    def with_task(self, index: int) -> "LessonState":
        """Return a copy advanced to a task, resetting the hint level."""
        return replace(self, current_index=index, hint_level=0)


def _sessions_dir(cwd: Path | None = None) -> Path:
    cwd = (cwd or Path.cwd()).resolve()
    cwd_hash = hashlib.sha256(str(cwd).encode()).hexdigest()[:12]
    return Path.home() / ".claude-agent" / "sessions" / cwd_hash


def _session_path(name: str, cwd: Path | None = None) -> Path:
    return _sessions_dir(cwd) / f"{name}.json"


def _lesson_path(name: str, cwd: Path | None = None) -> Path:
    return _sessions_dir(cwd) / f"{name}.lesson.json"


def _meta_path(name: str, cwd: Path | None = None) -> Path:
    return _sessions_dir(cwd) / f"{name}.meta.json"


def validate_session_name(name: str) -> str | None:
    if not name:
        return "Session name cannot be empty."
    if not _VALID_NAME.match(name):
        return "Session name must contain only letters, digits, hyphens, and underscores."
    return None


def _write_json_atomic(path: Path, data) -> str | None:
    """Write JSON via a sibling temp file + rename so the file is never truncated.

    Returns an error message on failure, None on success.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return f"Could not save {path.name}: {exc}"
    return None


def _quarantine_corrupt(path: Path) -> None:
    """Move an unparseable file aside so the next save can't destroy evidence."""
    try:
        os.replace(path, path.with_name(path.name + ".corrupt"))
    except OSError:
        pass


def _valid_message(item) -> bool:
    return isinstance(item, dict) and isinstance(item.get("role"), str)


def save_session(messages: list, name: str = DEFAULT_SESSION) -> str | None:
    """Persist a session. Returns an error message on failure, None on success."""
    return _write_json_atomic(_session_path(name), messages)


def load_session(name: str = DEFAULT_SESSION) -> list | None:
    path = _session_path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    except json.JSONDecodeError:
        _quarantine_corrupt(path)
        return None
    if not isinstance(data, list) or not data:
        return None
    if not all(_valid_message(item) for item in data):
        _quarantine_corrupt(path)
        return None
    return data


def session_exists(name: str) -> bool:
    return _session_path(name).exists()


def clear_session(name: str = DEFAULT_SESSION) -> None:
    _session_path(name).unlink(missing_ok=True)
    _lesson_path(name).unlink(missing_ok=True)
    _meta_path(name).unlink(missing_ok=True)


def save_lesson(state: LessonState, name: str = DEFAULT_SESSION) -> str | None:
    return _write_json_atomic(_lesson_path(name), state.to_dict())


def load_lesson(name: str = DEFAULT_SESSION) -> LessonState | None:
    path = _lesson_path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return LessonState.from_dict(data)


def clear_lesson(name: str = DEFAULT_SESSION) -> None:
    _lesson_path(name).unlink(missing_ok=True)


def save_session_profile(profile: str, name: str = DEFAULT_SESSION) -> str | None:
    """Remember which agent profile a session was created under."""
    return _write_json_atomic(_meta_path(name), {"profile": profile})


def load_session_profile(name: str = DEFAULT_SESSION) -> str | None:
    path = _meta_path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    profile = data.get("profile") if isinstance(data, dict) else None
    return profile if isinstance(profile, str) and profile else None


def rename_session(old_name: str, new_name: str) -> str | None:
    err = validate_session_name(old_name)
    if err:
        return err
    err = validate_session_name(new_name)
    if err:
        return err
    if old_name == new_name:
        return "New session name must be different."

    old_path = _session_path(old_name)
    new_path = _session_path(new_name)
    if not old_path.exists():
        return f"Session '{old_name}' not found."
    if new_path.exists():
        return f"Session '{new_name}' already exists."

    try:
        old_path.rename(new_path)
    except OSError as exc:
        return f"Could not rename session: {exc}"

    for sidecar_path in (_lesson_path, _meta_path):
        old_sidecar = sidecar_path(old_name)
        if old_sidecar.exists():
            try:
                old_sidecar.rename(sidecar_path(new_name))
            except OSError:
                pass
    return None


_SIDECAR_SUFFIXES = (".lesson.json", ".meta.json")


def list_sessions() -> list[str]:
    d = _sessions_dir()
    if not d.exists():
        return []
    return sorted(
        p.stem for p in d.glob("*.json")
        if not any(p.name.endswith(suffix) for suffix in _SIDECAR_SUFFIXES)
    )


def message_text(content) -> str:
    """Best-effort plain-text rendering of a message's content field."""
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

        content = message_text(message.get("content"))
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
