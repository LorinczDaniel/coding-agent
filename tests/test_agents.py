import pytest

from app.agents import (
    COACH_PROFILE,
    DEFAULT_PROFILE,
    PROFILES,
    AgentProfile,
    get_profile,
    list_profiles,
)


COACH_TOOL_SET = {"Read", "Write", "Edit", "Bash", "Glob", "Grep", "TodoWrite"}


def test_coach_is_default_profile():
    assert DEFAULT_PROFILE == COACH_PROFILE
    assert DEFAULT_PROFILE == "coach"


def test_coach_profile_is_registered_and_complete():
    profile = PROFILES[COACH_PROFILE]

    assert isinstance(profile, AgentProfile)
    assert profile.name == "coach"
    assert profile.title == "Learning Coach"
    assert "CodeCrafters" in profile.description
    assert profile.allowed_tools
    assert profile.system_addendum


def test_coach_profile_has_full_direct_help_tool_policy():
    profile = PROFILES[COACH_PROFILE]

    assert set(profile.allowed_tools) == COACH_TOOL_SET
    assert {"Write", "Edit"}.issubset(profile.allowed_tools)


def test_coach_profile_contains_teaching_instructions():
    instructions = PROFILES[COACH_PROFILE].system_addendum.lower()

    for expected in [
        "build goal",
        "5-10 small milestones",
        "one next task at a time",
        "inspect the learner's code",
        "hints in increasing strength",
        "avoid complete solutions",
        "you may create, edit, and rewrite files",
        "prefer small, focused edits",
        "explain what you changed and why",
    ]:
        assert expected in instructions


def test_get_profile_returns_default_coach():
    assert get_profile() is PROFILES[COACH_PROFILE]


def test_get_profile_rejects_unknown_profile():
    with pytest.raises(ValueError, match="Unknown agent profile: missing"):
        get_profile("missing")


def test_list_profiles_returns_registered_profiles():
    assert list_profiles() == (PROFILES[COACH_PROFILE],)
