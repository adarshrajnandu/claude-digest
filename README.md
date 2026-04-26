# claude-digest

A curated, editorial email digest for the Claude/Anthropic ecosystem — delivered every 3 days, written by Claude, covering commits, releases, issues, and new community repos.

**GitHub activity only** — commits, issues, releases, and new repos. Not a social feed.

## What it does

Two data tracks:
1. **Watchlist** — repos you care about, always included (anthropics/claude-code, SDKs, MCP spec)
2. **Topic discovery** — GitHub search for `claude`, `claude-code`, `anthropic`, `mcp` topics. Catches community repos before they trend.

Claude Sonnet analyzes the combined activity and writes editorial commentary — not a summary, but "what matters and why." Delivered via Resend email on a 3-day GitHub Actions cron.

**Cost**: ~$0.23/month at current pricing.

---

## Prerequisites

You need accounts and access set up before the pipeline can run:

1. **GitHub account** with a repo to host this (public recommended for free Actions minutes)
2. **GitHub fine-grained Personal Access Token** — no special scopes needed for public repos. Generate at [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new). Raises rate limit from 60 to 5,000 req/hour.
3. **Anthropic API key** with credits. Get at [console.anthropic.com/account/keys](https://console.anthropic.com/account/keys). ~$0.023/run.
4. **Resend account** (free tier: 100 emails/day). Requires a **domain you control** — you must verify a custom domain at [resend.com/domains](https://resend.com/domains). Gmail, Outlook, and other personal addresses cannot be used as the sender.

---

## Quickstart

```bash
git clone https://github.com/yourusername/claude-digest.git
cd claude-digest
pip install -r requirements.txt
```

1. **Configure**: Copy `config.yaml.example` to `config.yaml`. Set `sender_email` to an address on your verified Resend domain.

2. **Add GitHub Secrets** in your repo's Settings → Secrets → Actions:
   - `GITHUB_PAT` — your fine-grained token
   - `ANTHROPIC_API_KEY` — your Anthropic key
   - `RESEND_API_KEY` — your Resend key
   - `SUBSCRIBER_EMAILS` — comma-separated recipient addresses (e.g. `you@gmail.com,friend@gmail.com`)

3. **Test locally** (see Local Development below), then push.

4. **Trigger the first run**: In your repo, go to Actions → Claude Ecosystem Digest → Run workflow. Enable `dry_run` to verify the HTML output before sending.

---

## Local Development

Run the full pipeline locally with a `.env` file:

```bash
cp .env.example .env
# Fill in your secrets in .env
```

**Cost-free iteration** (no API calls):
```bash
source .env
MOCK_LLM=1 DRY_RUN=1 python src/main.py
```

This uses `tests/fixtures/mock_analysis.txt` as the editorial output and prints the rendered HTML without sending email.

**Dry run with real Claude** (renders + skips send):
```bash
source .env
DRY_RUN=1 python src/main.py
```

**Full run** (sends actual email):
```bash
source .env
python src/main.py
```

### Resend domain setup

1. Sign up at [resend.com](https://resend.com)
2. Go to Domains → Add Domain → enter your domain
3. Add the displayed DNS records (MX, TXT, CNAME) to your domain registrar
4. Click Verify — DNS propagation takes up to **48 hours**

Once verified, set `sender_email` in `config.yaml` to any address at that domain (e.g. `digest@yourdomain.com`).

To check: `resend.com/domains` will show status "Verified" when ready.

---

## Model upgrade

The Claude model is configured in `config.yaml`:

```yaml
model: claude-sonnet-4-6
```

To upgrade, change this value — no Python edits needed. See available models at [console.anthropic.com/docs/models](https://console.anthropic.com/docs/models).

---

## GitHub Pages archive (optional)

Each digest can be saved as a permanent HTML page. To enable:

1. In your repo: Settings → Pages → Source: "Deploy from a branch" → Branch: main, Folder: `/docs`
2. In `config.yaml`: set `github_pages.enabled: true`

Digests will be published to `https://yourusername.github.io/claude-digest/YYYY-MM-DD.html` after each run. Pages typically update 30–60 seconds after the commit is pushed.

---

## Known Limitations

**60-day inactivity disable**: GitHub Actions automatically disables scheduled workflows after 60 days of no repository activity. The `[skip ci]` commits from the state file don't count. To keep the pipeline active, make any commit to the repo (update a watchlist entry, edit the README). GitHub sends an email warning before disabling.

**Cron month-end gap**: The explicit day list `1,4,7,...,28` means the gap from day 28 to day 1 of the next month is 4 days (instead of 3). This is intentional — `*/3` resets monthly and creates unpredictable behavior. The 1-day extra gap at month-end is acceptable.

**First-run behavior**: The state file is empty on first run, so `is_new_this_run=True` for all repos and `star_velocity=0` for all. The digest will note everything as new/no prior velocity data. This normalizes after the second run.

---

## Running tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## Sharing

This repo is designed to be cloneable. Friends can fork or clone it, add their own 4 secrets, update `config.yaml` with their email, and get their own digest. No hosted service, no accounts beyond the 4 listed in Prerequisites.
