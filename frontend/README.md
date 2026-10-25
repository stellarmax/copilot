# Frontend development

The Vite proxy sends `/api` and `/health` to the local FastAPI server. Use the dedicated backend entry point below: it reads the Track 1 course dataset in `data/` (set `COPILOT_DATA_DIR=demo_data` to use the small demo set instead) and stores its claims/actions in a separate ignored SQLite file.

Terminal 1, from the repository root:

```powershell
.venv\Scripts\python.exe -m uvicorn backend.dev:app --host 127.0.0.1 --port 8000
```

Terminal 2, from the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. This development API has no authentication and must stay on localhost.