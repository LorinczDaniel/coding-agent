import asyncio
import json
import os
from typing import Any, Awaitable, Callable

from dotenv import load_dotenv
from openai import AsyncOpenAI

from .permissions import requires_confirmation
from .tools import TOOL_REGISTRY, execute_tool, get_tool_schemas

DENIED_RESULT = (
    "Error: user denied this tool call. "
    "Do not retry the same call. Try a different approach or ask the user."
)

INVALID_ARGS_RESULT = (
    "Error: tool arguments were not a valid JSON object. "
    "Retry the call with well-formed arguments."
)

# Safety valve: a model stuck repeating tool calls stops burning tokens here.
MAX_TOOL_TURNS = 50

SUBAGENT_SYSTEM_PROMPT = (
    "You are a subagent handling one self-contained task for a parent coding "
    "agent. Work autonomously with your tools and do not ask questions. "
    "Only your FINAL message is returned to the parent, so end with a "
    "complete, standalone report of what you did and found."
)

load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

MODELS = {
    "haiku": "anthropic/claude-haiku-4.5",
    "sonnet": "anthropic/claude-sonnet-4-6",
}
DEFAULT_MODEL = "haiku"

CONTEXT_WINDOWS = {
    "anthropic/claude-haiku-4.5": 200_000,
    "anthropic/claude-sonnet-4-6": 200_000,
}


def parse_tool_args(raw: str) -> dict[str, Any] | None:
    """Parse streamed tool-call arguments, returning None unless a JSON object."""
    try:
        args = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        return None
    return args if isinstance(args, dict) else None


async def run_agent(
    messages: list,
    model: str,
    on_text: Callable[[str], Awaitable[None]],
    on_tool_start: Callable[[str, str], Awaitable[None]],
    on_tool_result: Callable[[str, str, dict], Awaitable[None]],
    on_usage: Callable[[int, int, float], None] | None = None,
    on_tool_confirm: Callable[[str, dict, str], Awaitable[bool]] | None = None,
    on_todo: Callable[[list[dict]], Awaitable[None]] | None = None,
    tool_allowlist: list[str] | tuple[str, ...] | None = None,
) -> None:
    if not API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

    async def task_runner(args: dict) -> str:
        return await _run_task_subagent(
            client, args, model, tool_allowlist, on_usage, on_tool_confirm,
        )

    try:
        for _turn in range(MAX_TOOL_TURNS):
            had_tool_calls = await _run_turn(
                client,
                messages,
                model,
                on_text,
                on_tool_start,
                on_tool_result,
                on_usage,
                on_tool_confirm,
                on_todo,
                tool_allowlist,
                task_runner=task_runner,
            )
            if not had_tool_calls:
                return
        await on_text(
            f"\n[Stopped after {MAX_TOOL_TURNS} consecutive tool turns. "
            "Send a message to continue.]"
        )
    finally:
        await client.close()


async def _noop_text(_delta: str) -> None:
    return None


async def _noop_tool_start(_name: str, _args_json: str) -> None:
    return None


async def _noop_tool_result(_name: str, _result: str, _args: dict) -> None:
    return None


async def _run_task_subagent(
    client: AsyncOpenAI,
    args: dict,
    model: str,
    parent_allowlist: list[str] | tuple[str, ...] | None,
    on_usage: Callable[[int, int, float], None] | None,
    on_tool_confirm: Callable[[str, dict, str], Awaitable[bool]] | None,
) -> str:
    """Run a nested agent conversation and return its final assistant text.

    The subagent inherits the parent's tools minus Task (no recursion), and
    shares the parent's usage tracking and permission prompts.
    """
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return "Error: Task requires a non-empty 'prompt'."

    parent_tools = list(TOOL_REGISTRY) if parent_allowlist is None else list(parent_allowlist)
    allowlist = [name for name in parent_tools if name != "Task"]
    messages: list = [
        {"role": "system", "content": SUBAGENT_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    for _turn in range(MAX_TOOL_TURNS):
        had_tool_calls = await _run_turn(
            client,
            messages,
            model,
            _noop_text,
            _noop_tool_start,
            _noop_tool_result,
            on_usage,
            on_tool_confirm,
            None,
            allowlist,
        )
        if not had_tool_calls:
            break

    final = next(
        (
            m.get("content")
            for m in reversed(messages)
            if isinstance(m, dict) and m.get("role") == "assistant" and m.get("content")
        ),
        None,
    )
    return final or "Error: subagent finished without a final report."


async def _run_turn(
    client: AsyncOpenAI,
    messages: list,
    model: str,
    on_text: Callable[[str], Awaitable[None]],
    on_tool_start: Callable[[str, str], Awaitable[None]],
    on_tool_result: Callable[[str, str, dict], Awaitable[None]],
    on_usage: Callable[[int, int, float], None] | None,
    on_tool_confirm: Callable[[str, dict, str], Awaitable[bool]] | None,
    on_todo: Callable[[list[dict]], Awaitable[None]] | None,
    tool_allowlist: list[str] | tuple[str, ...] | None,
    task_runner: Callable[[dict], Awaitable[str]] | None = None,
) -> bool:
    """Run one model request plus its tool calls. Returns True if tools ran."""
    tool_calls_acc: dict[int, dict] = {}
    text_chunks: list[str] = []
    usage_obj = None

    stream = await client.chat.completions.create(  # type: ignore[call-overload]
        model=model,
        messages=messages,
        tools=get_tool_schemas(tool_allowlist),
        stream=True,
        stream_options={"include_usage": True},
        extra_body={"usage": {"include": True}},
    )

    async for chunk in stream:
        if getattr(chunk, "usage", None):
            usage_obj = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        if delta.content:
            await on_text(delta.content)
            text_chunks.append(delta.content)

        if delta.tool_calls:
            for tc in delta.tool_calls:
                acc = tool_calls_acc.setdefault(
                    tc.index, {"id": "", "name": "", "arguments": ""}
                )
                # id and name may arrive in any chunk, not just the first
                if tc.id:
                    acc["id"] = tc.id
                if tc.function and tc.function.name:
                    acc["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    acc["arguments"] += tc.function.arguments

    if on_usage is not None and usage_obj is not None:
        prompt = getattr(usage_obj, "prompt_tokens", 0) or 0
        completion = getattr(usage_obj, "completion_tokens", 0) or 0
        cost = getattr(usage_obj, "cost", 0.0) or 0.0
        on_usage(prompt, completion, float(cost))

    assistant_msg: dict = {"role": "assistant", "content": "".join(text_chunks) or None}
    if tool_calls_acc:
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            }
            for tc in tool_calls_acc.values()
        ]
    messages.append(assistant_msg)

    if not tool_calls_acc:
        return False

    # Phase 1: notify UI and handle confirmations sequentially
    prepared: list[tuple[dict, dict | None, bool]] = []
    for tc in tool_calls_acc.values():
        args = parse_tool_args(tc["arguments"])
        await on_tool_start(tc["name"], tc["arguments"])

        if args is None:
            prepared.append((tc, None, False))
            continue

        needs_confirm, reason = requires_confirmation(tc["name"], args)
        if needs_confirm and on_tool_confirm is not None:
            approved = await on_tool_confirm(tc["name"], args, reason)
        else:
            approved = True
        prepared.append((tc, args, approved))

    # Phase 2: execute approved tools in parallel. Every tool call must produce
    # a result string — an escaped exception here would leave the assistant's
    # tool_calls without matching tool messages and poison the conversation.
    async def _exec(tc: dict, args: dict | None, approved: bool) -> str:
        if args is None:
            return INVALID_ARGS_RESULT
        if not approved:
            return DENIED_RESULT
        name = tc["name"]
        try:
            if name == "Task" and task_runner is not None:
                result = await task_runner(args)
            else:
                result = await asyncio.to_thread(execute_tool, name, args)
        except Exception as e:
            return f"Error executing {name}: {e}"
        if name == "TodoWrite":
            if on_todo is not None and not result.startswith("Error"):
                await on_todo(args["todos"])
        return result

    results = await asyncio.gather(*(_exec(tc, args, ok) for tc, args, ok in prepared))

    # Phase 3: report results and append messages (order preserved by gather)
    for (tc, args, _), result in zip(prepared, results):
        await on_tool_result(tc["name"], result, args or {})
        messages.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": result,
        })
    return True
