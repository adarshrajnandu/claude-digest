"""Tests for gather.py — GitHub data collection and state management."""

import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import gather as gather_mod
from gather import (
    sanitize,
    load_state,
    save_state,
    prune_state,
    gather,
    _has_activity,
    _compute_star_velocity,
)
from conftest import _make_github_repo, _make_commit, _make_issue, _make_release


# ---------------------------------------------------------------------------
# sanitize
# ---------------------------------------------------------------------------

def test_sanitize_strips_newlines():
    assert sanitize("hello\nworld") == "hello world"
    assert sanitize("a\r\nb") == "a  b"


def test_sanitize_truncates():
    assert len(sanitize("x" * 500, max_len=10)) == 10


def test_sanitize_empty():
    assert sanitize("") == ""
    assert sanitize(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# test_config_validation — missing/invalid watchlist → exit 1
# ---------------------------------------------------------------------------

def test_config_validation_missing_watchlist(tmp_path, monkeypatch):
    """main.py must exit 1 when config.yaml has no watchlist."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("sender_email: digest@example.com\nmodel: claude-sonnet-4-6\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    monkeypatch.setenv("SUBSCRIBER_EMAILS", "test@example.com")

    import importlib, main as main_mod
    importlib.reload(main_mod)

    with pytest.raises(SystemExit) as exc_info:
        main_mod._validate_env_and_config()
    assert exc_info.value.code == 1


def test_config_validation_invalid_repo_format(tmp_path, monkeypatch):
    """main.py must exit 1 for badly formatted repo names."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "watchlist:\n  - not-valid\n"
        "sender_email: digest@example.com\n"
        "model: claude-sonnet-4-6\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    monkeypatch.setenv("SUBSCRIBER_EMAILS", "test@example.com")

    import importlib, main as main_mod
    importlib.reload(main_mod)

    with pytest.raises(SystemExit) as exc_info:
        main_mod._validate_env_and_config()
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# test_gather_schema — RepoActivity shape + is_new_this_run + star_velocity
# ---------------------------------------------------------------------------

def _mock_response(status_code: int, json_data) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    r.headers = {}
    r.raise_for_status = MagicMock()
    return r


def test_gather_schema(tmp_path, monkeypatch):
    """gather() returns correctly shaped RepoActivity objects."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")

    config = {"watchlist": ["anthropics/claude-code"]}

    meta_response = _mock_response(200, {
        "full_name": "anthropics/claude-code",
        "stargazers_count": 5000,
        "description": "Claude Code CLI",
        "pushed_at": "2026-04-25T10:00:00Z",
    })
    commits_response = _mock_response(200, [_make_commit("abc12345")])
    issues_response = _mock_response(200, [_make_issue(state="closed")])
    releases_response = _mock_response(200, [_make_release()])
    # Topic discovery returns empty
    search_response = _mock_response(200, {"items": []})

    def mock_get(url, **kwargs):
        if "search/repositories" in url:
            return search_response
        if "/commits" in url:
            return commits_response
        if "/issues" in url:
            return issues_response
        if "/releases" in url:
            return releases_response
        return meta_response

    with patch("gather.requests.get", side_effect=mock_get):
        result = gather(config)

    assert len(result) == 1
    repo = result[0]
    assert repo["name"] == "anthropics/claude-code"
    assert repo["stars"] == 5000
    assert isinstance(repo["commits"], list)
    assert isinstance(repo["issues"], list)
    assert isinstance(repo["releases"], list)
    assert isinstance(repo["has_activity"], bool)
    assert isinstance(repo["is_new_this_run"], bool)
    assert repo["star_velocity"] == 0  # first run, no prior history
    assert repo["is_new_this_run"] is True  # no prior state


# ---------------------------------------------------------------------------
# test_dedup — watchlist + discovered overlap → no duplicates
# ---------------------------------------------------------------------------

def test_dedup(tmp_path, monkeypatch):
    """Repos discovered via topics that are already in watchlist are not duplicated."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")

    config = {"watchlist": ["anthropics/claude-code"]}

    meta_response = _mock_response(200, {
        "full_name": "anthropics/claude-code",
        "stargazers_count": 5000,
        "description": "Claude Code CLI",
        "pushed_at": "2026-04-25T10:00:00Z",
    })
    empty_list = _mock_response(200, [])
    # Topic discovery returns the same repo (claude-code)
    search_response = _mock_response(200, {
        "items": [_make_github_repo("anthropics/claude-code", stars=5000)]
    })

    def mock_get(url, **kwargs):
        if "search/repositories" in url:
            return search_response
        if "/commits" in url or "/issues" in url or "/releases" in url:
            return empty_list
        return meta_response

    with patch("gather.requests.get", side_effect=mock_get):
        result = gather(config)

    names = [r["name"] for r in result]
    assert names.count("anthropics/claude-code") == 1


# ---------------------------------------------------------------------------
# test_partial_gather — topic discovery 403, watchlist succeeds
# ---------------------------------------------------------------------------

def test_partial_gather(tmp_path, monkeypatch):
    """Topic discovery 403 must not raise; returns watchlist-only results."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")

    config = {"watchlist": ["anthropics/claude-code"]}

    meta_response = _mock_response(200, {
        "full_name": "anthropics/claude-code",
        "stargazers_count": 5000,
        "description": "Claude Code CLI",
    })
    forbidden = _mock_response(403, {})
    forbidden.headers = {"X-RateLimit-Reset": "1234567890"}
    empty_list = _mock_response(200, [])

    def mock_get(url, **kwargs):
        if "search/repositories" in url:
            return forbidden
        if "/commits" in url or "/issues" in url or "/releases" in url:
            return empty_list
        return meta_response

    with patch("gather.requests.get", side_effect=mock_get):
        result = gather(config)  # must NOT raise

    assert len(result) == 1
    assert result[0]["name"] == "anthropics/claude-code"


# ---------------------------------------------------------------------------
# test_first_run_state — missing state file → created, all is_new_this_run=True
# ---------------------------------------------------------------------------

def test_first_run_state(tmp_path, monkeypatch):
    """On first run (no state.json), all repos are marked is_new_this_run=True."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    # state.json deliberately absent
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")

    config = {"watchlist": ["anthropics/claude-code"]}

    meta_response = _mock_response(200, {
        "full_name": "anthropics/claude-code",
        "stargazers_count": 100,
        "description": "",
    })
    empty_list = _mock_response(200, [])
    search_response = _mock_response(200, {"items": []})

    def mock_get(url, **kwargs):
        if "search/repositories" in url:
            return search_response
        if "/commits" in url or "/issues" in url or "/releases" in url:
            return empty_list
        return meta_response

    with patch("gather.requests.get", side_effect=mock_get):
        result = gather(config)

    assert result[0]["is_new_this_run"] is True
    state_file = tmp_path / "state" / "state.json"
    assert state_file.exists()


# ---------------------------------------------------------------------------
# test_state_pruning — entries older than 30 days are removed
# ---------------------------------------------------------------------------

def test_state_pruning():
    """prune_state() removes first_seen_repos and star_history entries > 30 days old."""
    state = {
        "seen_shas": {"repo/a": ["sha1"]},
        "first_seen_repos": {
            "repo/old": "2025-12-01",   # > 30 days ago
            "repo/new": "2026-04-20",   # recent
        },
        "star_history": {
            "repo/old": {"2025-12-01": 100},
            "repo/new": {"2026-04-20": 200},
        },
    }
    pruned = prune_state(state)
    assert "repo/old" not in pruned["first_seen_repos"]
    assert "repo/new" in pruned["first_seen_repos"]
    assert "repo/old" not in pruned["star_history"]
    assert "repo/new" in pruned["star_history"]
    # seen_shas are not pruned
    assert pruned["seen_shas"] == {"repo/a": ["sha1"]}


# ---------------------------------------------------------------------------
# test_star_velocity_error — repo metadata 403 → star_velocity=None, history preserved
# ---------------------------------------------------------------------------

def test_star_velocity_error(tmp_path, monkeypatch):
    """When repo metadata returns 403, star_velocity=None and prior star_history is preserved."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("GITHUB_PAT", "ghp_fake")

    # Pre-seed star_history for the repo
    prior_state = {
        "seen_shas": {},
        "first_seen_repos": {},
        "star_history": {"anthropics/claude-code": {"2026-04-22": 4900}},
    }
    (tmp_path / "state" / "state.json").write_text(json.dumps(prior_state))

    config = {"watchlist": ["anthropics/claude-code"]}

    # Repo metadata returns 403 (rate limit)
    forbidden = _mock_response(403, {})
    forbidden.headers = {"X-RateLimit-Reset": "9999999999"}
    empty_list = _mock_response(200, [])
    search_response = _mock_response(200, {"items": []})

    def mock_get(url, **kwargs):
        if "search/repositories" in url:
            return search_response
        if "/commits" in url or "/issues" in url or "/releases" in url:
            return empty_list
        # repo metadata (includes stars) → 403
        return forbidden

    with patch("gather.requests.get", side_effect=mock_get):
        result = gather(config)

    assert result[0]["star_velocity"] is None

    # Prior star_history entry must be preserved (not overwritten)
    with open(tmp_path / "state" / "state.json") as f:
        saved_state = json.load(f)
    assert saved_state["star_history"]["anthropics/claude-code"].get("2026-04-22") == 4900


# ---------------------------------------------------------------------------
# _has_activity — watchlist vs discovered threshold
# ---------------------------------------------------------------------------

def test_has_activity_watchlist_open_issues_only():
    """Watchlist repos with only open issues are considered active."""
    issues = [{"state": "open", "labels": []}]
    assert _has_activity([], issues, [], is_watchlist=True) is True


def test_has_activity_discovered_open_issues_only():
    """Discovered repos with only open issues are NOT considered active."""
    issues = [{"state": "open", "labels": []}]
    assert _has_activity([], issues, [], is_watchlist=False) is False
