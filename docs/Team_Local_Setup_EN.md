# Local Setup Guide for Teammates (with AI Chat)

This guide takes you from a fresh **Windows** or **macOS** computer to a running copy of the Fieldwork Operations Co-Pilot demo, including the AI chat. For the Chinese version, see [Team_Local_Setup_ZH.md](Team_Local_Setup_ZH.md).

There are three stages: **install the tools (once) → install the project dependencies (once) → start the app (every time)**. The first run takes about 15–20 minutes and needs an internet connection.

## 0. Get the project

Clone the private GitHub repository (the owner must invite you first), or unzip the package shared by the team. Either way you get one project folder, called the **project folder** below:

```bash
git clone https://github.com/stellarmax/copilot.git
```

| Folder | Contents |
|---|---|
| `backend/` | Backend: Python + FastAPI, with the business logic, AI agent and API |
| `frontend/` | Web app: React + TypeScript + Vite |
| `data/` | The **course-provided data** (120 orders, a 90-day production log, 8 outside workshops). The web app and AI read it, so **keep it** |
| `docs/` | This guide and the deployment guide |

> Neither the repository nor the package contains API keys, databases or chat history. Everyone sets up the AI with **their own** API key (step 4).

---

## 1. Install the tools (once)

You need **Python 3.11 or later** and **Node.js 20 or later**.

### Windows

1. **Python:** download the latest Python 3 (3.11 or later) from <https://www.python.org/downloads/>.
   - On the first installer screen, **tick "Add python.exe to PATH"**, then click *Install Now*.
2. **Node.js:** download the **LTS** version from <https://nodejs.org/> and install it with the default options.
3. **Close every PowerShell window and open a new one**, then check the versions:
   ```powershell
   py --version      # should show Python 3.11.x or later
   node --version    # should show v20.x or later
   npm --version
   ```
   If `py` is not recognized, try `python --version` instead. If that shows 3.11 or later, replace `py -3` with `python` in the next step.

> To open PowerShell, press the `Win` key, type `PowerShell` and press Enter.

### macOS

1. **Python:** download the latest Python 3 installer (3.11 or later) from <https://www.python.org/downloads/macos/> and run it.
   - When it finishes, double-click **Install Certificates.command** in the Python folder that opens. This prevents SSL errors when downloading dependencies later.
   - ⚠️ The `python3` that ships with macOS is usually 3.9, which is too old. **Don't use it.**
2. **Node.js:** download the **LTS** macOS installer from <https://nodejs.org/> and run it.
3. Open a **new** Terminal window and check the versions:
   ```bash
   python3.12 --version   # use the version you installed, e.g. python3.11 / python3.12 / python3.13
   node --version          # should show v20.x or later
   npm --version
   ```

> To open Terminal, press `Cmd + Space`, type `Terminal` and press Enter.
> If you use Homebrew, `brew install python@3.12 node` also works.

---

## 2. Install the project dependencies (once)

Clone or unzip the project to a path with **no spaces or non-English characters**. The commands below use the package's folder name; a clone is called `copilot`, so use your own path. For example:
- Windows: `C:\projects\General-Manager-Co-Pilot-AI-Demo`
- macOS: `~/projects/General-Manager-Co-Pilot-AI-Demo`

> Spaces or non-English characters in the path sometimes break commands, so avoid them.

### Windows (PowerShell)

```powershell
# Go to the project folder (use your own path)
cd C:\projects\General-Manager-Co-Pilot-AI-Demo

# 1) Create a Python virtual environment and install the backend dependencies
#    (if py is not recognized, use this line instead: python -m venv .venv)
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 2) Install the web app dependencies
cd frontend
npm ci
cd ..
```

### macOS (Terminal)

```bash
# Go to the project folder (use your own path)
cd ~/projects/General-Manager-Co-Pilot-AI-Demo

# 1) Create a Python virtual environment and install the backend dependencies
#    (replace python3.12 with the version you installed)
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

# 2) Install the web app dependencies
cd frontend
npm ci
cd ..
```

When you see `Successfully installed ...` and `added ... packages`, you're done. You can ignore `warn` and `vulnerabilities` messages from `npm`.

---

## 3. Start the app (every time)

You need **two terminal windows open at the same time**. **Keep both running.**

| Window | Runs | Port |
|---|---|---|
| Window 1 | Backend | 8000 |
| Window 2 | Web app | 5173 |

### Windows

**Window 1: backend**
```powershell
cd C:\projects\General-Manager-Co-Pilot-AI-Demo
.\.venv\Scripts\python.exe -m uvicorn backend.dev:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend
```

**Window 2: web app** (open a second PowerShell window)
```powershell
cd C:\projects\General-Manager-Co-Pilot-AI-Demo\frontend
npm run dev
```

### macOS

**Window 1: backend**
```bash
cd ~/projects/General-Manager-Co-Pilot-AI-Demo
source .venv/bin/activate
python -m uvicorn backend.dev:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend
```

**Window 2: web app** (press `Cmd + T` for a new tab)
```bash
cd ~/projects/General-Manager-Co-Pilot-AI-Demo/frontend
npm run dev
```

### Check that it started

- Window 1 shows `Application startup complete.`
- Window 2 shows `Local: http://127.0.0.1:5173/`

Then open these in your browser:

| Address | Purpose |
|---|---|
| <http://127.0.0.1:5173> | **Main web app** |
| <http://127.0.0.1:8000/health> | Backend health check; `{"status":"ok"}` means it's working |
| <http://127.0.0.1:8000/docs> | Backend API docs |

When the top-right corner of the web app shows **API connected**, the web app and backend are talking to each other.

### Stopping

Press `Ctrl + C` in both windows. Next time, just repeat step 3; you don't need to reinstall anything.

---

## 4. Set up the AI chat (the first time you use AI)

The Orders, Production, Feasibility and other pages work without AI. The AI chat needs an API key from a model provider.

1. Get an API key from any one of these providers. Most require you to sign up and add a small amount of credit.

   | Provider | Get a key at |
   |---|---|
   | ChatGPT (OpenAI) | <https://platform.openai.com/api-keys> |
   | Claude (Anthropic) | <https://console.anthropic.com/settings/keys> |
   | Gemini (Google) | <https://aistudio.google.com/apikey> |
   | DeepSeek | <https://platform.deepseek.com/api_keys> |

2. In the web app, click **AI settings** in the left sidebar.
3. Choose the **AI provider**, then a **Model**. Each provider's first model is the recommended default.
4. Paste your key into **API key** and click **Save settings**.
5. Click **Test connection**. *AI provider connection succeeded.* means it works.
6. Go back to **Overview** and type a question in the *Ask operations* box, or click one of the example questions.

About your API key:
- It stays on your own computer and is stored **encrypted**. The backend creates the encryption master key the first time it starts and keeps it in `backend/.ai-credentials.key`.
- **Never** send `backend/.ai-credentials.key` or `backend/*.sqlite3` to anyone or commit them to Git.
- Every question calls the provider's API and **costs a small amount of money**.

---

## 5. Troubleshooting

**Q1: On Windows, `npm` fails with "npm.ps1 cannot be loaded because running scripts is disabled on this system".**
This is a PowerShell security setting. Either:
- Use `npm.cmd` instead of `npm`, for example `npm.cmd ci` and `npm.cmd run dev`; or
- Run this once (it affects only your user account), then reopen PowerShell:
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```

**Q2: On Windows, `py` is not recognized.**
Some computers don't have the `py` launcher. Try `python --version`:
- If it shows 3.11 or later, create the virtual environment with `python -m venv .venv` instead. Every later command starts with `.\.venv\Scripts\python.exe`, so nothing else changes.
- If `python` isn't recognized either, or it opens the Microsoft Store, Python was installed without "Add python.exe to PATH". Run the Python installer again, choose *Modify*, and tick *py launcher* and *Add Python to environment variables*. Or uninstall and reinstall with "Add python.exe to PATH" ticked.

**Q3: On macOS, `python3.12: command not found`.**
Replace the version number with the one you installed, such as `python3.11` or `python3.13`. Type `python3.` in Terminal and press `Tab` twice to list the installed versions.

**Q4: Starting the backend says `No module named uvicorn`.**
You're not using the Python in the project's virtual environment. On Windows, start the command with `.\.venv\Scripts\python.exe`. On macOS, run `source .venv/bin/activate` in every new window; the prompt then starts with `(.venv)`. If it still fails, run the `pip install` command from step 2 again.

**Q5: `pip install` is slow or fails with a network or SSL error.**
- On macOS, make sure you ran *Install Certificates.command* from step 1.
- Check your internet connection or proxy, then try again.

**Q6: `npm ci` is slow or fails.**
Check your internet connection or proxy, then run `npm ci` again. If it still fails, delete the `frontend/node_modules` folder (if it exists) and retry.

**Q7: Port 8000 or 5173 is already in use (`address already in use` / `Port 5173 is in use`).**
An earlier copy of the app is still running. Close the old terminal windows first. If you can't find them:
- Windows: run `Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess` to get the process ID, then end that process on the *Details* tab of Task Manager.
- macOS: run `lsof -i :8000` to get the PID, then `kill <PID>`.

**Q8: The top-right corner says "API offline".**
The backend isn't running. Check Window 1 for errors or whether it was closed, then open <http://127.0.0.1:8000/health> to confirm.

**Q9: The AI chat says "AI is not configured".**
No API key is saved yet. Follow step 4.

**Q10: Test connection says the key was rejected, or shows an HTTP error.**
- **Key rejected:** the key was copied wrong, or it doesn't match the provider you chose (for example, an OpenAI key with Claude selected).
- **429:** too many requests or not enough credit. Check your balance on the provider's site.
- **400 / 404:** your account may not have access to that model. Try another model.

**Q11: I want to clear all demo records and start fresh.**
Stop the backend, delete `backend/.frontend-demo.sqlite3`, and start the backend again. This clears action records, chats, AI settings and memories, so you'll need to enter your API key again.

**Q12: Can teammates open the app on my computer over the LAN?**
No. The project has no login, and the AI settings and chat endpoints accept local requests only. Everyone should run their own copy.
---

## 6. Notes

- The app uses the **course-provided data** in `data/`, with the business date fixed at 2026-04-01.
- All services listen only on this computer (`127.0.0.1`). Do not expose them to a LAN or the internet.
- "Actions" are only recorded in the local database. They **never** send messages, create reminders or start watches.
- The AI can only call read-only tools, and the backend calculates every number. Click **Evidence** at the end of an answer to see how a result was calculated.
