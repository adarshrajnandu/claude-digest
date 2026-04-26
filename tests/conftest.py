"""Shared pytest fixtures."""

import json
import sys
import os
import pytest

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _make_github_repo(name: str, stars: int = 100) -> dict:
    return {
        "full_name": name,
        "stargazers_count": stars,
        "description": f"Mock description for {name}",
        "pushed_at": "2026-04-25T10:00:00Z",
    }


def _make_commit(sha: str = "abc12345abc12345abc12345abc12345abc12345") -> dict:
    return {
        "sha": sha,
        "commit": {
            "message": "fix: some bug",
            "author": {"date": "2026-04-25T10:00:00Z"},
        },
    }


def _make_issue(title: str = "Open issue", state: str = "open") -> dict:
    return {"title": title, "state": state, "labels": []}


def _make_release(tag: str = "v1.0.0") -> dict:
    return {"tag_name": tag, "name": f"Release {tag}", "published_at": "2026-04-25T10:00:00Z", "draft": False}
