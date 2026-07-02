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
# &&, ||, ;, |, single &, and newlines all separate commands under shell=True
_SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||&|\n")
# $( ... ) and backticks hide arbitrary commands from prefix analysis
_SUBSTITUTION = re.compile(r"\$\(|`")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")
# Wrappers that execute their arguments; the real command is what follows
_COMMAND_WRAPPERS = {"env", "command", "nice", "nohup", "time", "xargs"}


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
    return [s.strip() for s in _SEGMENT_SPLIT.split(cmd) if s.strip()]


def _strip_wrappers(segment: str) -> str:
    """Normalize a segment so risky commands can't hide behind trivial prefixes.

    Drops leading NAME=value assignments and wrapper commands (env, xargs, ...),
    and reduces the first token to its basename so `/bin/rm` matches `rm`.
    """
    tokens = segment.split()
    while tokens and _ENV_ASSIGNMENT.match(tokens[0]):
        tokens.pop(0)
    while tokens and tokens[0] in _COMMAND_WRAPPERS:
        tokens.pop(0)
    if tokens:
        tokens[0] = tokens[0].rsplit("/", 1)[-1]
    return " ".join(tokens)


def is_auto_allowed(cmd: str, auto_allow: list[str]) -> bool:
    """True only when every command segment matches an auto-allow prefix.

    A single allowed prefix must not whitelist an entire chained command
    (`git status && rm -rf /`), and substitution can hide anything, so it
    always disqualifies.
    """
    prefixes = [a for a in auto_allow if a]
    if not prefixes:
        return False
    if _SUBSTITUTION.search(cmd):
        return False
    segments = _split_pipeline(cmd)
    if not segments:
        return False
    return all(
        any(_matches_prefix(seg, prefix) for prefix in prefixes)
        for seg in segments
    )


def bash_risky(cmd: str) -> tuple[bool, str]:
    cmd = cmd.strip()
    if _SUBSTITUTION.search(cmd):
        return True, "contains command substitution ($(...) or backticks)"
    if _PIPE_TO_SHELL.search(cmd):
        return True, "pipes output into a shell interpreter"
    for seg in _split_pipeline(cmd):
        seg = _strip_wrappers(seg)
        for prefix in DEFAULT_RISKY_PREFIXES:
            if _matches_prefix(seg, prefix):
                return True, f"contains risky command: `{prefix}`"
    return False, ""


def path_outside_cwd(file_path: str) -> tuple[bool, str]:
    try:
        abs_path = Path(file_path).resolve()
        cwd = Path.cwd().resolve()
        if not abs_path.is_relative_to(cwd):
            return True, f"touches a path outside cwd: {abs_path}"
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
    if name in ("Read", "Write", "Edit"):
        return path_outside_cwd(args.get("file_path", ""))
    return False, ""
