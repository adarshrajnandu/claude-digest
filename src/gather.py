"""
Gather GitHub activity for the Claude ecosystem digest.

Reads state/state.json for deduplication, writes updated state after a
successful run. Handles watchlist repos + topic discovery. Returns a
DigestPayload (list[RepoActivity]).
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import TypedDict

import requests

logger = logging.getLogger(__name__)

STATE_FILE = "state/state.json"
MAX_REPOS = 15
MAX_COMMITS = 10
MAX_ISSUES = 10
MAX_RELEASES = 5
TOPIC_STAR_MIN = 10
LOOKBACK_DAYS = 3
PRUNE_DAYS = 30

TOPICS = ["claude", "claude-code", "anthropic", "mcp", "model-context-protocol"]


class RepoActivity(TypedDict):
    name: str
    stars: int
    description: str
    commits: list[dict]
    issues: list[dict]
    releases: list[dict]
    has_activity: bool
    is_new_this_run: bool
    star_velocity: int | None


DigestPayload = list[RepoActivity]


def sanitize(text: str, max_len: int = 200) -> str:
    if not text:
        return ""
    return text.replace("\n", " ").replace("\r", " ")[:max_len].strip()


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        logger.warning("stage=gather state file corrupted, starting fresh")
        return {}


def save_state(state: dict) -> None:
    os.makedirs("state", exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def prune_state(state: dict) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=PRUNE_DAYS)).date().isoformat()
    first_seen = state.get("first_seen_repos", {})
    star_history = state.get("star_history", {})

    pruned_first_seen = {k: v for k, v in first_seen.items() if v >= cutoff}
    pruned_star_history = {}
    for repo, dates in star_history.items():
        recent = {d: c for d, c in dates.items() if d >= cutoff}
        if recent:
            pruned_star_history[repo] = recent

    return {
        "seen_shas": state.get("seen_shas", {}),
        "first_seen_repos": pruned_first_seen,
        "star_history": pruned_star_history,
    }


def _make_headers() -> dict:
    pat = os.environ["GITHUB_PAT"]
    return {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _handle_github_error(response: requests.Response, context: str) -> None:
    if response.status_code == 401:
        raise RuntimeError(
            f"stage=gather GitHub API returned 401 for {context}: "
            "PAT is invalid or expired. Re-generate at github.com/settings/tokens"
        )
    if response.status_code == 403:
        reset = response.headers.get("X-RateLimit-Reset", "unknown")
        raise RuntimeError(
            f"stage=gather GitHub API returned 403 for {context}: "
            f"rate limit exceeded or insufficient scope. Rate limit resets at epoch {reset}"
        )
    response.raise_for_status()


def _fetch_repo_metadata(repo_name: str, headers: dict) -> dict | None:
    """Returns repo metadata dict (includes stargazers_count) or None on 403."""
    url = f"https://api.github.com/repos/{repo_name}"
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 403:
            reset = r.headers.get("X-RateLimit-Reset", "unknown")
            logger.warning(
                "stage=gather repo metadata 403 for %s (rate limit resets at %s) — star_velocity will be None",
                repo_name,
                reset,
            )
            return None
        if r.status_code == 401:
            _handle_github_error(r, repo_name)
        r.raise_for_status()
        return r.json()
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("stage=gather repo metadata fetch failed for %s: %s", repo_name, exc)
        return None


def _fetch_commits(repo_name: str, headers: dict, since: str) -> list[dict]:
    url = f"https://api.github.com/repos/{repo_name}/commits"
    try:
        r = requests.get(
            url,
            headers=headers,
            params={"since": since, "per_page": str(MAX_COMMITS)},
            timeout=30,
        )
        if r.status_code in (403, 409):
            return []
        r.raise_for_status()
        items = r.json()
        return [
            {
                "sha": c["sha"][:8],
                "message": sanitize(c["commit"]["message"], 200),
                "date": c["commit"]["author"]["date"][:10],
            }
            for c in items
            if isinstance(c, dict) and "sha" in c
        ]
    except Exception as exc:
        logger.warning("stage=gather commits fetch failed for %s: %s", repo_name, exc)
        return []


def _fetch_issues(repo_name: str, headers: dict, since: str) -> list[dict]:
    url = f"https://api.github.com/repos/{repo_name}/issues"
    try:
        r = requests.get(
            url,
            headers=headers,
            params={"state": "all", "since": since, "per_page": str(MAX_ISSUES)},
            timeout=30,
        )
        if r.status_code == 403:
            return []
        r.raise_for_status()
        return [
            {
                "title": sanitize(i["title"], 200),
                "state": i["state"],
                "labels": [sanitize(la["name"], 50) for la in i.get("labels", [])],
            }
            for i in r.json()
            if isinstance(i, dict) and "pull_request" not in i
        ]
    except Exception as exc:
        logger.warning("stage=gather issues fetch failed for %s: %s", repo_name, exc)
        return []


def _fetch_releases(repo_name: str, headers: dict) -> list[dict]:
    url = f"https://api.github.com/repos/{repo_name}/releases"
    try:
        r = requests.get(
            url,
            headers=headers,
            params={"per_page": str(MAX_RELEASES)},
            timeout=30,
        )
        if r.status_code == 403:
            return []
        r.raise_for_status()
        return [
            {
                "tag": sanitize(rel["tag_name"], 50),
                "name": sanitize(rel["name"] or rel["tag_name"], 100),
                "published_at": (rel.get("published_at") or "")[:10],
            }
            for rel in r.json()
            if isinstance(rel, dict) and not rel.get("draft")
        ]
    except Exception as exc:
        logger.warning("stage=gather releases fetch failed for %s: %s", repo_name, exc)
        return []


def _search_topic_repos(topic: str, headers: dict, pushed_since: str) -> list[dict]:
    """Returns list of repo dicts. Returns [] on 403 (non-blocking)."""
    url = "https://api.github.com/search/repositories"
    try:
        r = requests.get(
            url,
            headers=headers,
            params={
                "q": f"topic:{topic} stars:>{TOPIC_STAR_MIN} pushed:>{pushed_since}",
                "sort": "stars",
                "order": "desc",
                "per_page": str(MAX_REPOS),
            },
            timeout=30,
        )
        if r.status_code == 403:
            logger.warning(
                "stage=gather topic discovery returned 403 for topic:%s — continuing without it",
                topic,
            )
            return []
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as exc:
        logger.warning("stage=gather topic discovery failed for %s: %s — continuing", topic, exc)
        return []


def _has_activity(commits: list, issues: list, releases: list, is_watchlist: bool) -> bool:
    has_commits = len(commits) > 0
    has_closed_issues = any(i["state"] == "closed" for i in issues)
    has_releases = len(releases) > 0
    if is_watchlist:
        has_open_issues = any(i["state"] == "open" for i in issues)
        return has_commits or has_closed_issues or has_releases or has_open_issues
    return has_commits or has_closed_issues or has_releases


def _compute_star_velocity(
    repo_name: str,
    current_stars: int | None,
    star_history: dict,
) -> int | None:
    if current_stars is None:
        return None
    history = star_history.get(repo_name, {})
    if not history:
        return 0
    last_stars = history[max(history.keys())]
    return current_stars - last_stars


def gather(config: dict) -> DigestPayload:
    headers = _make_headers()

    state = load_state()
    seen_shas: dict = state.get("seen_shas", {})
    first_seen_repos: dict = state.get("first_seen_repos", {})
    star_history: dict = state.get("star_history", {})

    # Snapshot known repos at run start for is_new_this_run detection
    known_repos_at_start = set(first_seen_repos.keys())

    now = datetime.now(timezone.utc)
    since_iso = (now - timedelta(days=LOOKBACK_DAYS)).isoformat()
    pushed_since = (now - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    today = now.date().isoformat()

    watchlist: list[str] = config.get("watchlist", [])

    # Track 1: watchlist repos
    activities: list[RepoActivity] = []
    for repo_name in watchlist:
        meta = _fetch_repo_metadata(repo_name, headers)
        current_stars: int | None = meta.get("stargazers_count") if meta else None
        description = sanitize(meta.get("description") or "", 300) if meta else ""

        commits = _fetch_commits(repo_name, headers, since_iso)
        issues = _fetch_issues(repo_name, headers, since_iso)
        releases = _fetch_releases(repo_name, headers)

        # Filter commits by seen_shas
        repo_seen = set(seen_shas.get(repo_name, []))
        new_commits = [c for c in commits if c["sha"] not in repo_seen]

        velocity = _compute_star_velocity(repo_name, current_stars, star_history)
        is_new = repo_name not in known_repos_at_start

        activities.append(
            RepoActivity(
                name=repo_name,
                stars=current_stars or 0,
                description=description,
                commits=new_commits,
                issues=issues,
                releases=releases,
                has_activity=_has_activity(new_commits, issues, releases, is_watchlist=True),
                is_new_this_run=is_new,
                star_velocity=velocity,
            )
        )

    # Track 2: topic discovery
    discovered_names = {r["name"] for r in activities}
    discovered: list[dict] = []
    for topic in TOPICS:
        for repo in _search_topic_repos(topic, headers, pushed_since):
            name = repo.get("full_name", "")
            if name and name not in discovered_names:
                discovered_names.add(name)
                discovered.append(repo)

    # Sort discovered by stars descending and deduplicate
    discovered.sort(key=lambda r: r.get("stargazers_count", 0), reverse=True)

    for repo in discovered:
        if len(activities) >= MAX_REPOS:
            break
        repo_name = repo["full_name"]
        current_stars = repo.get("stargazers_count")
        description = sanitize(repo.get("description") or "", 300)

        commits = _fetch_commits(repo_name, headers, since_iso)
        issues = _fetch_issues(repo_name, headers, since_iso)
        releases = _fetch_releases(repo_name, headers)

        repo_seen = set(seen_shas.get(repo_name, []))
        new_commits = [c for c in commits if c["sha"] not in repo_seen]

        velocity = _compute_star_velocity(repo_name, current_stars, star_history)
        is_new = repo_name not in known_repos_at_start

        activities.append(
            RepoActivity(
                name=repo_name,
                stars=current_stars or 0,
                description=description,
                commits=new_commits,
                issues=issues,
                releases=releases,
                has_activity=_has_activity(new_commits, issues, releases, is_watchlist=False),
                is_new_this_run=is_new,
                star_velocity=velocity,
            )
        )

    # Update state for successful repos
    for activity in activities:
        repo_name = activity["name"]

        if repo_name not in first_seen_repos:
            first_seen_repos[repo_name] = today

        if activity["stars"] > 0:
            if repo_name not in star_history:
                star_history[repo_name] = {}
            star_history[repo_name][today] = activity["stars"]

        # Update seen_shas with new commits
        if repo_name not in seen_shas:
            seen_shas[repo_name] = []
        new_shas = [c["sha"] for c in activity["commits"]]
        seen_shas[repo_name] = list(set(seen_shas[repo_name]) | set(new_shas))

    save_state(
        prune_state(
            {
                "seen_shas": seen_shas,
                "first_seen_repos": first_seen_repos,
                "star_history": star_history,
            }
        )
    )

    return activities
