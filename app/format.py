def format_usage(prompt: int, completion: int, cost: float) -> str:
    return f"session: ↑ {prompt:,} · ↓ {completion:,} · ${cost:.4f}"
