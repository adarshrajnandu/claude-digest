"""
Orchestrate the gather → analyze → render → send pipeline.

Validates all required environment variables and config on startup before
making any API calls. Exits 1 loudly on any validation failure.
"""

import logging
import os
import re
import sys
from datetime import datetime, timezone

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def _validate_env_and_config() -> tuple[dict, list[str]]:
    """Validate all required secrets and config. Exits 1 on failure."""
    errors: list[str] = []

    # Required env vars
    for var in ("GITHUB_PAT", "ANTHROPIC_API_KEY", "RESEND_API_KEY"):
        if not os.environ.get(var):
            errors.append(f"Missing required environment variable: {var}")

    # SUBSCRIBER_EMAILS
    raw_subscribers = os.environ.get("SUBSCRIBER_EMAILS", "")
    subscribers = [e.strip() for e in raw_subscribers.split(",") if e.strip()]
    if not subscribers:
        errors.append("SUBSCRIBER_EMAILS is empty or missing")
    else:
        email_re = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
        for email in subscribers:
            if not email_re.match(email):
                errors.append(f"Invalid email in SUBSCRIBER_EMAILS: {email!r}")

    # config.yaml
    try:
        with open("config.yaml") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        errors.append("config.yaml not found")
        config = {}
    except yaml.YAMLError as exc:
        errors.append(f"config.yaml parse error: {exc}")
        config = {}

    if not isinstance(config, dict):
        errors.append("config.yaml must be a YAML mapping (key: value), not a scalar or list")
        config = {}

    if config:
        watchlist = config.get("watchlist")
        if not watchlist:
            errors.append("config.yaml missing 'watchlist' key or it is empty")
        else:
            repo_re = re.compile(r"^[\w.-]+/[\w.-]+$")
            for repo in watchlist:
                if not repo_re.match(str(repo)):
                    errors.append(f"Invalid repo format in watchlist: {repo!r} (expected 'owner/repo')")

        if not config.get("sender_email"):
            errors.append("config.yaml missing 'sender_email'")

    if errors:
        for err in errors:
            logger.error("stage=startup %s", err)
        sys.exit(1)

    return config, subscribers


def main() -> None:
    config, subscribers = _validate_env_and_config()

    dry_run = os.environ.get("DRY_RUN") in ("1", "true")
    if dry_run:
        logger.info("stage=startup DRY_RUN=1 — email delivery will be skipped")

    # Import pipeline modules here so import errors surface as stage errors
    sys.path.insert(0, os.path.dirname(__file__))
    from gather import gather
    from analyze import analyze
    from render import render
    from send import send

    # Stage: gather
    try:
        logger.info("stage=gather starting")
        payload = gather(config)
        active_count = sum(1 for r in payload if r["has_activity"])
        logger.info("stage=gather done: %d repos, %d with activity", len(payload), active_count)
    except Exception as exc:
        logger.error("stage=gather failed: %s", exc)
        sys.exit(1)

    if not any(r["has_activity"] for r in payload):
        logger.info("stage=main all repos quiet — skipping email, exiting 0")
        sys.exit(0)

    # Stage: analyze
    try:
        logger.info("stage=analyze starting")
        editorial = analyze(payload, config)
        logger.info("stage=analyze done: %d chars", len(editorial))
    except Exception as exc:
        logger.error("stage=analyze failed: %s", exc)
        sys.exit(1)

    # Stage: render
    try:
        logger.info("stage=render starting")
        date_str = datetime.now(timezone.utc).strftime("%B %-d, %Y")
        html = render(editorial, date=date_str, payload=payload)
        logger.info("stage=render done: %d chars", len(html))
    except Exception as exc:
        logger.error("stage=render failed: %s", exc)
        sys.exit(1)

    # Write GitHub Pages archive (optional)
    if config.get("github_pages", {}).get("enabled", False):
        try:
            os.makedirs("docs", exist_ok=True)
            archive_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            archive_path = f"docs/{archive_date}.html"
            with open(archive_path, "w") as f:
                f.write(html)
            logger.info("stage=archive wrote %s", archive_path)
        except Exception as exc:
            logger.error("stage=archive failed: %s", exc)
            sys.exit(1)

    # Stage: send
    if dry_run:
        logger.info("stage=send DRY_RUN — printing HTML preview (first 500 chars)")
        print(html[:500])
        sys.exit(0)

    try:
        logger.info("stage=send starting")
        send(html, subscribers, config["sender_email"])
        logger.info("stage=send done")
    except Exception as exc:
        logger.error("stage=send failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
