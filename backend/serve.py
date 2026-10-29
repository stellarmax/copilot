"""Production entry point: one process serves the built web app and the API.

Users sign in with their own accounts (backend/app/auth.py), and registration needs an invite code,
so the server refuses to start without COPILOT_INVITE_CODE. Cloudflare Access can be added in front
as an optional second gate by also setting CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD.

    COPILOT_INVITE_CODE=<share only with your team>
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

if len(os.getenv("COPILOT_INVITE_CODE", "")) < 8:
    raise RuntimeError(
        "Set COPILOT_INVITE_CODE (at least 8 characters) before deploying; only people with the code can "
        "create an account. See docs/DEPLOY_CLOUDFLARE_ZH.md."
    )

team_domain = os.getenv("CF_ACCESS_TEAM_DOMAIN", "")
audience = os.getenv("CF_ACCESS_AUD", "")
if team_domain and audience:
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
