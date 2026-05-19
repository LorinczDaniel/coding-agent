import json
import os
from typing import Callable
from dotenv import load_dotenv
from openai import AsyncOpenAI
from .tools import (
    Bash, Edit, Glob, Grep, Read, Write,
    BASH_TOOL, EDIT_TOOL, GLOB_TOOL, GREP_TOOL, READ_TOOL, WRITE_TOOL,
)

load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")


async def run_agent(
    messages: list,
    on_text: Callable[[str], None],
    on_tool_start: Callable[[str, str], None],
    on_tool_result: Callable[[str, str], None],
    on_usage: Callable[[int, int, float], None] | None = None,
) -> None:
    if not API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

    while True:
        tool_calls_acc: dict[int, dict] = {}
        text_chunks: list[str] = []
        usage_obj = None

        stream = await client.chat.completions.create(
            model="anthropic/claude-haiku-4.5",
            messages=messages,
            tools=[READ_TOOL, WRITE_TOOL, EDIT_TOOL, BASH_TOOL, GLOB_TOOL, GREP_TOOL],
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
                on_text(delta.content)
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

        for tc in tool_calls_acc.values():
            args = json.loads(tc["arguments"])
            on_tool_start(tc["name"], tc["arguments"])

            if tc["name"] == "Read":
                result = Read(args["file_path"])
            elif tc["name"] == "Write":
                result = Write(args["file_path"], args["content"])
            elif tc["name"] == "Edit":
                result = Edit(
                    args["file_path"],
                    args["old_string"],
                    args["new_string"],
                    args.get("replace_all", False),
                )
            elif tc["name"] == "Bash":
                result = Bash(args["command"])
            elif tc["name"] == "Glob":
                result = Glob(args["pattern"], args.get("path", "."))
            elif tc["name"] == "Grep":
                result = Grep(args["pattern"], args.get("path", "."), args.get("include", "*"))
            else:
                result = f"Unknown tool: {tc['name']}"

            on_tool_result(tc["name"], result)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })
