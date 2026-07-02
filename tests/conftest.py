import pytest


@pytest.fixture(autouse=True)
def _isolate_persistence(tmp_path, monkeypatch):
    """Keep every test hermetic: no test may read or write the developer's real
    ~/.claude-agent session store or the repo's .claude-agent profile store.

    Individual tests can still monkeypatch these seams again; a later patch
    simply wins.
    """
    monkeypatch.setattr(
        "app.session._sessions_dir",
        lambda cwd=None: tmp_path / "session-store",
    )
    monkeypatch.setattr(
        "app.agents._custom_profiles_path",
        lambda cwd=None: (cwd or tmp_path) / ".claude-agent" / "profiles.json",
    )
