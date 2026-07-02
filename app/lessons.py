"""Pure lesson/coaching logic: goals, hints, milestones. No UI dependencies."""

import re
from collections.abc import Callable

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


def learn_goal_prompt(goal: str) -> str:
    return (
        f"I want to build my own {goal}.\n\n"
        "Create a CodeCrafters-style learning path for this goal. "
        "Break it into 5-10 small milestones, then start with task 1 only. "
        "For task 1, include the expected outcome, a small implementation target, "
        "and how we will check it. Wait for my attempt before moving to task 2."
    )


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


def lesson_todos(lesson: LessonState) -> list[dict]:
    todos: list[dict] = []
    for index, milestone in enumerate(lesson.milestones):
        if index < lesson.current_index:
            status = "completed"
        elif index == lesson.current_index:
            status = "in-progress"
        else:
            status = "not-started"
        todos.append({"id": index + 1, "title": milestone, "status": status})
    return todos


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


def lesson_session_name(goal: str, taken: Callable[[str], bool]) -> str:
    """Derive a fresh session name for a lesson so it never clobbers the
    conversation the learner started it from."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", goal.strip()).strip("-").lower() or "lesson"
    base = f"lesson-{slug}"[:48]
    name = base
    counter = 2
    while taken(name):
        name = f"{base}-{counter}"
        counter += 1
    return name
