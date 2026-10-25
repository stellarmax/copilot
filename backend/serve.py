"""Production entry point: one process serves the built web app and the API.

Used behind a Cloudflare Tunnel. It refuses to start unless Cloudflare Access is configured, so the
app (and the AI key stored in it) is never reachable from the internet without a login.

    CF_ACCESS_TEAM_DOMAIN=yourteam.cloudflareaccess.com
    CF_ACCESS_AUD=<Application Audience (AUD) tag>
    python -m uvicorn backend.serve:app --host 127.0.0.1 --port 8000
"""

import os

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.access import AccessVerifier, CloudflareAccessMiddleware
from backend.copilot import PROJECT_ROOT
from backend.dev import app

DIST = PROJECT_ROOT / "frontend" / "dist"

if not (DIST / "index.html").exists():
    raise RuntimeError("frontend/dist is missing. Build the web app first: cd frontend; npm run build")

team_domain = os.getenv("CF_ACCESS_TEAM_DOMAIN", "")
audience = os.getenv("CF_ACCESS_AUD", "")
if not team_domain or not audience:
    raise RuntimeError(
        "Set CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD (see docs/DEPLOY_CLOUDFLARE_ZH.md). "
        "The public deployment will not start without Cloudflare Access."
    )
app.add_middleware(CloudflareAccessMiddleware, verifier=AccessVerifier(team_domain, audience))
app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def web_app(path: str) -> FileResponse:
    """Serve built files, and index.html for client-side routes such as /chat or /reminders."""
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    candidate = (DIST / path).resolve()
    if path and candidate.is_file() and DIST.resolve() in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(DIST / "index.html")
