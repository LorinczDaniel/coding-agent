"""First-run onboarding: capture and persist the OpenRouter API key."""

import os
from pathlib import Path

from .agent import set_api_key

KEY_NAME = "OPENROUTER_API_KEY"
SIGNUP_URL = "https://openrouter.ai/settings/keys"

_MIN_KEY_LENGTH = 12


def validate_api_key(key: str) -> str | None:
    """Sanity-check a pasted key. Returns an error message or None if plausible."""
    key = key.strip()
    if not key:
        return "API key cannot be empty."
    if any(c.isspace() for c in key):
        return "API key cannot contain spaces — check that it was pasted in one piece."
    if len(key) < _MIN_KEY_LENGTH:
        return "That looks too short to be an OpenRouter API key."
    return None


def save_api_key(key: str, root: Path | None = None) -> str | None:
    """Persist the key to .env and activate it for this process.

    Replaces an existing OPENROUTER_API_KEY line (never duplicates it) and
    keeps every other line untouched. Written atomically like the session
    store so a crash cannot truncate an existing .env.
    Returns an error message on failure, None on success.
    """
    key = key.strip()
    err = validate_api_key(key)
    if err:
        return err

    path = (root or Path.cwd()) / ".env"
    lines: list[str] = []
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return f"Could not read {path.name}: {exc}"

    key_line = f"{KEY_NAME}={key}"
    replaced = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{KEY_NAME}=") or stripped.startswith(f"export {KEY_NAME}="):
            lines[index] = key_line
            replaced = True
    if not replaced:
        lines.append(key_line)

    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return f"Could not save {path.name}: {exc}"

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    set_api_key(key)
    return None
