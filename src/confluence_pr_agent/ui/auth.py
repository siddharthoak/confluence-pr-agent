"""Identity for the multi-tenant UI: who is this request for?

Caddy is the only way to reach this app at all (see podman-compose.yml --
no host port is published for the app service), and Caddy's own basic_auth
sets {http.auth.user.id} on a successful login, forwarded as the
X-Auth-User header (see Caddyfile.example's reverse_proxy block). Trusting
that header is only safe because of the topology, not anything this app
enforces on its own -- X-Internal-Secret is the second, cheap layer: Caddy
sets it from INTERNAL_SHARED_SECRET (an env var shared with the app, see
podman-compose.yml), and this dependency rejects any request that doesn't
have it. That way, a future third container someone adds to the same
compose network can't reach the app and forge X-Auth-User directly, even
though it technically could reach the internal port.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from confluence_pr_agent.config import get_process_config


def current_username(request: Request) -> str:
    process = get_process_config()

    # Skipped when unconfigured -- same idiom as CONFLUENCE_WEBHOOK_SECRET
    # verification (webhook/app.py::_verify_signature): fine for local
    # `uvicorn --reload` dev with no Caddy in front at all, since there'd be
    # nothing to ever set this header in that case. Once INTERNAL_SHARED_
    # SECRET is set (podman-compose.yml's public profile always sets it),
    # the check is real.
    if process.internal_shared_secret:
        if request.headers.get("X-Internal-Secret") != process.internal_shared_secret:
            raise HTTPException(status_code=401, detail="missing/invalid internal secret -- must be accessed through Caddy")

    username = request.headers.get("X-Auth-User") or process.default_user.strip()
    if not username:
        raise HTTPException(status_code=401, detail="no authenticated user")

    # Also stashed on request.state so templates (base.html's nav) can show
    # who's logged in without every single route handler needing to thread
    # a `username` key into its own Jinja2Templates context dict.
    request.state.username = username
    return username
