import asyncio
import json
import os
from typing import Awaitable, Callable
from dotenv import load_dotenv
from openai import AsyncOpenAI
from .permissions import requires_confirmation
from .tools import execute_tool, get_tool_schemas

DENIED_RESULT = (
    "Error: user denied this tool call. "
    "Do not retry the same call. Try a different approach or ask the user."
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

    while True:
        tool_calls_acc: dict[int, dict] = {}
        text_chunks: list[str] = []
        usage_obj = None

        stream = await client.chat.completions.create(
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
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc.id or "",
                            "name": (tc.function.name or "") if tc.function else "",
                            "arguments": "",
                        }
                    if tc.function and tc.function.arguments:
                        tool_calls_acc[idx]["arguments"] += tc.function.arguments

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
            break

        # Phase 1: notify UI and handle confirmations sequentially
        prepared: list[tuple[dict, dict, bool]] = []
        for tc in tool_calls_acc.values():
            args = json.loads(tc["arguments"])
            await on_tool_start(tc["name"], tc["arguments"])

            needs_confirm, reason = requires_confirmation(tc["name"], args)
            if needs_confirm and on_tool_confirm is not None:
                approved = await on_tool_confirm(tc["name"], args, reason)
            else:
                approved = True
            prepared.append((tc, args, approved))

        # Phase 2: execute approved tools in parallel
        async def _exec(tc: dict, args: dict, approved: bool) -> str:
            if not approved:
                return DENIED_RESULT
            name = tc["name"]
            result = await asyncio.to_thread(execute_tool, name, args)
            if name == "TodoWrite":
                if on_todo is not None and not result.startswith("Error"):
                    await on_todo(args["todos"])
            return result

        results = await asyncio.gather(*(_exec(tc, args, ok) for tc, args, ok in prepared))

        # Phase 3: report results and append messages (order preserved by gather)
        for (tc, args, _), result in zip(prepared, results):
            await on_tool_result(tc["name"], result, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })
