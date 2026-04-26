"""Render the editorial string into an HTML email via Jinja2."""

import re
from datetime import datetime, timezone
from markupsafe import Markup, escape

from jinja2 import Environment, FileSystemLoader


def _build_repo_index(payload: list) -> dict:
    """Build a lookup dict from repo name → RepoActivity."""
    return {r["name"]: r for r in (payload or [])}


def _repo_header(repo_name: str, repo_index: dict) -> str:
    """Render a rich repo section header with avatar, link, stars, velocity."""
    owner = repo_name.split("/")[0]
    avatar = f"https://github.com/{owner}.png?size=32"
    gh_url = f"https://github.com/{repo_name}"

    data = repo_index.get(repo_name)
    stars_html = ""
    velocity_html = ""
    links_html = ""

    if data:
        stars = data.get("stars", 0)
        if stars:
            stars_html = f'<span class="badge">★ {_fmt_stars(stars)}</span>'

        velocity = data.get("star_velocity")
        if velocity and velocity > 0:
            velocity_html = f'<span class="badge badge-green">↑ {velocity} this cycle</span>'

        # Commit links
        commit_links = []
        for c in (data.get("commits") or [])[:3]:
            sha = c.get("sha", "")
            msg = c.get("message", "")[:60]
            commit_links.append(
                f'<a href="{gh_url}/commit/{sha}" class="ref-link">'
                f'<span class="ref-sha">{sha[:7]}</span> {escape(msg)}</a>'
            )

        # Release links
        for rel in (data.get("releases") or [])[:2]:
            tag = rel.get("tag", "")
            name = rel.get("name", tag)[:40]
            commit_links.append(
                f'<a href="{gh_url}/releases/tag/{escape(tag)}" class="ref-link ref-release">'
                f'🏷 {escape(name)}</a>'
            )

        if commit_links:
            links_html = '<div class="ref-links">' + "".join(commit_links) + '</div>'

    return (
        f'<div class="repo-header">'
        f'  <img src="{avatar}" alt="" class="repo-avatar">'
        f'  <div class="repo-meta">'
        f'    <a href="{gh_url}" class="repo-name">{escape(repo_name)}</a>'
        f'    <div class="repo-badges">{stars_html}{velocity_html}</div>'
        f'  </div>'
        f'</div>'
        f'{links_html}'
    )


def _fmt_stars(n: int) -> str:
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def _md_to_html(text: str, repo_index: dict) -> str:
    """Convert Claude's markdown output to HTML, enriching repo section headers."""
    lines = text.split("\n")
    html_parts: list[str] = []
    buffer: list[str] = []
    in_fire = False
    in_signal = False

    def flush_buffer():
        if not buffer:
            return
        combined = " ".join(l for l in buffer if l.strip())
        if combined.strip():
            html_parts.append(f'<p>{_inline_md(combined)}</p>')
        buffer.clear()

    for line in lines:
        stripped = line.strip()

        # Section divider ---
        if stripped == "---":
            flush_buffer()
            if in_fire:
                html_parts.append('</div>')
                in_fire = False
            if in_signal:
                html_parts.append('</div>')
                in_signal = False
            html_parts.append('<hr class="divider">')
            continue

        # Catching fire heading
        if re.match(r'^\*\*Catching fire\*\*', stripped, re.IGNORECASE) or \
           re.match(r'^Catching fire\b', stripped, re.IGNORECASE):
            flush_buffer()
            if in_signal:
                html_parts.append('</div>')
                in_signal = False
            html_parts.append('<div class="section-fire"><p class="section-label">Catching fire 🔥</p>')
            in_fire = True
            continue

        # Signal of the week heading
        if re.match(r'^\*\*Signal of the week\*\*', stripped, re.IGNORECASE) or \
           re.match(r'^Signal of the week\b', stripped, re.IGNORECASE):
            flush_buffer()
            if in_fire:
                html_parts.append('</div>')
                in_fire = False
            html_parts.append('<div class="signal-box"><p class="section-label">Signal of the week</p>')
            in_signal = True
            continue

        # Repo section header: **owner/repo** OR ## owner/repo (standalone line)
        repo_match = (
            re.match(r'^\*\*([\w.\-]+/[\w.\-]+)\*\*\s*(?:—|--|-|–)?(.*)$', stripped)
            or re.match(r'^#{1,3}\s+([\w.\-]+/[\w.\-]+)\s*(?:—|--|-|–)?(.*)$', stripped)
        )
        if repo_match and not in_fire and not in_signal:
            flush_buffer()
            repo_name = repo_match.group(1)
            rest = repo_match.group(2).strip()
            html_parts.append('<div class="repo-section">')
            html_parts.append(_repo_header(repo_name, repo_index))
            if rest:
                html_parts.append(f'<p>{_inline_md(rest)}</p>')
            # Close repo-section after next paragraph flush — track with sentinel
            html_parts.append('__CLOSE_REPO__')
            continue

        # Close open repo-section before starting next block
        if '__CLOSE_REPO__' in html_parts and stripped and not buffer:
            # Already handled inline
            pass

        # Empty line = paragraph break
        if not stripped:
            flush_buffer()
            # Close repo-section div if pending
            while '__CLOSE_REPO__' in html_parts:
                idx = html_parts.index('__CLOSE_REPO__')
                html_parts[idx] = '</div>'
            continue

        buffer.append(stripped)

    flush_buffer()
    # Close any remaining open blocks
    while '__CLOSE_REPO__' in html_parts:
        idx = html_parts.index('__CLOSE_REPO__')
        html_parts[idx] = '</div>'
    if in_fire or in_signal:
        html_parts.append('</div>')

    return "\n".join(html_parts)


def _inline_md(text: str) -> str:
    """Convert inline markdown to HTML with XSS escaping."""
    escaped = str(escape(text))
    escaped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
    escaped = re.sub(r'`([^`]+)`', r'<code>\1</code>', escaped)
    return escaped


def render(editorial: str, date: str | None = None, payload: list | None = None) -> str:
    if date is None:
        date = datetime.now(timezone.utc).strftime("%B %-d, %Y")

    repo_index = _build_repo_index(payload or [])

    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=True,
    )
    template = env.get_template("email.html.j2")
    body_html = Markup(_md_to_html(editorial, repo_index))
    return template.render(body=body_html, date=date)
