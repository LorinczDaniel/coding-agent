import json
import re
from pathlib import Path

CONFIG_FILE = ".agent_config.json"

DEFAULT_RISKY_PREFIXES = [
    "rm",
    "rmdir",
    "git push",
    "git reset --hard",
    "git checkout --",
    "git clean -f",
    "git clean -fd",
    "git clean -fdx",
    "sudo",
    "shutdown",
    "reboot",
    "halt",
    "mkfs",
    "dd",
    "chmod",
    "chown",
    "kill",
    "killall",
    "pkill",
    "npm publish",
    "pip uninstall",
    "uv remove",
]

_PIPE_TO_SHELL = re.compile(r"\|\s*(sh|bash|zsh|fish)\b")


def load_config() -> dict:
    path = Path(CONFIG_FILE)
    if not path.exists():
        return {"auto_allow": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"auto_allow": []}
    if not isinstance(data, dict):
        return {"auto_allow": []}
    data.setdefault("auto_allow", [])
    return data


def _matches_prefix(cmd: str, prefix: str) -> bool:
    return cmd == prefix or cmd.startswith(prefix + " ")


def _split_pipeline(cmd: str) -> list[str]:
    return [s.strip() for s in re.split(r"&&|\|\||;|\|", cmd) if s.strip()]


def is_auto_allowed(cmd: str, auto_allow: list[str]) -> bool:
    cmd = cmd.strip()
    return any(_matches_prefix(cmd, a) for a in auto_allow if a)


def bash_risky(cmd: str) -> tuple[bool, str]:
    cmd = cmd.strip()
    if _PIPE_TO_SHELL.search(cmd):
        return True, "pipes output into a shell interpreter"
    for seg in _split_pipeline(cmd):
        for prefix in DEFAULT_RISKY_PREFIXES:
            if _matches_prefix(seg, prefix):
                return True, f"contains risky command: `{prefix}`"
    return False, ""


def path_outside_cwd(file_path: str) -> tuple[bool, str]:
    try:
        abs_path = Path(file_path).resolve()
        cwd = Path.cwd().resolve()
        if not abs_path.is_relative_to(cwd):
            return True, f"writes outside cwd: {abs_path}"
    except (OSError, ValueError):
        return True, "could not resolve path"
    return False, ""


def requires_confirmation(name: str, args: dict, config: dict | None = None) -> tuple[bool, str]:
    if config is None:
        config = load_config()
    auto_allow = config.get("auto_allow", [])

    if name == "Bash":
        cmd = args.get("command", "")
        if is_auto_allowed(cmd, auto_allow):
            return False, ""
        return bash_risky(cmd)
    if name in ("Write", "Edit"):
        return path_outside_cwd(args.get("file_path", ""))
    return False, ""
