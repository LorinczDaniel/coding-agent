# Model Switching (`/model`)

Switch models mid-session for cost/capability trade-offs.

## Model Registry

Dict in `agent.py` mapping aliases to OpenRouter model IDs:

```python
MODELS = {
    "haiku": "anthropic/claude-haiku-4.5",
    "sonnet": "anthropic/claude-sonnet-4-6",
}
DEFAULT_MODEL = "haiku"
```

## State

`AgentApp._model: str` — stores the alias key (e.g. `"haiku"`). Initialized to `DEFAULT_MODEL`.

## `/model` Command

Handled in `tui.py._send()` alongside `/clear`:

- `/model` (no args) — prints current model and available options.
- `/model <alias>` — switches `self._model`, prints confirmation.
- `/model <unknown>` — prints error with valid options.

## `run_agent` Changes

Add a `model: str` parameter (full OpenRouter model ID). The TUI resolves the alias via `MODELS[self._model]` before calling.

```python
async def run_agent(messages, on_text, on_tool_start, on_tool_result,
                    on_usage, on_tool_confirm, model: str) -> None:
```

The hardcoded `"anthropic/claude-haiku-4.5"` in the `create()` call is replaced with the `model` parameter.

## Usage Bar

Append the current model alias to the existing usage line:

```
session: ↑ 1,234 · ↓ 567 · $0.0012 · haiku
```

`format_usage` gains a `model: str` parameter for this.

## Files Changed

| File | Change |
|------|--------|
| `app/agent.py` | Add `MODELS` dict, `DEFAULT_MODEL`, add `model` param to `run_agent`, remove hardcoded model |
| `app/tui.py` | Add `self._model`, handle `/model` command, pass model to `run_agent`, pass model to usage bar |
| `app/format.py` | Add `model` param to `format_usage` |
