# Updating the site on Google Cloud to the latest version

The site is already running on a Google Cloud (Compute Engine) VM. This guide brings it up to the latest code on GitHub without losing anyone's accounts, chats, reminders or saved AI keys.

A `git push` does **not** update the server by itself. Repeat these steps whenever new code is pushed. The VM does not need a reboot; only the app restarts.

**Time needed:** about 10 minutes (longer the first time, while you find out how the server is set up).

---

## Step 1: Open a terminal on the VM

Use either of these:
- **Browser:** Google Cloud Console → **Compute Engine → VM instances** → click **SSH** next to the VM.
- **Your laptop** (with the [gcloud CLI](https://cloud.google.com/sdk/docs/install)):
  ```bash
  gcloud compute ssh <INSTANCE_NAME> --zone <ZONE>
  ```

All commands below run **on the VM** unless they say otherwise.

## Step 2: Find out how this server runs the app (first time only)

Run these and write down the answers; later steps refer to them.

**a) Where is the project folder?**

```bash
sudo find / -path "*/backend/copilot.py" -not -path "*/node_modules/*" 2>/dev/null
```

The output is something like `/home/<user>/copilot/backend/copilot.py`, which makes the project folder `/home/<user>/copilot`. Go there and set a shortcut:

```bash
cd /home/<user>/copilot        # use the folder you found
export APP=$(pwd)
ls -l backend/.frontend-demo.sqlite3 deploy.env 2>/dev/null   # the live database and settings; note who owns them
```

If the files belong to another Linux user, switch to that user first (`sudo -iu <owner>`) and run every following step as them.

**b) How is the app started?**

```bash
systemctl list-units --type=service --all | grep -i -E "copilot|uvicorn"
ps aux | grep -i "uvicorn" | grep -v grep
```

| You see | It runs as | Restart method in Step 7 |
|---|---|---|
| A service such as `copilot.service` | a **systemd service** (recommended) | **A** |
| Only a `uvicorn backend.serve:app ...` process, no service | started by hand (in `tmux`, `screen` or with `nohup`) | **B** |
| Nothing from either command | the app is not running | start it with method **B**, then consider method A |

For a systemd service, this shows the exact command, folder, user and settings file it uses:

```bash
systemctl cat copilot     # use the service name you found
```

**c) How much memory does the VM have?**

```bash
free -h
```

The `total` column decides where you build the web app in Step 6. An `e2-micro` has about 1 GB; an `e2-small`, 2 GB.

## Step 3: Back up the database

Updates can add database columns automatically when the app starts. No data is lost, but keep a copy just in case:

```bash
cd $APP
cp backend/.frontend-demo.sqlite3 ~/copilot-backup-$(date +%Y%m%d-%H%M).sqlite3
```

## Step 4: Get the latest code

```bash
cd $APP
git status              # should say "nothing to commit, working tree clean"
git pull
git log --oneline -1    # the commit you are now on
```

- **Files listed as changed in `git status`:** run `git stash`, then `git pull`.
- **`Permission denied (publickey)`:** the VM's GitHub key is missing or was removed. Ask the repo owner to add the VM's public key (`cat ~/.ssh/id_ed25519.pub`) under **GitHub repo → Settings → Deploy keys**.
- **`detected dubious ownership`:** you are not the user who owns the folder. Switch to that user (Step 2a).

## Step 5: Update the backend dependencies

Use the same Python the app uses. That is normally `$APP/.venv`; for a systemd service, `systemctl cat` shows the path.

```bash
$APP/.venv/bin/pip install -r $APP/backend/requirements.txt
```

This is harmless when nothing changed.

## Step 6: Rebuild the web app

The site serves the built files in `frontend/dist`. Without a rebuild, it keeps showing the old pages. You can skip this step only when the update changed nothing under `frontend/`.

**VM with 2 GB of memory or more:** build on the VM.

```bash
cd $APP/frontend
npm ci
npm run build
cd $APP
```

**VM with about 1 GB (e2-micro):** `npm run build` usually runs out of memory there. Build on your laptop instead, then upload the result.

On your laptop, inside your own clone of the repo:

```bash
git pull
cd frontend
npm ci
npm run build
cd ..
gcloud compute scp --recurse frontend/dist <INSTANCE_NAME>:<APP_FOLDER>/frontend/ --zone <ZONE>
```

Replace `<APP_FOLDER>` with the folder from Step 2a, e.g. `/home/<user>/copilot`.

No gcloud CLI? Zip the folder instead (`frontend/dist` → `dist.zip`). In the browser SSH window, click **Upload file** (the gear or upload icon at the top right); the zip lands in your home folder. Then on the VM:

```bash
cd $APP/frontend
rm -rf dist
unzip ~/dist.zip -d .         # creates frontend/dist; install unzip with: sudo apt -y install unzip
ls dist/index.html            # must exist
```

## Step 7: Restart the app

**A. systemd service** (use the name from Step 2b):

```bash
sudo systemctl restart copilot
sudo systemctl status copilot --no-pager    # should say "active (running)"
curl -s http://127.0.0.1:8000/health        # should return {"status":"ok"...}
```

If it does not start, read the log: `journalctl -u copilot -n 50 --no-pager`.

**B. Started by hand:**

1. Stop the old process.
   - In its `tmux` or `screen` window, press `Ctrl+C`. (`tmux ls` / `screen -ls` lists sessions; `tmux attach -t <name>` / `screen -r <name>` reopens one.)
   - Otherwise, stop it directly:
     ```bash
     pkill -f "uvicorn backend.serve:app"
     ```
2. Start it again with the settings file, inside `tmux` so it keeps running after you close the window:
   ```bash
   cd $APP
   tmux new -s copilot
   set -a; . ./deploy.env; set +a
   .venv/bin/python -m uvicorn backend.serve:app --host 127.0.0.1 --port 8000
   ```
   Press `Ctrl+B`, then `D`, to leave it running.
3. Check it:
   ```bash
   curl -s http://127.0.0.1:8000/health
   ```

> Method B stops when the VM reboots. To have the app start by itself and restart after a crash, set it up as a systemd service once. Follow **Step 6** of `docs/DEPLOY_ORACLE_CLOUD_EN.md`; it works the same on Google Cloud. Replace `ubuntu` and `/home/ubuntu/copilot` with your user and folder from Step 2a.

**Keep the same `--host` and `--port` the site already used.** If it was `--host 127.0.0.1`, the site is published through Cloudflare Tunnel (or another proxy) and that keeps working without changes. `cloudflared` does **not** need a restart.

## Step 8: Check the site

Open the site in a browser and press **Ctrl+F5**, so it does not show a cached old page. Then check:

- [ ] You can sign in, and existing accounts, chats and reminders are still there.
- [ ] **Signed out**, every page opens and shows a green *Sign in to see data and use the AI assistant* box instead of data.
- [ ] **Reminders page** (signed in):
  - a *Suggested follow-ups* panel at the top;
  - a snooze button (⏰) on each reminder and a *Repeat* option;
  - *Export to calendar* downloads an `.ics` file.
- [ ] A bell icon at the top right shows a count when reminders are due.
- [ ] *Turn on desktop notifications* works. This needs the site to be opened over **https://**. Through a Cloudflare domain it is; through a plain `http://<external-IP>` address, browsers block notifications.

---

## Never touch these files

These are not in Git, so `git pull` leaves them alone. Do not delete, replace or commit them:

| File | What it is | If it is lost |
|---|---|---|
| `deploy.env` | Optional settings (Cloudflare Access) | The service's `EnvironmentFile=` line fails; recreate it from `deploy.env.example` |
| `backend/.ai-credentials.key` | Master key that encrypts everyone's saved AI keys | Nobody's saved AI key can be decrypted; everyone must re-enter their key |
| `backend/.frontend-demo.sqlite3` | The database: accounts, chats, reminders, action log | Every account and all user data is gone (restore from the Step 3 backup) |

Copy the last two to your laptop now and then:

```bash
gcloud compute scp <INSTANCE_NAME>:<APP_FOLDER>/backend/.frontend-demo.sqlite3 . --zone <ZONE>
gcloud compute scp <INSTANCE_NAME>:<APP_FOLDER>/backend/.ai-credentials.key . --zone <ZONE>
```

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| The site still looks old after the update | The web app was not rebuilt (Step 6), or the browser cached it: press Ctrl+F5 |
| New features show **Not Found** or **Method Not Allowed** | The old backend process is still running: restart it (Step 7) and check that only one `uvicorn` process exists (`ps aux \| grep uvicorn`) |
| Log says **frontend/dist is missing** | Build or upload the web app (Step 6) |
| Log says **Address already in use** | An old process still holds port 8000: `pkill -f "uvicorn backend.serve:app"`, then start again |
| `npm run build` prints **Killed** | Out of memory: build on your laptop (Step 6, 1 GB route) |
| Browser shows **502 Bad Gateway** | The app is not running: check Step 7 |
| Browser shows a Cloudflare **1033** error | `cloudflared` on the VM is not connected: `sudo systemctl status cloudflared` |
| Something broke after the update | Roll back: `cd $APP && git log --oneline -5`, then `git checkout <previous-commit>`; restore the backup with `cp ~/copilot-backup-<date>.sqlite3 backend/.frontend-demo.sqlite3`; rebuild and restart. Report the problem to the team |
