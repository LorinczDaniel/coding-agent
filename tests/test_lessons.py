from app.lessons import (
    MAX_HINT_LEVEL,
    check_commands_from_todos,
    check_prompt,
    current_check_command,
    current_index_from_todos,
    extract_learning_goal,
    hint_level_display,
    hint_prompt,
    learn_goal_prompt,
    lesson_session_name,
    lesson_todos,
    milestone_card,
    next_action_hint,
    read_task_card,
    scaffold_lesson_workspace,
)
from app.session import LessonState

# --- extract_learning_goal ---

def test_extract_goal_want_to_learn():
    assert extract_learning_goal("I want to learn C++") == "C++"


def test_extract_goal_help_me_learn():
    assert extract_learning_goal("help me learn rust") == "rust"


def test_extract_goal_teach_me():
    assert extract_learning_goal("teach me about sockets") == "sockets"


def test_extract_goal_build_my_own():
    assert extract_learning_goal("I want to build my own redis") == "redis"


def test_extract_goal_lets_build():
    assert extract_learning_goal("let's build a shell") == "a shell"


def test_extract_goal_strips_filler_suffixes():
    assert extract_learning_goal("I want to learn grep from scratch") == "grep"
    assert extract_learning_goal("teach me about http step by step") == "http"
    assert extract_learning_goal("I want to learn sql because I need it") == "sql"


def test_extract_goal_none_for_plain_message():
    assert extract_learning_goal("what does this error mean?") is None


def test_extract_goal_none_for_empty_goal():
    assert extract_learning_goal("I want to learn ...") is None


# --- prompts and display ---

def test_learn_goal_prompt_mentions_milestones():
    prompt = learn_goal_prompt("redis")
    assert "my own redis" in prompt
    assert "5-10 small milestones" in prompt
    assert "task 1" in prompt


def test_hint_prompt_levels():
    assert "strength 1 of 4 (question)" in hint_prompt(1)
    assert "strength 4 of 4 (near-solution)" in hint_prompt(MAX_HINT_LEVEL)


def test_learn_goal_prompt_with_workspace_instructs_scaffolding():
    prompt = learn_goal_prompt("grep", workspace="lessons/grep")
    assert "lessons/grep" in prompt
    assert "TASK.md" in prompt
    assert "main.py" in prompt
    assert "TODO" in prompt


def test_learn_goal_prompt_without_workspace_omits_scaffolding():
    prompt = learn_goal_prompt("grep")
    assert "TASK.md" not in prompt
    assert "main.py" not in prompt


# --- scaffold_lesson_workspace ---

def test_scaffold_creates_workspace_with_task_card(tmp_path):
    workspace = scaffold_lesson_workspace("grep", tmp_path)

    assert workspace == tmp_path / "lessons" / "grep"
    card = (workspace / "TASK.md").read_text(encoding="utf-8")
    assert "grep" in card
    assert "## Goal" in card
    assert "## Current milestone" in card
    assert "## Expected outcome" in card
    assert "## How it will be checked" in card


def test_scaffold_slugifies_goal(tmp_path):
    workspace = scaffold_lesson_workspace("HTTP server!", tmp_path)
    assert workspace == tmp_path / "lessons" / "http-server"


def test_scaffold_preserves_existing_task_card(tmp_path):
    workspace = tmp_path / "lessons" / "grep"
    workspace.mkdir(parents=True)
    (workspace / "TASK.md").write_text("my notes", encoding="utf-8")

    scaffold_lesson_workspace("grep", tmp_path)

    assert (workspace / "TASK.md").read_text(encoding="utf-8") == "my notes"


def test_hint_level_display():
    assert hint_level_display(0) == "0/4 (none)"
    assert hint_level_display(2) == "2/4 (nudge)"
    assert hint_level_display(99) == "4/4 (near-solution)"


# --- current_index_from_todos ---

def test_current_index_prefers_in_progress():
    todos = [
        {"status": "completed"},
        {"status": "in-progress"},
        {"status": "not-started"},
    ]
    assert current_index_from_todos(todos, 0) == 1


def test_current_index_after_last_completed():
    todos = [{"status": "completed"}, {"status": "completed"}, {"status": "not-started"}]
    assert current_index_from_todos(todos, 0) == 2


def test_current_index_falls_back_when_no_progress():
    todos = [{"status": "not-started"}, {"status": "not-started"}]
    assert current_index_from_todos(todos, 5) == 1


def test_current_index_empty_todos():
    assert current_index_from_todos([], 3) == 0


# --- check commands ---

def test_check_commands_from_todos_align_with_titles():
    todos = [
        {"id": 1, "title": "Parse args", "status": "completed", "check": "python main.py -h"},
        {"id": 2, "title": "Search files", "status": "in-progress"},
        {"id": 3, "title": "   ", "status": "not-started", "check": "ignored"},
        {"id": 4, "title": "Format output", "status": "not-started", "check": "  pytest -q  "},
    ]
    # Items without a usable title are dropped, exactly like milestones, so
    # the commands stay aligned with the milestone list.
    assert check_commands_from_todos(todos) == ("python main.py -h", "", "pytest -q")


def test_check_commands_from_todos_ignore_non_string_check():
    todos = [{"id": 1, "title": "Parse args", "status": "in-progress", "check": 5}]
    assert check_commands_from_todos(todos) == ("",)


def test_current_check_command_returns_command_for_current_milestone():
    lesson = LessonState(
        goal="grep",
        milestones=("Parse args", "Search files"),
        check_commands=("echo a", "echo b"),
        current_index=1,
    )
    assert current_check_command(lesson) == "echo b"


def test_current_check_command_none_when_unset_blank_or_finished():
    assert current_check_command(LessonState(goal="grep", milestones=("a",))) is None
    blank = LessonState(goal="grep", milestones=("a", "b"), check_commands=("", "echo b"))
    assert current_check_command(blank) is None
    finished = LessonState(
        goal="grep", milestones=("a",), check_commands=("echo a",), current_index=1,
    )
    assert current_check_command(finished) is None


def test_check_prompt_includes_command_output_and_verdict_request():
    prompt = check_prompt("Search files", "pytest -q", "[exit 0]\n[stdout]\n3 passed")
    assert "Search files" in prompt
    assert "pytest -q" in prompt
    assert "3 passed" in prompt
    assert "TodoWrite" in prompt
    assert "hint" in prompt.lower()


# --- next_action_hint ---

def test_next_action_hint_points_at_starter_file(tmp_path):
    (tmp_path / "lessons" / "grep").mkdir(parents=True)
    (tmp_path / "lessons" / "grep" / "main.py").write_text("x", encoding="utf-8")
    lesson = LessonState(goal="grep", milestones=("Parse args",), check_commands=("pytest -q",))

    assert next_action_hint(lesson, tmp_path) == "edit lessons/grep/main.py, then /check"


def test_next_action_hint_generic_without_starter_file(tmp_path):
    lesson = LessonState(goal="grep", milestones=("Parse args",), check_commands=("pytest -q",))

    assert next_action_hint(lesson, tmp_path) == "edit your solution, then /check"


def test_next_action_hint_without_check_command_suggests_review(tmp_path):
    lesson = LessonState(goal="grep", milestones=("Parse args",))

    assert next_action_hint(lesson, tmp_path) == "edit your solution, then ask the coach to review"


# --- lesson_todos hint ---

def test_lesson_todos_attach_hint_to_current_task():
    lesson = LessonState(goal="grep", milestones=("Parse args", "Search files"), current_index=1)

    todos = lesson_todos(lesson, next_hint="edit lessons/grep/main.py, then /check")

    assert todos[0] == {"id": 1, "title": "Parse args", "status": "completed"}
    assert todos[1] == {
        "id": 2,
        "title": "Search files",
        "status": "in-progress",
        "hint": "next: edit lessons/grep/main.py, then /check",
    }


def test_lesson_todos_without_hint_stay_plain():
    lesson = LessonState(goal="grep", milestones=("Parse args",))

    todos = lesson_todos(lesson)

    assert todos == [{"id": 1, "title": "Parse args", "status": "in-progress"}]


def test_lesson_todos_finished_lesson_has_no_hint():
    lesson = LessonState(goal="grep", milestones=("Parse args",), current_index=1)

    todos = lesson_todos(lesson, next_hint="edit main.py, then /check")

    assert todos == [{"id": 1, "title": "Parse args", "status": "completed"}]


# --- milestone_card ---

def test_milestone_card_for_current_task_shows_check_and_next():
    lesson = LessonState(
        goal="grep",
        milestones=("Parse args", "Search files"),
        check_commands=("", "pytest -q"),
        current_index=1,
    )

    card = milestone_card(lesson, 1, next_hint="edit lessons/grep/main.py, then /check")

    assert card == [
        "Milestone 2/2: Search files",
        "Status: in-progress",
        "Check: pytest -q",
        "Next: edit lessons/grep/main.py, then /check",
    ]


def test_milestone_card_for_other_tasks_has_no_next_line():
    lesson = LessonState(
        goal="grep",
        milestones=("Parse args", "Search files", "Format output"),
        check_commands=("echo a",),
        current_index=1,
    )

    completed = milestone_card(lesson, 0, next_hint="edit main.py, then /check")
    upcoming = milestone_card(lesson, 2, next_hint="edit main.py, then /check")

    assert completed == ["Milestone 1/3: Parse args", "Status: completed", "Check: echo a"]
    assert upcoming == ["Milestone 3/3: Format output", "Status: not started", "Check: not set yet"]


# --- read_task_card ---

def test_read_task_card_reads_workspace_card(tmp_path):
    workspace = tmp_path / "lessons" / "grep"
    workspace.mkdir(parents=True)
    (workspace / "TASK.md").write_text("# Lesson: grep\ncard body", encoding="utf-8")

    assert read_task_card("grep", tmp_path) == "# Lesson: grep\ncard body"


def test_read_task_card_missing_returns_none(tmp_path):
    assert read_task_card("grep", tmp_path) is None


# --- lesson_session_name ---

def test_lesson_session_name_slugifies():
    assert lesson_session_name("http server", lambda name: False) == "lesson-http-server"


def test_lesson_session_name_avoids_collisions():
    taken = {"lesson-redis", "lesson-redis-2"}
    assert lesson_session_name("redis", lambda name: name in taken) == "lesson-redis-3"


def test_lesson_session_name_handles_symbols_only_goal():
    name = lesson_session_name("!!!", lambda name: False)
    assert name == "lesson-lesson"
