"""Production entry point: one process serves the built web app and the API.

Anyone can create an account (backend/app/auth.py); each account uses its own AI key, and the factory
data is read-only. Cloudflare Access can be added in front as an optional gate by setting
CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD.

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
if team_domain and audience:
    app.add_middleware(CloudflareAccessMiddleware, verifier=AccessVerifier(team_domain, audience))

# The interactive API docs are for local development only; do not publish them through the tunnel.
DOC_PATHS = {app.docs_url, app.redoc_url, app.openapi_url, app.swagger_ui_oauth2_redirect_url}
app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) not in DOC_PATHS]
app.docs_url = app.redoc_url = app.openapi_url = None

app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def web_app(path: str) -> FileResponse:
    """Serve built files, and index.html for client-side routes such as /chat or /reminders."""
    if path.startswith("api/") or "/" + path in DOC_PATHS:
        raise HTTPException(status_code=404, detail="Not Found")
    candidate = (DIST / path).resolve()
    if path and candidate.is_file() and DIST.resolve() in candidate.parents:
        return FileResponse(candidate)
    return FileResponse(DIST / "index.html")
