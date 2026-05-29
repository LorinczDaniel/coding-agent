import asyncio
import json
import os
from typing import Awaitable, Callable
from dotenv import load_dotenv
from openai import AsyncOpenAI
from .permissions import requires_confirmation
from .tools import (
    Bash, Edit, Glob, Grep, Read, Write, TodoWrite,
    BASH_TOOL, EDIT_TOOL, GLOB_TOOL, GREP_TOOL, READ_TOOL, WRITE_TOOL, TODO_TOOL,
)

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


async def run_agent(
    messages: list,
    model: str,
    on_text: Callable[[str], Awaitable[None]],
    on_tool_start: Callable[[str, str], Awaitable[None]],
    on_tool_result: Callable[[str, str, dict], Awaitable[None]],
    on_usage: Callable[[int, int, float], None] | None = None,
    on_tool_confirm: Callable[[str, dict, str], Awaitable[bool]] | None = None,
    on_todo: Callable[[list[dict]], Awaitable[None]] | None = None,
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
            tools=[READ_TOOL, WRITE_TOOL, EDIT_TOOL, BASH_TOOL, GLOB_TOOL, GREP_TOOL, TODO_TOOL],
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
            if name == "Read":
                return await asyncio.to_thread(Read, args["file_path"])
            if name == "Write":
                return await asyncio.to_thread(Write, args["file_path"], args["content"])
            if name == "Edit":
                return await asyncio.to_thread(
                    Edit, args["file_path"], args["old_string"],
                    args["new_string"], args.get("replace_all", False),
                )
            if name == "Bash":
                return await asyncio.to_thread(
                    Bash, args["command"], args.get("timeout", 120),
                )
            if name == "Glob":
                return await asyncio.to_thread(Glob, args["pattern"], args.get("path", "."))
            if name == "Grep":
                return await asyncio.to_thread(
                    Grep, args["pattern"], args.get("path", "."), args.get("include", "*"),
                )
            if name == "TodoWrite":
                result = TodoWrite(args["todos"])
                if on_todo is not None and not result.startswith("Error"):
                    await on_todo(args["todos"])
                return result
            return f"Unknown tool: {name}"

        results = await asyncio.gather(*(_exec(tc, args, ok) for tc, args, ok in prepared))

        # Phase 3: report results and append messages (order preserved by gather)
        for (tc, args, _), result in zip(prepared, results):
            await on_tool_result(tc["name"], result, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })
