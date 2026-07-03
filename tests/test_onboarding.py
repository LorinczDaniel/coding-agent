import os

import app.agent
from app.onboarding import SIGNUP_URL, save_api_key, validate_api_key

# --- validate_api_key ---

def test_validate_rejects_empty_key():
    assert validate_api_key("") is not None
    assert validate_api_key("   ") is not None


def test_validate_rejects_key_with_inner_whitespace():
    assert validate_api_key("sk-or wrong") is not None


def test_validate_rejects_obviously_truncated_key():
    assert validate_api_key("sk-or") is not None


def test_validate_accepts_plausible_key():
    assert validate_api_key("sk-or-v1-abcdef0123456789") is None
    assert validate_api_key("  sk-or-v1-abcdef0123456789  ") is None


def test_signup_url_points_at_openrouter():
    assert "openrouter.ai" in SIGNUP_URL


# --- save_api_key ---

def _sandbox_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(app.agent, "API_KEY", None)


def test_save_creates_env_file_and_activates_key(tmp_path, monkeypatch):
    _sandbox_key(monkeypatch)

    err = save_api_key("sk-or-v1-abcdef0123456789", tmp_path)

    assert err is None
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789" in content
    assert app.agent.API_KEY == "sk-or-v1-abcdef0123456789"
    assert not (tmp_path / ".env.tmp").exists()


def test_save_strips_whitespace_from_key(tmp_path, monkeypatch):
    _sandbox_key(monkeypatch)

    assert save_api_key("  sk-or-v1-abcdef0123456789\n", tmp_path) is None

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789\n" in content


def test_save_preserves_other_env_lines(tmp_path, monkeypatch):
    _sandbox_key(monkeypatch)
    (tmp_path / ".env").write_text(
        "# comment\nOPENROUTER_BASE_URL=https://example.test\n", encoding="utf-8"
    )

    assert save_api_key("sk-or-v1-abcdef0123456789", tmp_path) is None

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "# comment" in content
    assert "OPENROUTER_BASE_URL=https://example.test" in content
    assert "OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789" in content


def test_save_replaces_existing_key_line_without_duplicating(tmp_path, monkeypatch):
    _sandbox_key(monkeypatch)
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=old-key-0123456789\n", encoding="utf-8")

    assert save_api_key("sk-or-v1-abcdef0123456789", tmp_path) is None

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert content.count("OPENROUTER_API_KEY=") == 1
    assert "old-key" not in content
    assert "OPENROUTER_API_KEY=sk-or-v1-abcdef0123456789" in content


def test_save_activates_key_for_current_process(tmp_path, monkeypatch):
    _sandbox_key(monkeypatch)

    assert save_api_key("sk-or-v1-abcdef0123456789", tmp_path) is None

    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-abcdef0123456789"
    assert app.agent.has_api_key() is True


def test_save_rejects_invalid_key_and_leaves_env_untouched(tmp_path, monkeypatch):
    _sandbox_key(monkeypatch)
    (tmp_path / ".env").write_text("KEEP=me\n", encoding="utf-8")

    err = save_api_key("not a key", tmp_path)

    assert err is not None
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "KEEP=me\n"
    assert app.agent.API_KEY is None
