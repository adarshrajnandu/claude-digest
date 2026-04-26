"""Tests for main.py — pipeline orchestration and DRY_RUN handling."""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _quiet_payload():
    return [
        {
            "name": "anthropics/claude-code",
            "stars": 5000,
            "description": "Claude Code CLI",
            "commits": [],
            "issues": [],
            "releases": [],
            "has_activity": False,
            "is_new_this_run": False,
            "star_velocity": 0,
        }
    ]


def _active_payload():
    return [
        {
            "name": "anthropics/claude-code",
            "stars": 5000,
            "description": "Claude Code CLI",
            "commits": [{"sha": "abc12345", "message": "fix", "date": "2026-04-25"}],
            "issues": [],
            "releases": [],
            "has_activity": True,
            "is_new_this_run": False,
            "star_velocity": 50,
        }
    ]


def _mock_config():
    return {
        "watchlist": ["anthropics/claude-code"],
        "sender_email": "digest@example.com",
        "model": "claude-sonnet-4-6",
        "github_pages": {"enabled": False},
    }


# ---------------------------------------------------------------------------
# test_dry_run — DRY_RUN=1 → send() not called
# ---------------------------------------------------------------------------

def test_dry_run(tmp_path, monkeypatch, capsys):
    """DRY_RUN=1 must skip send() entirely."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "templates").mkdir()

    # Copy the template
    import shutil
    template_src = os.path.join(os.path.dirname(__file__), "..", "templates", "email.html.j2")
    shutil.copy(template_src, tmp_path / "templates" / "email.html.j2")

    # Write minimal config.yaml
    (tmp_path / "config.yaml").write_text(
        "watchlist:\n  - anthropics/claude-code\n"
        "sender_email: digest@example.com\n"
        "model: claude-sonnet-4-6\n"
    )

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    monkeypatch.setenv("SUBSCRIBER_EMAILS", "test@example.com")

    mock_send = MagicMock()

    with patch("gather.gather", return_value=_active_payload()), \
         patch("analyze.analyze", return_value="Editorial content here." * 5), \
         patch("send.send", mock_send):

        import importlib
        import main as main_mod
        importlib.reload(main_mod)

        with pytest.raises(SystemExit) as exc_info:
            main_mod.main()

    mock_send.assert_not_called()
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# test_dry_run_string — DRY_RUN="false" → send() IS called
# ---------------------------------------------------------------------------

def test_dry_run_string_false(tmp_path, monkeypatch):
    """DRY_RUN='false' (string) must NOT skip send() — only '1' and 'true' skip it."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "templates").mkdir()

    import shutil
    template_src = os.path.join(os.path.dirname(__file__), "..", "templates", "email.html.j2")
    shutil.copy(template_src, tmp_path / "templates" / "email.html.j2")

    # Write minimal config.yaml
    (tmp_path / "config.yaml").write_text(
        "watchlist:\n  - anthropics/claude-code\n"
        "sender_email: digest@example.com\n"
        "model: claude-sonnet-4-6\n"
    )

    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    monkeypatch.setenv("SUBSCRIBER_EMAILS", "test@example.com")

    mock_send = MagicMock()

    with patch("gather.gather", return_value=_active_payload()), \
         patch("analyze.analyze", return_value="Editorial content here." * 5), \
         patch("send.send", mock_send):

        import importlib
        import main as main_mod
        importlib.reload(main_mod)

        main_mod.main()  # no sys.exit on the happy path

    mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# test_all_quiet — all repos inactive → no email sent, exit 0
# ---------------------------------------------------------------------------

def test_all_quiet(tmp_path, monkeypatch):
    """When all repos have has_activity=False, pipeline exits 0 without sending email."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()

    # Write minimal config.yaml
    (tmp_path / "config.yaml").write_text(
        "watchlist:\n  - anthropics/claude-code\n"
        "sender_email: digest@example.com\n"
        "model: claude-sonnet-4-6\n"
    )

    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    monkeypatch.setenv("SUBSCRIBER_EMAILS", "test@example.com")

    mock_send = MagicMock()
    mock_analyze = MagicMock()

    with patch("gather.gather", return_value=_quiet_payload()), \
         patch("analyze.analyze", mock_analyze), \
         patch("send.send", mock_send):

        import importlib
        import main as main_mod
        importlib.reload(main_mod)

        with pytest.raises(SystemExit) as exc_info:
            main_mod.main()

    assert exc_info.value.code == 0
    mock_analyze.assert_not_called()
    mock_send.assert_not_called()
