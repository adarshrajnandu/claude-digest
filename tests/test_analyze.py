"""Tests for analyze.py — LLM analysis, token guard, response validation."""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _active_payload():
    return [
        {
            "name": "anthropics/claude-code",
            "stars": 5000,
            "description": "Claude Code CLI",
            "commits": [{"sha": "abc12345", "message": "fix: bug", "date": "2026-04-25"}],
            "issues": [],
            "releases": [],
            "has_activity": True,
            "is_new_this_run": False,
            "star_velocity": 50,
        }
    ]


def _make_message(text: str, stop_reason: str = "end_turn"):
    content_block = MagicMock()
    content_block.text = text
    msg = MagicMock()
    msg.content = [content_block]
    msg.stop_reason = stop_reason
    return msg


# ---------------------------------------------------------------------------
# test_analyze_malformed — empty response → ValueError
# ---------------------------------------------------------------------------

def test_analyze_malformed(monkeypatch):
    """analyze() raises ValueError when Claude returns an empty response."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.delenv("MOCK_LLM", raising=False)

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_message("")
    mock_client.messages.count_tokens.return_value = MagicMock(input_tokens=1000)

    with patch("analyze.anthropic.Anthropic", return_value=mock_client):
        from analyze import analyze
        import importlib
        import analyze as analyze_mod
        importlib.reload(analyze_mod)

        with pytest.raises(ValueError, match="short response|malformed|empty"):
            analyze_mod.analyze(_active_payload(), {"model": "claude-sonnet-4-6"})


# ---------------------------------------------------------------------------
# test_analyze_max_tokens — truncated response → ValueError
# ---------------------------------------------------------------------------

def test_analyze_max_tokens(monkeypatch):
    """analyze() raises ValueError when finish_reason is max_tokens."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.delenv("MOCK_LLM", raising=False)

    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_message(
        "This is a very long response..." * 100,
        stop_reason="max_tokens",
    )
    mock_client.messages.count_tokens.return_value = MagicMock(input_tokens=1000)

    with patch("analyze.anthropic.Anthropic", return_value=mock_client):
        import importlib
        import analyze as analyze_mod
        importlib.reload(analyze_mod)

        with pytest.raises(ValueError, match="max_tokens|truncated"):
            analyze_mod.analyze(_active_payload(), {"model": "claude-sonnet-4-6"})


# ---------------------------------------------------------------------------
# test_token_guard — payload > 50k tokens → repo list truncated
# ---------------------------------------------------------------------------

def test_token_guard(monkeypatch):
    """analyze() truncates the repo list when token count exceeds 50k."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.delenv("MOCK_LLM", raising=False)

    # Build a large payload with multiple repos
    big_payload = []
    for i in range(10):
        big_payload.append({
            "name": f"repo/project-{i}",
            "stars": 100,
            "description": "A repo",
            "commits": [{"sha": f"sha{i}", "message": "commit", "date": "2026-04-25"}],
            "issues": [],
            "releases": [],
            "has_activity": True,
            "is_new_this_run": False,
            "star_velocity": 0,
        })

    call_count = {"n": 0}

    def fake_count_tokens(**kwargs):
        call_count["n"] += 1
        result = MagicMock()
        # First call returns over budget, subsequent calls reduce
        result.input_tokens = max(1000, 60_000 - call_count["n"] * 8000)
        return result

    mock_client = MagicMock()
    mock_client.messages.count_tokens.side_effect = fake_count_tokens
    mock_client.messages.create.return_value = _make_message("Good editorial content here." * 5)

    with patch("analyze.anthropic.Anthropic", return_value=mock_client):
        import importlib
        import analyze as analyze_mod
        importlib.reload(analyze_mod)

        result = analyze_mod.analyze(big_payload, {"model": "claude-sonnet-4-6"})

    # Should have truncated and still returned a result
    assert isinstance(result, str)
    assert len(result) > 0
    # count_tokens should have been called multiple times (truncation loop)
    assert call_count["n"] > 1
