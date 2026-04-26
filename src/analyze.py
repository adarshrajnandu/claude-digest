"""
Analyze the DigestPayload with Claude and return editorial prose.

Reads model name from config.yaml. Supports MOCK_LLM=1 for local iteration
without burning API credits. Applies a 50k-token guard and validates the
response for completeness.
"""

import json
import logging
import os
from pathlib import Path

import anthropic

from gather import DigestPayload

logger = logging.getLogger(__name__)

TOKEN_BUDGET = 50_000
MIN_RESPONSE_CHARS = 100
MOCK_FIXTURE = "tests/fixtures/mock_analysis.txt"

SYSTEM_PROMPT = """You are writing a newsletter about the Claude/Anthropic ecosystem for a \
technical audience that builds with Claude. Write in a clear, editorial voice — not a \
summary, but commentary. What matters, why, and what it means for builders.

OUTPUT FORMAT — follow exactly:

1. For each repo with significant activity, start its section with the repo name on its \
own line in bold: **owner/repo** (e.g. **anthropics/claude-code**). Then write 2-4 \
sentences covering:
   - What changed (specific: releases, merged PRs, new issues)
   - Why it matters to someone building with Claude
   - One thing to watch

2. Separate repo sections with a blank line.

3. After all repo sections, add a horizontal rule on its own line: ---

4. Write a 1-paragraph section starting with **Signal of the week** — the single most \
interesting development across the entire ecosystem.

5. If the Hot Newcomers list is non-empty, add a section starting with **Catching fire** \
before the repo sections, listing each newcomer with a sentence on why it's interesting.

Do NOT include a title, heading, or "# Claude Ecosystem Digest" line — the email \
template provides the header. Do NOT use ## markdown headings. Use only **bold** for \
repo names and section labels. Do NOT use bullet points for repo commentary — write \
flowing prose sentences instead.

Only write about repos with significant activity (commits, closed issues, or releases). \
Skip repos with only open issues and no other activity.

If any repo has star_velocity > 100, mention it as a momentum signal. \
Suppress star velocity entirely when all values are 0 or None."""


def _count_tokens(client: anthropic.Anthropic, model: str, system: str, user_content: str) -> int:
    try:
        resp = client.messages.count_tokens(
            model=model,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        return resp.input_tokens
    except Exception as exc:
        logger.warning("stage=analyze token count API failed (%s), using char estimate", exc)
        return (len(system) + len(user_content)) // 4


def analyze(payload: DigestPayload, config: dict) -> str:
    if os.environ.get("MOCK_LLM") in ("1", "true"):
        logger.info("stage=analyze MOCK_LLM=1, returning fixture")
        return Path(MOCK_FIXTURE).read_text()

    model: str = config.get("model", "claude-sonnet-4-6")
    api_key = os.environ["ANTHROPIC_API_KEY"]

    active = [r for r in payload if r["has_activity"]]
    if not active:
        return ""

    # Build newcomers and velocity sections
    newcomers = [r["name"] for r in active if r.get("is_new_this_run")]
    newcomer_block = "\n".join(newcomers) if newcomers else "None this run."

    velocity_lines = [
        f"  {r['name']}: +{r['star_velocity']} stars"
        for r in active
        if r.get("star_velocity") is not None and (r.get("star_velocity") or 0) > 0
    ]
    velocity_block = (
        "STAR VELOCITY (stars gained since last digest run):\n" + "\n".join(velocity_lines)
        if velocity_lines
        else ""
    )

    # Strip star_velocity/is_new_this_run from the JSON (already surfaced above)
    repo_data = [
        {
            "name": r["name"],
            "stars": r["stars"],
            "description": r["description"],
            "commits": r["commits"],
            "issues": r["issues"],
            "releases": r["releases"],
        }
        for r in active
    ]

    user_content = f"""HOT NEWCOMERS (repos appearing in topic discovery for the first time):
{newcomer_block}

{velocity_block}

Raw data:
<untrusted_github_data>
{json.dumps(repo_data, indent=2)}
</untrusted_github_data>"""

    # Token guard: truncate payload if over budget
    try:
        client = anthropic.Anthropic(api_key=api_key)
    except anthropic.AuthenticationError as exc:
        raise RuntimeError(
            "stage=analyze Anthropic API key is invalid. "
            "Check console.anthropic.com/account/keys"
        ) from exc

    token_count = _count_tokens(client, model, SYSTEM_PROMPT, user_content)
    if token_count > TOKEN_BUDGET:
        logger.warning(
            "stage=analyze payload ~%d tokens exceeds %d budget, truncating repo list",
            token_count,
            TOKEN_BUDGET,
        )
        # Truncate: drop repos from the end until we're under budget
        while len(repo_data) > 1 and token_count > TOKEN_BUDGET:
            repo_data = repo_data[:-1]
            user_content = _rebuild_user_content(newcomer_block, velocity_lines, repo_data, velocity_block)
            token_count = _count_tokens(client, model, SYSTEM_PROMPT, user_content)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
    except anthropic.AuthenticationError as exc:
        raise RuntimeError(
            "stage=analyze Anthropic API key is invalid. "
            "Check console.anthropic.com/account/keys"
        ) from exc

    if response.stop_reason == "max_tokens":
        raise ValueError(
            "stage=analyze Claude response was truncated (finish_reason=max_tokens). "
            "The output is incomplete — aborting to avoid sending partial content."
        )

    text = response.content[0].text if response.content else ""

    if len(text.strip()) < MIN_RESPONSE_CHARS:
        raise ValueError(
            f"stage=analyze Claude returned an unexpectedly short response ({len(text.strip())} chars). "
            "Aborting to avoid sending empty or malformed content."
        )

    return text


def _rebuild_user_content(newcomer_block: str, velocity_lines: list, repo_data: list, velocity_block: str) -> str:
    return f"""HOT NEWCOMERS (repos appearing in topic discovery for the first time):
{newcomer_block}

{velocity_block}

Raw data:
<untrusted_github_data>
{json.dumps(repo_data, indent=2)}
</untrusted_github_data>"""
