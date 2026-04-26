"""Render the editorial string into an HTML email via Jinja2."""

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


def render(editorial: str, date: str | None = None) -> str:
    if date is None:
        date = datetime.now(timezone.utc).strftime("%B %-d, %Y")

    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=True,
    )
    template = env.get_template("email.html.j2")
    return template.render(body=editorial, date=date)
