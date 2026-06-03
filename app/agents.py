import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .tools import TOOL_REGISTRY


@dataclass(frozen=True)
class AgentProfile:
    name: str
    title: str
    description: str
    allowed_tools: tuple[str, ...]
    system_addendum: str


PROFILE_STORE_VERSION = 1
CUSTOM_PROFILES_FILE = Path(".claude-agent") / "profiles.json"
MAX_PROFILE_NAME_LENGTH = 64
_VALID_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")


COACH_PROFILE = "coach"
DEFAULT_PROFILE = COACH_PROFILE

COACH_ALLOWED_TOOLS = (
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
    "TodoWrite",
)

COACH_SYSTEM_ADDENDUM = """\
You are the Learning Coach, a CodeCrafters-style education agent.

Your job is to help the learner build their own project step by step. The
learner may say they want to build their own Redis, grep, shell, HTTP server,
interpreter, database, or another system. Treat that goal as a curriculum seed.

Teaching rules:
- Ask for a build goal if the learner has not provided one.
- Turn the goal into 5-10 small milestones with observable outcomes.
- Give exactly one next task at a time.
- Inspect the learner's code, tests, and command output before judging progress.
- When the learner struggles, give hints in increasing strength: question,
  nudge, focused example, then near-solution.
- Avoid complete solutions unless the learner explicitly asks after struggling.
- Explain the concept behind each step briefly, then let the learner work.
- Keep feedback specific, kind, and oriented toward the next action.

Direct help policy:
- You may create, edit, and rewrite files when it helps the learner move forward.
- Prefer small, focused edits that match the current lesson step.
- Explain what you changed and why in teaching language after making an edit.
- Do not skip the learning path by dumping a complete project unless asked.
- Use shell commands carefully to run checks, inspect behavior, and validate work.
"""

PROFILES: dict[str, AgentProfile] = {
    COACH_PROFILE: AgentProfile(
        name=COACH_PROFILE,
        title="Learning Coach",
        description=(
            "CodeCrafters-style coach that turns a build goal into small tasks "
            "and helps with graduated hints while keeping the learner in control."
        ),
        allowed_tools=COACH_ALLOWED_TOOLS,
        system_addendum=COACH_SYSTEM_ADDENDUM,
    ),
}


def available_tool_names() -> tuple[str, ...]:
    return tuple(TOOL_REGISTRY.keys())


def _custom_profiles_path(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()) / CUSTOM_PROFILES_FILE


def validate_profile_name(name: str, *, allow_builtin: bool = False) -> str | None:
    if not name:
        return "Agent profile name cannot be empty."
    if len(name) > MAX_PROFILE_NAME_LENGTH:
        return f"Agent profile name must be {MAX_PROFILE_NAME_LENGTH} characters or fewer."
    if not _VALID_PROFILE_NAME.match(name):
        return (
            "Agent profile name must start with a lowercase letter and contain only "
            "lowercase letters, digits, hyphens, and underscores."
        )
    if not allow_builtin and name in PROFILES:
        return f"Agent profile '{name}' is built in and cannot be replaced."
    return None


def validate_allowed_tools(tools: Any) -> tuple[tuple[str, ...] | None, str | None]:
    if not isinstance(tools, (list, tuple)):
        return None, "Allowed tools must be a list."

    normalized: list[str] = []
    seen: set[str] = set()
    valid = set(TOOL_REGISTRY)
    for tool_name in tools:
        if not isinstance(tool_name, str) or not tool_name.strip():
            return None, "Allowed tools must be non-empty strings."
        tool_name = tool_name.strip()
        if tool_name not in valid:
            available = ", ".join(available_tool_names())
            return None, f"Unknown tool: {tool_name}. Available tools: {available}."
        if tool_name not in seen:
            normalized.append(tool_name)
            seen.add(tool_name)

    if not normalized:
        return None, "At least one allowed tool is required."
    return tuple(normalized), None


def validate_profile(profile: AgentProfile, *, allow_builtin: bool = False) -> str | None:
    err = validate_profile_name(profile.name, allow_builtin=allow_builtin)
    if err:
        return err
    if not profile.title.strip():
        return "Agent profile title cannot be empty."
    if not profile.description.strip():
        return "Agent profile description cannot be empty."
    if not profile.system_addendum.strip():
        return "Agent profile instructions cannot be empty."
    _, err = validate_allowed_tools(profile.allowed_tools)
    return err


def _profile_to_dict(profile: AgentProfile) -> dict[str, Any]:
    data = asdict(profile)
    data["allowed_tools"] = list(profile.allowed_tools)
    return data


def _profile_from_dict(data: Any) -> AgentProfile | None:
    if not isinstance(data, dict):
        return None

    name = data.get("name")
    title = data.get("title")
    description = data.get("description")
    allowed_tools = data.get("allowed_tools")
    system_addendum = data.get("system_addendum")
    if not all(isinstance(value, str) for value in (name, title, description, system_addendum)):
        return None

    normalized_tools, err = validate_allowed_tools(allowed_tools)
    if err:
        return None

    profile = AgentProfile(
        name=name.strip(),
        title=title.strip(),
        description=description.strip(),
        allowed_tools=normalized_tools,
        system_addendum=system_addendum.strip(),
    )
    if validate_profile(profile, allow_builtin=True):
        return None
    return profile


def load_custom_profiles(cwd: Path | None = None) -> dict[str, AgentProfile]:
    path = _custom_profiles_path(cwd)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(data, dict):
        return {}
    raw_profiles = data.get("profiles")
    if not isinstance(raw_profiles, list):
        return {}

    profiles: dict[str, AgentProfile] = {}
    for raw_profile in raw_profiles:
        profile = _profile_from_dict(raw_profile)
        if profile is None or profile.name in PROFILES:
            continue
        profiles[profile.name] = profile
    return profiles


def save_custom_profile(profile: AgentProfile, cwd: Path | None = None) -> str | None:
    err = validate_profile(profile)
    if err:
        return err

    profiles = load_custom_profiles(cwd)
    profiles[profile.name] = profile
    data = {
        "version": PROFILE_STORE_VERSION,
        "profiles": [_profile_to_dict(profiles[name]) for name in sorted(profiles)],
    }
    path = _custom_profiles_path(cwd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        return f"Could not save agent profile: {exc}"
    return None


def _all_profiles() -> dict[str, AgentProfile]:
    return {**load_custom_profiles(), **PROFILES}


def get_profile(name: str = DEFAULT_PROFILE) -> AgentProfile:
    profiles = _all_profiles()
    try:
        return profiles[name]
    except KeyError as exc:
        available = ", ".join(sorted(profiles))
        raise ValueError(f"Unknown agent profile: {name}. Available: {available}") from exc


def list_profiles() -> tuple[AgentProfile, ...]:
    profiles = _all_profiles()
    return tuple(profiles[name] for name in sorted(profiles))
