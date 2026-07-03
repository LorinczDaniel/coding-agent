"""Pure lesson/coaching logic: goals, hints, milestones. No UI dependencies."""

import re
from collections.abc import Callable
from pathlib import Path

from .session import LessonState

HINT_LEVELS: tuple[tuple[str, str], ...] = (
    ("question", "Ask me one guiding question that points me toward the next step. Do not reveal the approach."),
    ("nudge", "Give a short nudge naming the concept or area to focus on. Still no code."),
    ("focused example", "Show a small, focused example of the technique in isolation, not the full solution for my task."),
    ("near-solution", "Walk me through the solution for the current task step by step, stopping just short of writing the complete final code unless I ask."),
)

MAX_HINT_LEVEL = len(HINT_LEVELS)

_LEARNING_GOAL_PATTERNS = (
    re.compile(
        r"\b(?:i\s+)?(?:want|wanna|would like|need|am trying|i'm trying)\s+to\s+"
        r"(?:learn|study|practice)\s+(?P<goal>[^.?!\n]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bhelp\s+me\s+(?:learn|study|practice)\s+(?P<goal>[^.?!\n]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:teach|coach)\s+me\s+(?:about\s+)?(?P<goal>[^.?!\n]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:i\s+)?(?:want|wanna|would like)\s+to\s+build\s+(?:my\s+own\s+)?(?P<goal>[^.?!\n]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:let's|lets)\s+(?:learn|study|practice|build)\s+(?P<goal>[^.?!\n]+)",
        re.IGNORECASE,
    ),
)


def _clean_learning_goal(goal: str) -> str | None:
    cleaned = goal.strip().strip("\"'`.,;:!? ")
    cleaned = re.split(
        r"\s+(?:from\s+scratch|from\s+the\s+ground\s+up|step\s+by\s+step|for\s+beginners|please|pls)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = re.split(
        r"\s+(?:because|but|so\s+that|so\s+i\s+can)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    cleaned = cleaned.strip().strip("\"'`.,;:!? ")
    return cleaned or None


def extract_learning_goal(text: str) -> str | None:
    """Pull a learning goal out of a natural-language message, if present."""
    for pattern in _LEARNING_GOAL_PATTERNS:
        match = pattern.search(text.strip())
        if match:
            return _clean_learning_goal(match.group("goal"))
    return None


def learn_goal_prompt(goal: str, workspace: str | None = None) -> str:
    prompt = (
        f"I want to build my own {goal}.\n\n"
        "Create a CodeCrafters-style learning path for this goal. "
        "Break it into 5-10 small milestones, then start with task 1 only. "
        "For task 1, include the expected outcome, a small implementation target, "
        "and how we will check it. Wait for my attempt before moving to task 2."
    )
    if workspace:
        prompt += (
            f"\n\nA lesson workspace exists at {workspace}/ with a TASK.md task card. "
            "Before explaining task 1, use your Write tool to:\n"
            f"1. Create {workspace}/main.py — a starter file with function stubs and "
            "# TODO comments for task 1. Stubs only, never the working solution.\n"
            f"2. Rewrite {workspace}/TASK.md so its current milestone, expected outcome, "
            "and how-it-will-be-checked sections describe task 1.\n"
            "Keep TASK.md up to date whenever we move to a new task."
        )
    return prompt


def hint_prompt(level: int) -> str:
    label, instruction = HINT_LEVELS[level - 1]
    return (
        f"I'm stuck on the current task. Give me a hint at strength {level} of "
        f"{MAX_HINT_LEVEL} ({label}). {instruction} Keep it focused on the current "
        "task only and stay in teaching mode."
    )


def hint_level_display(level: int) -> str:
    if level <= 0:
        return f"0/{MAX_HINT_LEVEL} (none)"
    clamped = min(level, MAX_HINT_LEVEL)
    return f"{clamped}/{MAX_HINT_LEVEL} ({HINT_LEVELS[clamped - 1][0]})"


def lesson_todos(lesson: LessonState, next_hint: str | None = None) -> list[dict]:
    todos: list[dict] = []
    for index, milestone in enumerate(lesson.milestones):
        if index < lesson.current_index:
            status = "completed"
        elif index == lesson.current_index:
            status = "in-progress"
        else:
            status = "not-started"
        todo: dict = {"id": index + 1, "title": milestone, "status": status}
        if status == "in-progress" and next_hint:
            todo["hint"] = f"next: {next_hint}"
        todos.append(todo)
    return todos


def next_action_hint(lesson: LessonState, root: Path | None = None) -> str:
    """One-line pointer for the current task: what to edit and how to verify."""
    slug = lesson_slug(lesson.goal)
    starter = (root or Path.cwd()) / "lessons" / slug / "main.py"
    edit = f"edit lessons/{slug}/main.py" if starter.exists() else "edit your solution"
    verify = "then /check" if current_check_command(lesson) is not None else "then ask the coach to review"
    return f"{edit}, {verify}"


def milestone_card(lesson: LessonState, index: int, next_hint: str | None = None) -> list[str]:
    """Summary lines for one milestone, shown when it is clicked in the panel."""
    if index < lesson.current_index:
        status = "completed"
    elif index == lesson.current_index:
        status = "in-progress"
    else:
        status = "not started"
    check = lesson.check_commands[index] if index < len(lesson.check_commands) else ""
    lines = [
        f"Milestone {index + 1}/{len(lesson.milestones)}: {lesson.milestones[index]}",
        f"Status: {status}",
        f"Check: {check or 'not set yet'}",
    ]
    if index == lesson.current_index and next_hint:
        lines.append(f"Next: {next_hint}")
    return lines


def read_task_card(goal: str, root: Path | None = None) -> str | None:
    """The workspace TASK.md contents, or None if it does not exist."""
    path = (root or Path.cwd()) / "lessons" / lesson_slug(goal) / "TASK.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def check_commands_from_todos(todos: list[dict]) -> tuple[str, ...]:
    """Extract each todo's check command, aligned with the milestone list.

    Uses the same title filter as the milestone extraction so index i here
    always belongs to milestone i; items without a check get "".
    """
    return tuple(
        check.strip() if isinstance(check := item.get("check"), str) else ""
        for item in todos
        if isinstance(item.get("title"), str) and item.get("title", "").strip()
    )


def current_check_command(lesson: LessonState) -> str | None:
    """The check command for the current milestone, or None if not set."""
    if not (0 <= lesson.current_index < len(lesson.check_commands)):
        return None
    return lesson.check_commands[lesson.current_index] or None


def check_prompt(milestone: str, command: str, output: str) -> str:
    return (
        f'I ran the check for the current task ("{milestone}").\n'
        f"Command: {command}\n"
        f"Output:\n```\n{output}\n```\n\n"
        "Judge this result against the task's expected outcome. If it passes, "
        "mark the milestone completed with TodoWrite (keeping each milestone's "
        "check command) and introduce the next task. If it fails, do not "
        "advance: explain what the output means and give me a hint toward "
        "fixing it, without the full solution."
    )


def current_index_from_todos(todos: list[dict], fallback: int) -> int:
    if not todos:
        return 0
    for index, item in enumerate(todos):
        if item.get("status") == "in-progress":
            return index
    completed_indexes = [index for index, item in enumerate(todos) if item.get("status") == "completed"]
    if completed_indexes:
        return min(completed_indexes[-1] + 1, len(todos))
    return min(fallback, len(todos) - 1)


def lesson_slug(goal: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", goal.strip()).strip("-").lower() or "lesson"


def _task_card(goal: str) -> str:
    return (
        f"# Lesson: {goal}\n"
        "\n"
        "## Goal\n"
        f"Build my own {goal}, one small milestone at a time.\n"
        "\n"
        "## Current milestone\n"
        "_The coach fills this in when task 1 starts._\n"
        "\n"
        "## Expected outcome\n"
        "_The coach fills this in when task 1 starts._\n"
        "\n"
        "## How it will be checked\n"
        "_The coach fills this in when task 1 starts._\n"
    )


def scaffold_lesson_workspace(goal: str, root: Path) -> Path:
    """Create lessons/<slug>/ under root with a TASK.md task card.

    Deterministic counterpart to the coach's prompt-driven starter file:
    the task card always exists even if the model under-delivers. Existing
    files are never overwritten, so re-running /learn resumes in place.
    """
    workspace = root / "lessons" / lesson_slug(goal)
    workspace.mkdir(parents=True, exist_ok=True)
    task_card = workspace / "TASK.md"
    if not task_card.exists():
        task_card.write_text(_task_card(goal), encoding="utf-8")
    return workspace


def lesson_session_name(goal: str, taken: Callable[[str], bool]) -> str:
    """Derive a fresh session name for a lesson so it never clobbers the
    conversation the learner started it from."""
    base = f"lesson-{lesson_slug(goal)}"[:48]
    name = base
    counter = 2
    while taken(name):
        name = f"{base}-{counter}"
        counter += 1
    return name
