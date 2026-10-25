# The General Manager's Co-Pilot

DSS5105 Capstone · Track 1 · Group 16

An operations assistant for the general manager of SweaterCo, a sweater factory. The manager asks about orders, production output, delivery risk and new-order feasibility in plain English. An AI agent picks from a small set of approved tools, a deterministic Python core calculates every number, and every conclusion links to evidence that can be re-verified. Write actions (order notes, reminders, chase-up drafts) are only prepared by the AI; nothing is saved until the user clicks **Confirm**.

**Design principle:** the LLM interprets, deterministic tools calculate, and every claim is traceable.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI API, deterministic core (`copilot.py`), AI agent (`app/agent/`), tests |
| `frontend/` | React + TypeScript + Vite web app |
| `data/` | Course-provided dataset (orders, production log, workshops); the app's default data |
| `demo_data/` | Small fixture dataset used by the automated tests |
| `evaluation/` | 36-question evaluation set, independent answer key, runner and failure analysis (run logs are generated locally) |
| `docs/` | Local setup guides (EN/ZH) and deployment guide (Cloudflare Tunnel + Access) |
| `scripts/` | Production start script |

## Run locally (development)

Requires Python 3.11+ and Node.js 20+. Full step-by-step instructions for Windows and macOS: [docs/Team_Local_Setup_EN.md](docs/Team_Local_Setup_EN.md) (Chinese: [_ZH](docs/Team_Local_Setup_ZH.md)).

```powershell
# Backend (window 1)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.dev:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend

# Web app (window 2)
cd frontend
npm ci
npm run dev
```

Open <http://127.0.0.1:5173>. To use the AI chat, add your own API key under **AI settings**. It is stored encrypted in a local, git-ignored database.

## Tests and evaluation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend -p "test_*.py" -t .   # backend
cd frontend; npm test                                                           # frontend
.\.venv\Scripts\python.exe -m unittest evaluation.test_grader                   # grader controls
.\.venv\Scripts\python.exe -m evaluation.run_eval --set dev                     # live AI evaluation (uses your API key)
```

Results and the failure analysis are in `evaluation/EVALUATION_REPORT.md`.

## Deploy on your own domain

The app runs on one computer and is published through **Cloudflare Tunnel**. **Cloudflare Access** restricts it to listed e-mail addresses, and the production server refuses requests without a valid Access login. See `docs/DEPLOY_CLOUDFLARE_ZH.md`.

## Never committed

API keys, the encryption key (`backend/.ai-credentials.key`), local databases (`*.sqlite3`), `deploy.env`, `node_modules/`, `.venv/` and build output are git-ignored. Every user keeps their own.
