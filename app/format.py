import re

_EXIT_RE = re.compile(r"\[exit (-?\d+)\]\n?")


def format_usage(prompt: int, completion: int, cost: float) -> str:
    return f"session: ↑ {prompt:,} · ↓ {completion:,} · ${cost:.4f}"


def parse_exit_code(result: str) -> tuple[int | None, str]:
    """Split a Bash result of the form '[exit N]\\n<output>' into (code, output)."""
    m = _EXIT_RE.match(result)
    if not m:
        return None, result
    return int(m.group(1)), result[m.end():]


def diff_line_style(line: str) -> str:
    if line.startswith(("+++", "---")):
        return "bold dim"
    if line.startswith("@@"):
        return "cyan"
    if line.startswith("+"):
        return "green"
    if line.startswith("-"):
        return "red"
    return "dim white"


def is_diff(result: str) -> bool:
    return result.startswith("--- a/")
