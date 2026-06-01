import re

_EXIT_RE = re.compile(r"\[exit (-?\d+)\]\n?")
_BASH_STREAM_RE = re.compile(r"^\[(stdout|stderr)\]\n?", re.MULTILINE)


def _format_tokens(n: int) -> str:
    """Format token count as e.g. '12.4k' or '1.2M' for readability."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def format_usage(
    prompt: int, completion: int, cost: float,
    model: str = "", context_window: int = 0,
) -> str:
    base = f"session: ↑ {prompt:,} · ↓ {completion:,} · ${cost:.4f}"
    if context_window > 0:
        base += f" · ctx {_format_tokens(prompt)}/{_format_tokens(context_window)}"
    if model:
        base += f" · {model}"
    return base


def parse_exit_code(result: str) -> tuple[int | None, str]:
    """Split a Bash result of the form '[exit N]\\n<output>' into (code, output)."""
    m = _EXIT_RE.match(result)
    if not m:
        return None, result
    return int(m.group(1)), result[m.end():]


def split_bash_streams(body: str) -> list[tuple[str, str]]:
    """Split Bash output marked with [stdout]/[stderr] sections."""
    matches = list(_BASH_STREAM_RE.finditer(body))
    if not matches:
        return [("stdout", body)] if body else []

    streams: list[tuple[str, str]] = []
    prefix = body[:matches[0].start()]
    if prefix.strip():
        streams.append(("stdout", prefix))

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        text = body[start:end]
        if text:
            streams.append((match.group(1), text))

    return streams


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
