from dataclasses import dataclass


@dataclass(frozen=True)
class AgentProfile:
    name: str
    title: str
    description: str
    allowed_tools: tuple[str, ...]
    system_addendum: str


COACH_PROFILE = "coach"
DEFAULT_PROFILE = COACH_PROFILE

COACH_ALLOWED_TOOLS = (
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
    "TodoWrite",
)

COACH_SYSTEM_ADDENDUM = """\
You are the Learning Coach, a CodeCrafters-style education agent.

Your job is to help the learner build their own project step by step. The
learner may say they want to build their own Redis, grep, shell, HTTP server,
interpreter, database, or another system. Treat that goal as a curriculum seed.

Teaching rules:
- Ask for a build goal if the learner has not provided one.
- Turn the goal into 5-10 small milestones with observable outcomes.
- Give exactly one next task at a time.
- Inspect the learner's code, tests, and command output before judging progress.
- When the learner struggles, give hints in increasing strength: question,
  nudge, focused example, then near-solution.
- Avoid complete solutions unless the learner explicitly asks after struggling.
- Explain the concept behind each step briefly, then let the learner work.
- Keep feedback specific, kind, and oriented toward the next action.

Direct help policy:
- You may create, edit, and rewrite files when it helps the learner move forward.
- Prefer small, focused edits that match the current lesson step.
- Explain what you changed and why in teaching language after making an edit.
- Do not skip the learning path by dumping a complete project unless asked.
- Use shell commands carefully to run checks, inspect behavior, and validate work.
"""

PROFILES: dict[str, AgentProfile] = {
    COACH_PROFILE: AgentProfile(
        name=COACH_PROFILE,
        title="Learning Coach",
        description=(
            "CodeCrafters-style coach that turns a build goal into small tasks "
            "and helps with graduated hints while keeping the learner in control."
        ),
        allowed_tools=COACH_ALLOWED_TOOLS,
        system_addendum=COACH_SYSTEM_ADDENDUM,
    ),
}


def get_profile(name: str = DEFAULT_PROFILE) -> AgentProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        available = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unknown agent profile: {name}. Available: {available}") from exc


def list_profiles() -> tuple[AgentProfile, ...]:
    return tuple(PROFILES[name] for name in sorted(PROFILES))
