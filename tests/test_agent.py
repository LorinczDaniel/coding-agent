import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent import DENIED_RESULT, INVALID_ARGS_RESULT, parse_tool_args, run_agent
from app.agents import COACH_ALLOWED_TOOLS


def _make_chunk(delta_content=None, delta_tool_calls=None, usage=None, has_choices=True):
    """Build a fake streaming chunk."""
    chunk = MagicMock()
    chunk.usage = usage
    if not has_choices:
        chunk.choices = []
        return chunk
    delta = MagicMock()
    delta.content = delta_content
    delta.tool_calls = delta_tool_calls
    choice = MagicMock()
    choice.delta = delta
    chunk.choices = [choice]
    return chunk


def _tool_call_delta(index, tc_id=None, name=None, arguments=""):
    """Build a fake tool-call delta fragment."""
    tc = MagicMock()
    tc.index = index
    tc.id = tc_id
    func = MagicMock()
    func.name = name
    func.arguments = arguments
    tc.function = func
    return tc


def _make_stream(chunks):
    """Wrap a list of chunks into an async iterator."""
    async def _iter():
        for c in chunks:
            yield c
    return _iter()


def _read_stream(file_paths):
    """Build stream chunks that emit multiple Read tool calls, then a final text-only turn."""
    tool_deltas = []
    for i, fp in enumerate(file_paths):
        tool_deltas.append(
            _make_chunk(delta_tool_calls=[
                _tool_call_delta(i, tc_id=f"call_{i}", name="Read",
                                 arguments=json.dumps({"file_path": fp})),
            ])
        )
    # Final empty chunk (no choices) for usage
    tool_deltas.append(_make_chunk(has_choices=False))

    # Second turn: model replies with text, no tools
    text_chunks = [
        _make_chunk(delta_content="Done"),
        _make_chunk(has_choices=False),
    ]
    return [tool_deltas, text_chunks]


@pytest.fixture
def callbacks():
    return {
        "on_text": AsyncMock(),
        "on_tool_start": AsyncMock(),
        "on_tool_result": AsyncMock(),
        "on_usage": None,
        "on_tool_confirm": None,
        "on_todo": AsyncMock(),
    }


@pytest.mark.asyncio
async def test_parallel_reads_preserve_order(tmp_path, callbacks):
    """Multiple Read calls run in parallel and results line up with tool_call_id."""
    files = []
    for i in range(3):
        f = tmp_path / f"file_{i}.txt"
        f.write_text(f"content_{i}")
        files.append(str(f))

    turns = _read_stream(files)
    turn_iter = iter(turns)

    async def fake_create(**kwargs):
        return _make_stream(next(turn_iter))

    messages = [{"role": "user", "content": "read these files"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    # Verify tool results were reported in order
    assert callbacks["on_tool_result"].call_count == 3
    for i in range(3):
        call_args = callbacks["on_tool_result"].call_args_list[i]
        assert call_args[0][0] == "Read"
        assert call_args[0][1] == f"content_{i}"

    # Verify tool messages in conversation have correct tool_call_ids
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 3
    for i, msg in enumerate(tool_msgs):
        assert msg["tool_call_id"] == f"call_{i}"
        assert msg["content"] == f"content_{i}"


@pytest.mark.asyncio
async def test_parallel_execution_is_concurrent(tmp_path, callbacks):
    """Verify tools actually run concurrently (not sequentially)."""
    files = []
    for i in range(3):
        f = tmp_path / f"file_{i}.txt"
        f.write_text(f"data_{i}")
        files.append(str(f))

    turns = _read_stream(files)
    turn_iter = iter(turns)

    async def fake_create(**kwargs):
        return _make_stream(next(turn_iter))

    original_read = __import__("app.tools", fromlist=["Read"]).Read

    def slow_read(file_path):
        time.sleep(0.15)
        return original_read(file_path)

    messages = [{"role": "user", "content": "read"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls, \
            patch("app.tools.Read", side_effect=slow_read):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        start = time.monotonic()
        await run_agent(messages, "test-model", **callbacks)
        elapsed = time.monotonic() - start

    # 3 x 0.15s sequential = 0.45s; parallel should be ~0.15s
    assert elapsed < 0.35, f"Expected parallel execution, took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_tool_allowlist_filters_openrouter_schemas(callbacks):
    """Only allowlisted tool schemas are sent to OpenRouter."""
    chunks = [
        _make_chunk(delta_content="Done"),
        _make_chunk(has_choices=False),
    ]
    tool_names = []

    async def fake_create(**kwargs):
        tool_names.append([tool["function"]["name"] for tool in kwargs["tools"]])
        return _make_stream(chunks)

    messages = [{"role": "user", "content": "hi"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(
            messages,
            "test-model",
            **callbacks,
            tool_allowlist=["Read", "Bash"],
        )

    assert tool_names == [["Read", "Bash"]]


@pytest.mark.asyncio
async def test_default_tool_schemas_include_all_existing_tools(callbacks):
    """Without an allowlist, all registered tool schemas are sent."""
    from app.tools import TOOL_REGISTRY

    chunks = [
        _make_chunk(delta_content="Done"),
        _make_chunk(has_choices=False),
    ]
    tool_names = []

    async def fake_create(**kwargs):
        tool_names.append([tool["function"]["name"] for tool in kwargs["tools"]])
        return _make_stream(chunks)

    messages = [{"role": "user", "content": "hi"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    assert len(tool_names) == 1
    assert set(tool_names[0]) == set(TOOL_REGISTRY)


@pytest.mark.asyncio
async def test_coach_tool_allowlist_is_sent_to_openrouter(callbacks):
    chunks = [
        _make_chunk(delta_content="Done"),
        _make_chunk(has_choices=False),
    ]
    tool_names = []

    async def fake_create(**kwargs):
        tool_names.append([tool["function"]["name"] for tool in kwargs["tools"]])
        return _make_stream(chunks)

    messages = [{"role": "user", "content": "hi"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(
            messages,
            "test-model",
            **callbacks,
            tool_allowlist=COACH_ALLOWED_TOOLS,
        )

    assert tool_names == [list(COACH_ALLOWED_TOOLS)]


@pytest.mark.asyncio
async def test_denied_tool_returns_denied_result(tmp_path, callbacks):
    """When user denies a tool, DENIED_RESULT is used without executing the tool."""
    f = tmp_path / "secret.txt"
    f.write_text("secret")

    turns = _read_stream([str(f)])
    turn_iter = iter(turns)

    async def fake_create(**kwargs):
        return _make_stream(next(turn_iter))

    async def deny_all(name, args, reason):
        return False

    callbacks["on_tool_confirm"] = deny_all

    messages = [{"role": "user", "content": "read"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls, \
         patch("app.agent.requires_confirmation", return_value=(True, "risky")):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"] == DENIED_RESULT


@pytest.mark.asyncio
async def test_mixed_approved_and_denied(tmp_path, callbacks):
    """Mix of approved and denied tools: ordering preserved, denied get DENIED_RESULT."""
    files = []
    for i in range(3):
        f = tmp_path / f"f{i}.txt"
        f.write_text(f"c{i}")
        files.append(str(f))

    turns = _read_stream(files)
    turn_iter = iter(turns)

    async def fake_create(**kwargs):
        return _make_stream(next(turn_iter))

    call_count = 0

    async def deny_second(name, args, reason):
        nonlocal call_count
        call_count += 1
        return call_count != 2  # deny the second tool call

    callbacks["on_tool_confirm"] = deny_second

    messages = [{"role": "user", "content": "read"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls, \
         patch("app.agent.requires_confirmation", return_value=(True, "test")):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 3
    assert tool_msgs[0]["content"] == "c0"
    assert tool_msgs[1]["content"] == DENIED_RESULT
    assert tool_msgs[2]["content"] == "c2"
    # tool_call_ids still in order
    assert [m["tool_call_id"] for m in tool_msgs] == ["call_0", "call_1", "call_2"]


@pytest.mark.asyncio
async def test_todo_write_calls_on_todo(callbacks):
    """TodoWrite tool triggers the on_todo callback with the todo list."""
    todos = [
        {"id": 1, "title": "Step one", "status": "in-progress"},
        {"id": 2, "title": "Step two", "status": "not-started"},
    ]

    # Turn 1: model calls TodoWrite
    tool_chunks = [
        _make_chunk(delta_tool_calls=[
            _tool_call_delta(0, tc_id="call_todo", name="TodoWrite",
                             arguments=json.dumps({"todos": todos})),
        ]),
        _make_chunk(has_choices=False),
    ]
    # Turn 2: model replies with text
    text_chunks = [
        _make_chunk(delta_content="Plan created"),
        _make_chunk(has_choices=False),
    ]
    turns = iter([tool_chunks, text_chunks])

    async def fake_create(**kwargs):
        return _make_stream(next(turns))

    messages = [{"role": "user", "content": "plan a task"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    # on_todo should have been called with the todos list
    callbacks["on_todo"].assert_awaited_once_with(todos)

    # Tool result message should confirm the update
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert "Todo list updated" in tool_msgs[0]["content"]
    assert "● Step one" in tool_msgs[0]["content"]
    assert "○ Step two" in tool_msgs[0]["content"]


# ---------------------------------------------------------------------------
# run_agent coverage: text, tool, multi-turn, denied, usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_text_response(callbacks):
    """Agent returns a plain text response with no tool calls."""
    chunks = [
        _make_chunk(delta_content="Hello "),
        _make_chunk(delta_content="world"),
        _make_chunk(has_choices=False),
    ]

    async def fake_create(**kwargs):
        return _make_stream(chunks)

    messages = [{"role": "user", "content": "hi"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    # on_text called for each chunk
    assert callbacks["on_text"].await_count == 2
    callbacks["on_text"].assert_any_await("Hello ")
    callbacks["on_text"].assert_any_await("world")

    # No tool activity
    callbacks["on_tool_start"].assert_not_awaited()
    callbacks["on_tool_result"].assert_not_awaited()

    # Assistant message appended
    assistant_msgs = [m for m in messages if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == "Hello world"
    assert "tool_calls" not in assistant_msgs[0]


@pytest.mark.asyncio
async def test_single_tool_call(tmp_path, callbacks):
    """Agent makes one Read tool call, gets the result, then replies with text."""
    f = tmp_path / "data.txt"
    f.write_text("file contents")

    # Turn 1: model requests Read
    tool_chunks = [
        _make_chunk(delta_tool_calls=[
            _tool_call_delta(0, tc_id="call_r", name="Read",
                             arguments=json.dumps({"file_path": str(f)})),
        ]),
        _make_chunk(has_choices=False),
    ]
    # Turn 2: model replies with text
    text_chunks = [
        _make_chunk(delta_content="Got it"),
        _make_chunk(has_choices=False),
    ]
    turns = iter([tool_chunks, text_chunks])

    async def fake_create(**kwargs):
        return _make_stream(next(turns))

    messages = [{"role": "user", "content": "read the file"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    # Tool start and result reported
    callbacks["on_tool_start"].assert_awaited_once_with("Read", json.dumps({"file_path": str(f)}))
    callbacks["on_tool_result"].assert_awaited_once()
    assert callbacks["on_tool_result"].call_args[0][0] == "Read"
    assert callbacks["on_tool_result"].call_args[0][1] == "file contents"

    # Messages: user, assistant (tool_calls), tool, assistant (text)
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert "tool_calls" in messages[1]
    assert messages[2]["role"] == "tool"
    assert messages[2]["content"] == "file contents"
    assert messages[3]["role"] == "assistant"
    assert messages[3]["content"] == "Got it"


@pytest.mark.asyncio
async def test_multi_turn_tool_loop(tmp_path, callbacks):
    """Agent uses tools across two consecutive turns before giving a final text reply."""
    f1 = tmp_path / "a.txt"
    f1.write_text("aaa")
    f2 = tmp_path / "b.txt"
    f2.write_text("bbb")

    # Turn 1: Read f1
    turn1 = [
        _make_chunk(delta_tool_calls=[
            _tool_call_delta(0, tc_id="c1", name="Read",
                             arguments=json.dumps({"file_path": str(f1)})),
        ]),
        _make_chunk(has_choices=False),
    ]
    # Turn 2: Read f2
    turn2 = [
        _make_chunk(delta_tool_calls=[
            _tool_call_delta(0, tc_id="c2", name="Read",
                             arguments=json.dumps({"file_path": str(f2)})),
        ]),
        _make_chunk(has_choices=False),
    ]
    # Turn 3: final text
    turn3 = [
        _make_chunk(delta_content="All done"),
        _make_chunk(has_choices=False),
    ]
    turns = iter([turn1, turn2, turn3])
    create_call_count = 0

    async def fake_create(**kwargs):
        nonlocal create_call_count
        create_call_count += 1
        return _make_stream(next(turns))

    messages = [{"role": "user", "content": "go"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    # Two tool calls executed across two turns
    assert callbacks["on_tool_result"].await_count == 2
    assert callbacks["on_tool_result"].call_args_list[0][0][1] == "aaa"
    assert callbacks["on_tool_result"].call_args_list[1][0][1] == "bbb"

    # create called 3 times (one per loop iteration)
    assert create_call_count == 3

    # Final message is assistant text
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "All done"


@pytest.mark.asyncio
async def test_denied_tool_skips_execution(tmp_path, callbacks):
    """A denied tool call returns DENIED_RESULT and never touches the filesystem."""
    f = tmp_path / "important.txt"
    f.write_text("original")

    # Model tries to write to the file
    tool_chunks = [
        _make_chunk(delta_tool_calls=[
            _tool_call_delta(0, tc_id="call_w", name="Write",
                             arguments=json.dumps({"file_path": str(f), "content": "overwritten"})),
        ]),
        _make_chunk(has_choices=False),
    ]
    text_chunks = [
        _make_chunk(delta_content="OK"),
        _make_chunk(has_choices=False),
    ]
    turns = iter([tool_chunks, text_chunks])

    async def fake_create(**kwargs):
        return _make_stream(next(turns))

    async def deny_all(name, args, reason):
        return False

    callbacks["on_tool_confirm"] = deny_all
    messages = [{"role": "user", "content": "write"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls, \
         patch("app.agent.requires_confirmation", return_value=(True, "destructive")):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    # File untouched
    assert f.read_text() == "original"

    # Tool result is DENIED_RESULT
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"] == DENIED_RESULT

    # on_tool_result still called so UI can show the denial
    callbacks["on_tool_result"].assert_awaited_once()
    assert callbacks["on_tool_result"].call_args[0][1] == DENIED_RESULT


@pytest.mark.asyncio
async def test_usage_tracking_callback(callbacks):
    """on_usage is called with prompt tokens, completion tokens, and cost."""
    usage = MagicMock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    usage.cost = 0.0025

    chunks = [
        _make_chunk(delta_content="hi"),
        _make_chunk(has_choices=False, usage=usage),
    ]

    async def fake_create(**kwargs):
        return _make_stream(chunks)

    on_usage = MagicMock()
    callbacks["on_usage"] = on_usage
    messages = [{"role": "user", "content": "hello"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    on_usage.assert_called_once_with(100, 50, 0.0025)


# ---------------------------------------------------------------------------
# History integrity: every tool_call must always get a matching tool result
# ---------------------------------------------------------------------------


def test_parse_tool_args_accepts_object():
    assert parse_tool_args('{"file_path": "x.txt"}') == {"file_path": "x.txt"}


def test_parse_tool_args_rejects_empty_malformed_and_non_object():
    assert parse_tool_args("") is None
    assert parse_tool_args('{"file_path": "x') is None
    assert parse_tool_args("null") is None
    assert parse_tool_args("[1, 2]") is None


@pytest.mark.asyncio
async def test_malformed_tool_args_produce_error_result_not_crash(callbacks):
    """Truncated/empty argument JSON must not corrupt the message history."""
    tool_chunks = [
        _make_chunk(delta_tool_calls=[
            _tool_call_delta(0, tc_id="call_bad", name="Read", arguments='{"file_path": "x'),
        ]),
        _make_chunk(has_choices=False),
    ]
    text_chunks = [
        _make_chunk(delta_content="OK"),
        _make_chunk(has_choices=False),
    ]
    turns = iter([tool_chunks, text_chunks])

    async def fake_create(**kwargs):
        return _make_stream(next(turns))

    messages = [{"role": "user", "content": "read"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_bad"
    assert tool_msgs[0]["content"] == INVALID_ARGS_RESULT


@pytest.mark.asyncio
async def test_tool_handler_exception_becomes_error_result(callbacks):
    """A handler crash (e.g. missing required arg) yields an error tool message."""
    # Read with a wrong argument key -> KeyError inside the handler
    tool_chunks = [
        _make_chunk(delta_tool_calls=[
            _tool_call_delta(0, tc_id="call_boom", name="Read",
                             arguments=json.dumps({"wrong_key": "x.txt"})),
        ]),
        _make_chunk(has_choices=False),
    ]
    text_chunks = [
        _make_chunk(delta_content="OK"),
        _make_chunk(has_choices=False),
    ]
    turns = iter([tool_chunks, text_chunks])

    async def fake_create(**kwargs):
        return _make_stream(next(turns))

    messages = [{"role": "user", "content": "read"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"].startswith("Error executing Read")


@pytest.mark.asyncio
async def test_tool_call_id_and_name_can_arrive_in_later_chunks(callbacks, tmp_path):
    """Providers may send id/name in a later delta than index 0's first chunk."""
    f = tmp_path / "late.txt"
    f.write_text("late data")

    tool_chunks = [
        _make_chunk(delta_tool_calls=[_tool_call_delta(0, tc_id=None, name=None, arguments="")]),
        _make_chunk(delta_tool_calls=[
            _tool_call_delta(0, tc_id="call_late", name="Read",
                             arguments=json.dumps({"file_path": str(f)})),
        ]),
        _make_chunk(has_choices=False),
    ]
    text_chunks = [
        _make_chunk(delta_content="Done"),
        _make_chunk(has_choices=False),
    ]
    turns = iter([tool_chunks, text_chunks])

    async def fake_create(**kwargs):
        return _make_stream(next(turns))

    messages = [{"role": "user", "content": "read"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_late"
    assert tool_msgs[0]["content"] == "late data"


# ---------------------------------------------------------------------------
# Task subagent tool
# ---------------------------------------------------------------------------


def _task_call_chunks(prompt: str):
    return [
        _make_chunk(delta_tool_calls=[
            _tool_call_delta(0, tc_id="call_task", name="Task",
                             arguments=json.dumps({
                                 "description": "research something",
                                 "prompt": prompt,
                             })),
        ]),
        _make_chunk(has_choices=False),
    ]


@pytest.mark.asyncio
async def test_task_tool_runs_subagent_and_returns_final_text(callbacks):
    """A Task call spawns a nested conversation whose final text becomes the
    tool result; the subagent gets its own system prompt and no Task tool."""
    requests = []

    parent_task_turn = _task_call_chunks("Count the widgets. Report the total.")
    subagent_turn = [
        _make_chunk(delta_content="There are 42 widgets."),
        _make_chunk(has_choices=False),
    ]
    parent_final_turn = [
        _make_chunk(delta_content="Done"),
        _make_chunk(has_choices=False),
    ]
    turns = iter([parent_task_turn, subagent_turn, parent_final_turn])

    async def fake_create(**kwargs):
        requests.append(kwargs)
        return _make_stream(next(turns))

    messages = [{"role": "user", "content": "how many widgets?"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    # The subagent's final text is the parent's tool result
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_task"
    assert tool_msgs[0]["content"] == "There are 42 widgets."

    # Second request is the subagent's: fresh system prompt, no Task tool
    assert len(requests) == 3
    sub_request = requests[1]
    sub_tools = [t["function"]["name"] for t in sub_request["tools"]]
    assert "Task" not in sub_tools
    assert "Read" in sub_tools
    sub_messages = sub_request["messages"]
    assert sub_messages[0]["role"] == "system"
    assert "subagent" in sub_messages[0]["content"]
    assert sub_messages[1] == {
        "role": "user",
        "content": "Count the widgets. Report the total.",
    }
    # The parent's history never leaks into the subagent
    assert all("how many widgets?" not in str(m) for m in sub_messages)


@pytest.mark.asyncio
async def test_task_tool_respects_parent_allowlist(callbacks):
    """The subagent inherits the parent profile's tools (minus Task)."""
    requests = []

    parent_task_turn = _task_call_chunks("look around")
    subagent_turn = [
        _make_chunk(delta_content="report"),
        _make_chunk(has_choices=False),
    ]
    parent_final_turn = [
        _make_chunk(delta_content="ok"),
        _make_chunk(has_choices=False),
    ]
    turns = iter([parent_task_turn, subagent_turn, parent_final_turn])

    async def fake_create(**kwargs):
        requests.append(kwargs)
        return _make_stream(next(turns))

    messages = [{"role": "user", "content": "go"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(
            messages, "test-model", **callbacks,
            tool_allowlist=["Read", "Grep", "Task"],
        )

    sub_tools = [t["function"]["name"] for t in requests[1]["tools"]]
    assert sub_tools == ["Read", "Grep"]


@pytest.mark.asyncio
async def test_task_tool_empty_prompt_returns_error(callbacks):
    parent_task_turn = [
        _make_chunk(delta_tool_calls=[
            _tool_call_delta(0, tc_id="call_task", name="Task",
                             arguments=json.dumps({"description": "x", "prompt": "  "})),
        ]),
        _make_chunk(has_choices=False),
    ]
    parent_final_turn = [
        _make_chunk(delta_content="ok"),
        _make_chunk(has_choices=False),
    ]
    turns = iter([parent_task_turn, parent_final_turn])
    request_count = 0

    async def fake_create(**kwargs):
        nonlocal request_count
        request_count += 1
        return _make_stream(next(turns))

    messages = [{"role": "user", "content": "go"}]

    with patch("app.agent.API_KEY", "test-key"), \
         patch("app.agent.AsyncOpenAI") as mock_cls:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = fake_create
        mock_cls.return_value = mock_client

        await run_agent(messages, "test-model", **callbacks)

    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert tool_msgs[0]["content"].startswith("Error: Task requires")
    # No subagent request was made for the bad call
    assert request_count == 2
