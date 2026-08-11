# Setup

This splits every third-party dependency into what you must do by hand
(account/credential creation — none of this can be scripted) and what the
bootstrap script does for you once those accounts exist.

Once you've generated the tokens below, you can paste them into `.env`
directly, **or** start the service and fill them in at
http://localhost:8000/ui/config instead — the form covers every field in
`.env.example` and writes straight to `.env` for you.

## 1. Manual steps (one-time, per provider)

### Confluence Cloud
Your POC space is already up: `SD` on `neurealm-team-juadifpx.atlassian.net`.

1. Generate an API token: https://id.atlassian.com/manage-profile/security/api-tokens
   → `CONFLUENCE_API_TOKEN` in `.env`. Use the Atlassian account email that
   generated it as `CONFLUENCE_USER_EMAIL`.
2. **Registering a real Confluence Cloud webhook is not part of this POC.**
   Atlassian doesn't publish a supported REST API for creating space/global
   webhooks with simple API-token auth (there's an internal, undocumented
   endpoint some tools use, but Atlassian explicitly does not support it and
   it can change without notice — not something to build a POC's plumbing
   on), and registering one in the UI would additionally require exposing
   this service to the public internet (tunnel, public IP, etc.), which this
   setup deliberately avoids. Instead: edit the spec page for real in
   Confluence's UI, then trigger the pipeline yourself from
   http://localhost:8000/ui/simulate (or `curl` — see step 3) with that
   page's ID. The pipeline still fetches the *real* current page content via
   the Confluence API either way; only the trigger is manual.
   `CONFLUENCE_WEBHOOK_SECRET` can stay blank for this POC as a result — the
   simulator signs its request when it's set, but there's no real inbound
   webhook to verify.

### GitHub (target repo the agent implements changes in)
1. Create a **classic PAT** (simplest for a POC — fine-grained tokens need
   per-repo setup in the UI with no reliable way to pre-fill via URL):
   https://github.com/settings/tokens/new?scopes=repo&description=confluence-pr-agent
   Scope needed: `repo` (read/write contents + open PRs).
   → `GITHUB_TOKEN` in `.env`.
2. Set `TARGET_REPO` in `.env` to the `owner/name` of the repo you want this
   agent to watch and open PRs against.
3. *(Production upgrade path, not needed for the POC)*: swap the PAT for a
   GitHub App installed on just the target repo(s), created via the
   [manifest flow](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest)
   — that flow *can* be scripted, unlike PAT creation.

### SendGrid (team notification email)
1. Sign up / log in at https://sendgrid.com (manual — email verification).
2. Verify a sender identity (single sender or domain) — required before
   SendGrid will deliver mail from `EMAIL_FROM_ADDRESS`.
3. Create an API key with **Mail Send** permission:
   https://app.sendgrid.com/settings/api_keys → `SENDGRID_API_KEY` in `.env`.
4. Set `EMAIL_FROM_ADDRESS` (must match a verified sender) and
   `EMAIL_TO_ADDRESSES` (comma-separated distribution list) in `.env`.

### Change engine (the code-writing backend — pick one)
Set `CHANGE_AGENT_ENGINE` in `.env` to whichever you have access to; only
that engine's credential is needed. Full detail: [docs/change-engines.md](docs/change-engines.md).

- **`claude_code`** (default): API key at
  https://console.anthropic.com/settings/keys → `ANTHROPIC_API_KEY`. CLI:
  `npm install -g @anthropic-ai/claude-code`.
- **`cursor`**: API key from your Cursor account settings →
  `CURSOR_API_KEY`. CLI: `curl https://cursor.com/install -fsS | bash`.
- **`copilot`**: reuses the `GITHUB_TOKEN` from the GitHub section above —
  no separate key. CLI: `npm install -g @github/copilot` (needs Node 22+
  and an active Copilot subscription on that token's account).

## 2. Automated steps

```bash
./scripts/bootstrap.sh
```

This creates a virtualenv, installs dependencies, copies `.env.example` to
`.env` if missing, and runs `scripts/check_credentials.py` — a read-only
sanity check that pings each provider's API with whatever you've put in
`.env` so far and reports which credentials are valid.

You can re-run the credential check any time after editing `.env`:

```bash
source .venv/bin/activate
python scripts/check_credentials.py
```

## 3. Running it for a POC demo

This runs containerized -- the container's own `CMD` starts the service on
container up, so there's no `uvicorn` command to run or keep alive
separately. Build with `--build-arg` set to whichever engine you configured
above, then run with `.env` both loaded (`--env-file`) and bind-mounted as a
real file (`-v .../.env:/app/.env`) so `/ui/config` edits actually persist:

```bash
podman build -f Containerfile -t confluence-pr-agent \
  --build-arg CHANGE_AGENT_ENGINE=claude_code .   # match CHANGE_AGENT_ENGINE in .env

podman run -d --name confluence-pr-agent \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  --env-file .env \
  -v "$(pwd)/data:/app/data:Z" \
  -v "$(pwd)/.env:/app/.env:Z" \
  confluence-pr-agent
```

(`podman-compose up -d --build` does the same thing if you have
`podman-compose` installed.) Confirm it's up: `curl http://localhost:8000/healthz`.

Edit the actual spec page in Confluence, then trigger a run one of two ways:

**UI (recommended):** open http://localhost:8000/ui/simulate, enter the
page's ID (from its Confluence URL) and hit send — it builds the payload,
signs it if needed, and shows you the result. Watch it land in
http://localhost:8000/ui/runs.

**curl:**
```bash
curl -X POST http://localhost:8000/webhook/confluence \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/confluence_webhook_payload.json
```
(Swap the `page.id` in that payload for the real page ID first.)

Either way, make sure `TARGET_REPO` points at a repo you're OK with the
agent opening a real PR against — see
[docs/demo-spec-template.md](docs/demo-spec-template.md) for a suggested
spec page + a v2 edit that produces a clean, demoable diff.

## 4. What happens on a failed run

If the change agent fails, or the target repo's test command
(`TARGET_REPO_TEST_COMMAND`, default `pytest`) fails, the pipeline stops
*before* committing/pushing/opening a PR, and the page-version store is left
unadvanced — the next webhook delivery (or a manual re-POST) will retry from
the same diff rather than silently treating it as processed.
