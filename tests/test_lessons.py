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


# --- lesson_session_name ---

def test_lesson_session_name_slugifies():
    assert lesson_session_name("http server", lambda name: False) == "lesson-http-server"


def test_lesson_session_name_avoids_collisions():
    taken = {"lesson-redis", "lesson-redis-2"}
    assert lesson_session_name("redis", lambda name: name in taken) == "lesson-redis-3"


def test_lesson_session_name_handles_symbols_only_goal():
    name = lesson_session_name("!!!", lambda name: False)
    assert name == "lesson-lesson"
