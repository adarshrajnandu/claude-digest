# TODOS — claude-digest

Deferred from /autoplan review (2026-04-26). Items below are out-of-scope for v1 but worth building later.

## Phase 2 — Distribution & Scale

- [ ] **Hosted service** — single URL signup, zero-setup subscription. Currently requires clone + 4 secrets. Removes the adoption friction the CEO review flagged.
- [ ] **Event-driven delivery** — webhook-triggered on release/commit, not 3-day batch cron. Real-time signal when something ships.
- [ ] **Anthropic changelog RSS source** — add non-GitHub source to catch model updates, pricing changes, system prompt changes that have zero GitHub footprint.
- [ ] **Slack/Discord webhook delivery** — natural phase 2 once email version is stable.
- [ ] **README auto-link to latest digest** — requires idempotent regex rewrite of README on every run.
- [ ] **Subscriber management** — opening a GitHub Issue to subscribe. Requires issue-triggered workflow.

## Phase 3 — Intelligence

- [ ] **Differentiation guide** — editorial voice positioning vs Anthropic's own newsletter. When Anthropic launches their developer newsletter (they will), the editorial voice needs to be distinctly non-corporate and community-focused.
- [ ] **Star velocity rolling trend** — currently a single run-delta. Rolling 7-day average would be a stronger signal.
- [ ] **HN/Reddit signal sources** — Claude-tagged posts as a supplementary source.

## Validation

- [ ] **Demand validation** — before building hosted service, send 5 manually-written digests to target readers. Measure open rate + reply rate. The CEO subagent flagged this as unvalidated for a product (less critical for personal utility, but worth testing before investing in hosted infra).
