import json

import pytest

from app.agents import (
    COACH_PROFILE,
    DEFAULT_PROFILE,
    MENTOR_PROFILE,
    PROFILES,
    AgentProfile,
    _custom_profiles_path,
    get_profile,
    list_profiles,
    load_custom_profiles,
    save_custom_profile,
    validate_allowed_tools,
    validate_profile_name,
)


COACH_TOOL_SET = {"Read", "Write", "Edit", "Bash", "Glob", "Grep", "TodoWrite"}
MENTOR_TOOL_SET = {"Read", "Glob", "Grep", "TodoWrite"}


def _custom_profile(name: str = "reviewer") -> AgentProfile:
    return AgentProfile(
        name=name,
        title="Code Reviewer",
        description="Reviews changes for correctness and clarity.",
        allowed_tools=("Read", "Grep"),
        system_addendum="Review the code and report the most important risks first.",
    )


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


def test_mentor_profile_is_registered_and_read_only():
    profile = PROFILES[MENTOR_PROFILE]

    assert isinstance(profile, AgentProfile)
    assert profile.name == "mentor"
    assert set(profile.allowed_tools) == MENTOR_TOOL_SET
    assert not {"Write", "Edit", "Bash"} & set(profile.allowed_tools)
    assert profile.system_addendum


def test_get_profile_returns_mentor_by_name():
    assert get_profile(MENTOR_PROFILE) is PROFILES[MENTOR_PROFILE]


def test_get_profile_rejects_unknown_profile():
    with pytest.raises(ValueError, match="Unknown agent profile: missing"):
        get_profile("missing")


def test_list_profiles_returns_registered_profiles(monkeypatch):
    monkeypatch.setattr("app.agents.load_custom_profiles", lambda: {})

    assert list_profiles() == (PROFILES[COACH_PROFILE], PROFILES[MENTOR_PROFILE])


def test_validate_profile_name_accepts_safe_custom_names():
    assert validate_profile_name("reviewer") is None
    assert validate_profile_name("test_agent-1") is None


def test_validate_profile_name_rejects_unsafe_or_builtin_names():
    assert "empty" in validate_profile_name("")
    assert "lowercase" in validate_profile_name("Reviewer")
    assert "lowercase" in validate_profile_name("has spaces")
    assert "built in" in validate_profile_name(COACH_PROFILE)


def test_validate_allowed_tools_uses_tool_registry():
    tools, err = validate_allowed_tools(["Read", "Grep", "Read"])

    assert err is None
    assert tools == ("Read", "Grep")


def test_validate_allowed_tools_rejects_unknown_tools():
    tools, err = validate_allowed_tools(["Read", "Nope"])

    assert tools is None
    assert "Unknown tool: Nope" in err
    assert "Read" in err


def test_save_and_load_custom_profile(tmp_path):
    profile = _custom_profile()

    err = save_custom_profile(profile, tmp_path)

    assert err is None
    assert load_custom_profiles(tmp_path) == {"reviewer": profile}
    data = json.loads(_custom_profiles_path(tmp_path).read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["profiles"][0]["allowed_tools"] == ["Read", "Grep"]


def test_save_custom_profile_rejects_builtin_conflicts(tmp_path):
    profile = AgentProfile(
        name=COACH_PROFILE,
        title="Other Coach",
        description="Attempts to replace the built-in coach.",
        allowed_tools=("Read",),
        system_addendum="Do something else.",
    )

    err = save_custom_profile(profile, tmp_path)

    assert "built in" in err
    assert not _custom_profiles_path(tmp_path).exists()


def test_invalid_custom_profile_data_is_ignored(tmp_path):
    path = _custom_profiles_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "version": 1,
        "profiles": [
            _custom_profile().__dict__,
            {"name": "bad name"},
            {
                "name": COACH_PROFILE,
                "title": "Fake Coach",
                "description": "Should not override built-in profiles.",
                "allowed_tools": ["Read"],
                "system_addendum": "Ignore the built-in coach.",
            },
            {
                "name": "unknown_tool",
                "title": "Unknown Tool",
                "description": "Has a tool that does not exist.",
                "allowed_tools": ["Nope"],
                "system_addendum": "Use an unknown tool.",
            },
            "not an object",
        ],
    }), encoding="utf-8")

    loaded = load_custom_profiles(tmp_path)

    assert loaded == {"reviewer": _custom_profile()}


def test_corrupt_custom_profiles_file_is_ignored(tmp_path):
    path = _custom_profiles_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")

    assert load_custom_profiles(tmp_path) == {}


def test_get_and_list_profiles_include_custom_profiles(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert save_custom_profile(_custom_profile()) is None

    assert get_profile("reviewer") == _custom_profile()
    assert [profile.name for profile in list_profiles()] == ["coach", "mentor", "reviewer"]
