# Model Switching (`/model`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users switch between OpenRouter models mid-session with `/model <alias>`.

**Architecture:** Add a `MODELS` dict and `DEFAULT_MODEL` constant to `agent.py`. The TUI stores the current alias on `self._model`, resolves it to a full model ID, and passes it to `run_agent`. The usage bar shows the active model.

**Tech Stack:** Python, Textual, OpenAI SDK (OpenRouter)

---

### Task 1: Add model registry and `model` param to `run_agent`

**Files:**
- Modify: `app/agent.py:18-47`
- Test: `tests/test_format.py` (no changes needed here, but we verify agent.py imports)

- [ ] **Step 1: Add `MODELS` and `DEFAULT_MODEL` to `agent.py`**

In `app/agent.py`, after the `BASE_URL` line (line 19), add:

```python
MODELS = {
    "haiku": "anthropic/claude-haiku-4.5",
    "sonnet": "anthropic/claude-sonnet-4-6",
}
DEFAULT_MODEL = "haiku"
```

- [ ] **Step 2: Add `model` parameter to `run_agent` and use it**

Change the `run_agent` signature to accept `model: str` as the first positional arg after `messages`:

```python
async def run_agent(
    messages: list,
    model: str,
    on_text: Callable[[str], Awaitable[None]],
    on_tool_start: Callable[[str, str], Awaitable[None]],
    on_tool_result: Callable[[str, str, dict], Awaitable[None]],
    on_usage: Callable[[int, int, float], None] | None = None,
    on_tool_confirm: Callable[[str, dict, str], Awaitable[bool]] | None = None,
) -> None:
```

Then replace the hardcoded model in the `client.chat.completions.create()` call (line 41):

```python
        stream = await client.chat.completions.create(
            model=model,
            ...
        )
```

- [ ] **Step 3: Commit**

```bash
git add app/agent.py
git commit -m "feat: add model registry and model param to run_agent"
```

---

### Task 2: Update `format_usage` to show the active model

**Files:**
- Modify: `app/format.py:6-7`
- Modify: `tests/test_format.py`

- [ ] **Step 1: Write failing tests for the new `model` parameter**

Add these tests to `tests/test_format.py`:

```python
def test_format_usage_with_model():
    assert format_usage(100, 50, 0.01, "haiku") == "session: ↑ 100 · ↓ 50 · $0.0100 · haiku"


def test_format_usage_with_model_sonnet():
    assert format_usage(100, 50, 0.05, "sonnet") == "session: ↑ 100 · ↓ 50 · $0.0500 · sonnet"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_format.py::test_format_usage_with_model tests/test_format.py::test_format_usage_with_model_sonnet -v`

Expected: FAIL — `format_usage() takes 3 positional arguments but 4 were given`

- [ ] **Step 3: Update `format_usage` to accept and display the model**

In `app/format.py`, change line 6-7:

```python
def format_usage(prompt: int, completion: int, cost: float, model: str = "") -> str:
    base = f"session: ↑ {prompt:,} · ↓ {completion:,} · ${cost:.4f}"
    return f"{base} · {model}" if model else base
```

- [ ] **Step 4: Run all format tests to verify they pass**

Run: `uv run pytest tests/test_format.py -v`

Expected: All tests PASS (existing tests still work because `model` defaults to `""`)

- [ ] **Step 5: Commit**

```bash
git add app/format.py tests/test_format.py
git commit -m "feat: show active model in usage bar"
```

---

### Task 3: Handle `/model` command and pass model to `run_agent`

**Files:**
- Modify: `app/tui.py:102-108,155-168,238-244,272-280`

- [ ] **Step 1: Import `MODELS` and `DEFAULT_MODEL` in `tui.py`**

Change the import on line 11:

```python
from .agent import run_agent, MODELS, DEFAULT_MODEL
```

- [ ] **Step 2: Initialize `self._model` in `on_mount`**

In `on_mount`, after `self._current_tool_block = None` (line 108), add:

```python
        self._model = DEFAULT_MODEL
```

- [ ] **Step 3: Update the initial usage bar to show the default model**

In `compose`, change the usage bar Static (line 95):

```python
            yield Static(format_usage(0, 0, 0.0, DEFAULT_MODEL), id="usage-bar")
```

This also requires updating the import on line 13:

```python
from .agent import run_agent, MODELS, DEFAULT_MODEL
```

(Already done in Step 1.)

- [ ] **Step 4: Add `/model` command handling in `_send`**

In `_send`, after the `/clear` block (after line 161), add:

```python
        if text == "/model" or text.startswith("/model "):
            arg = text[7:].strip()
            if not arg:
                options = ", ".join(MODELS)
                self._append_sync(Static(Text.assemble(
                    ("Current model: ", "dim"),
                    (self._model, "bold"),
                    (" — available: ", "dim"),
                    (options, "bold"),
                )))
            elif arg in MODELS:
                self._model = arg
                self._append_sync(Static(Text.assemble(
                    ("Switched to ", "dim"),
                    (arg, "bold"),
                )))
                self.query_one("#usage-bar", Static).update(
                    format_usage(self._total_in, self._total_out, self._total_cost, self._model)
                )
            else:
                options = ", ".join(MODELS)
                self._append_sync(Static(Text.assemble(
                    (f"Unknown model: {arg}", "bold red"),
                    (" — available: ", "dim"),
                    (options, "bold"),
                )))
            return
```

- [ ] **Step 5: Pass model to `run_agent`**

In `_run_agent`, update the `run_agent` call (around line 273):

```python
            await run_agent(
                self._messages,
                MODELS[self._model],
                on_text,
                on_tool_start,
                on_tool_result,
                on_usage,
                on_tool_confirm,
            )
```

- [ ] **Step 6: Pass model to `format_usage` in `on_usage`**

In the `on_usage` callback (around line 242):

```python
        def on_usage(prompt: int, completion: int, cost: float) -> None:
            self._total_in += prompt
            self._total_out += completion
            self._total_cost += cost
            self.query_one("#usage-bar", Static).update(
                format_usage(self._total_in, self._total_out, self._total_cost, self._model)
            )
```

- [ ] **Step 7: Run all tests to verify nothing broke**

Run: `uv run pytest -v`

Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add app/tui.py
git commit -m "feat: /model command for mid-session model switching"
```

---

### Task 4: Manual smoke test

- [ ] **Step 1: Start the app**

Run: `uv run -m app.main`

- [ ] **Step 2: Verify default model shows in usage bar**

Expected: Bottom bar shows `session: ↑ 0 · ↓ 0 · $0.0000 · haiku`

- [ ] **Step 3: Test `/model` with no args**

Type: `/model`

Expected: Shows `Current model: haiku — available: haiku, sonnet`

- [ ] **Step 4: Test `/model sonnet`**

Type: `/model sonnet`

Expected: Shows `Switched to sonnet`, usage bar updates to show `· sonnet`

- [ ] **Step 5: Test `/model bogus`**

Type: `/model bogus`

Expected: Shows `Unknown model: bogus — available: haiku, sonnet`

- [ ] **Step 6: Send a message to verify model is used**

Type any prompt and confirm the agent responds (verifies the model string is passed correctly to OpenRouter).

- [ ] **Step 7: Switch back and verify**

Type: `/model haiku`

Expected: Shows `Switched to haiku`, usage bar updates.
