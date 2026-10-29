# Deploying to Oracle Cloud (Always Free) + Cloudflare Tunnel

This guide picks up **after you have created an Oracle Cloud account**. At the end the app runs 24/7 on a free Oracle VM and is reachable at `https://copilot.<our-domain>`. Everyone signs in with their own account and uses their own AI key.

```text
Browser ──https──▶ Cloudflare ──Tunnel (outbound from the VM)──▶ Oracle VM: cloudflared → http://127.0.0.1:8000 (uvicorn: API + web app)
```

The VM never needs open inbound ports: `cloudflared` makes an outbound connection to Cloudflare. That means you don't have to edit Oracle security lists or the Ubuntu firewall.

**Before you start, you need:**
- an SSH client (`ssh` in Windows PowerShell or the macOS Terminal);
- read access to the GitHub repo `stellarmax/copilot`, with the version that includes accounts (it contains `backend/app/auth.py`);
- access to the Cloudflare account that manages our domain, or someone who can do Step 6 for you;
- an invite code for the site, at least 8 characters, agreed with the team.

---

## Step 1: Create the VM

1. In the Oracle Cloud console, open **☰ → Compute → Instances → Create instance**.
2. **Name:** `copilot`.
3. **Image:** click *Change image* and pick **Canonical Ubuntu 24.04**.
4. **Shape:** click *Change shape → Ampere → VM.Standard.A1.Flex*, with **1 OCPU and 6 GB memory**. This is inside the Always Free allowance, which is up to 4 OCPU and 24 GB in total.
   - If you get **"Out of capacity"**, try another *Availability domain* on the same page, or retry later. Always Free Ampere capacity is limited.
   - The fallback is `VM.Standard.E2.1.Micro` (AMD, 1 GB RAM), which is also free. It is very tight on memory, so if you use it, follow the swap tip in Step 3.
5. **Networking:** keep the default new VCN and public subnet, and keep *Assign a public IPv4 address* switched on. We only need it for SSH.
6. **SSH keys:** choose *Generate a key pair for me* and **download the private key** (for example `ssh-key-copilot.key`). Store it safely. Without it you cannot log in.
7. Click **Create**. When the state is **Running**, copy the **Public IP address**.

> The Always Free Ampere shape is only available in your **home region**, the one you chose at sign-up.

## Step 2: Log in over SSH

Windows PowerShell:

```powershell
icacls .\ssh-key-copilot.key /inheritance:r /grant:r "$($env:USERNAME):R"
ssh -i .\ssh-key-copilot.key ubuntu@<PUBLIC_IP>
```

macOS:

```bash
chmod 600 ~/Downloads/ssh-key-copilot.key
ssh -i ~/Downloads/ssh-key-copilot.key ubuntu@<PUBLIC_IP>
```

From here on, every command runs **on the VM**.

## Step 3: Install the tools

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install git python3-venv python3-pip build-essential
# Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt -y install nodejs
python3 --version   # needs 3.11 or newer (Ubuntu 24.04 ships 3.12)
node --version      # needs v20 or newer
```

**Only on the 1 GB Micro VM:** add swap so that `npm run build` doesn't run out of memory:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## Step 4: Get the code

The repo is private, so the VM needs its own read-only key:

```bash
ssh-keygen -t ed25519 -C "copilot-vm" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Send the printed line to the repo owner. They add it under **GitHub repo → Settings → Deploy keys → Add deploy key**, with *Allow write access* left **unchecked**. Then:

```bash
cd ~
git clone git@github.com:stellarmax/copilot.git
cd copilot
ls backend/app/auth.py    # must exist; if not, the account system has not been pushed yet, so stop and ask
```

## Step 5: Install, build and configure

```bash
cd ~/copilot
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r backend/requirements.txt

cd frontend
npm ci
npm run build          # creates frontend/dist
cd ..

cp deploy.env.example deploy.env
nano deploy.env        # set COPILOT_INVITE_CODE=<the team's code>; leave both CF_ACCESS_* lines empty
chmod 600 deploy.env
```

Quick test. Leave it running for a few seconds, then stop it with `Ctrl+C`:

```bash
set -a; . ./deploy.env; set +a
.venv/bin/python -m uvicorn backend.serve:app --host 127.0.0.1 --port 8000
# in a second SSH window:  curl -s http://127.0.0.1:8000/health   → {"status":"ok"...}
```

The first start creates `backend/.ai-credentials.key`, the master key that encrypts everyone's saved AI keys, and `backend/.frontend-demo.sqlite3`. Neither file is in git. **Never commit, share or delete them** (see Step 9).

## Step 6: Run it as a service (auto-start, auto-restart)

```bash
sudo tee /etc/systemd/system/copilot.service > /dev/null <<'EOF'
[Unit]
Description=GM Co-Pilot
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/copilot
EnvironmentFile=/home/ubuntu/copilot/deploy.env
ExecStart=/home/ubuntu/copilot/.venv/bin/python -m uvicorn backend.serve:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now copilot
sudo systemctl status copilot --no-pager      # should say "active (running)"
curl -s http://127.0.0.1:8000/health
```

To read the logs: `journalctl -u copilot -f`.

Keep `--host 127.0.0.1`. The app must only be reachable through the tunnel, never directly on the public IP.

## Step 7: Connect the domain with Cloudflare Tunnel

Do this in the Cloudflare dashboard of the account that owns our domain. If you don't have access, ask for the tunnel token.

1. Open **Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared**, and name it `copilot-oracle`.
2. Under *Choose your environment*, pick **Debian** and **arm64**. On the Micro VM, pick **64-bit**.
3. The page shows install commands. Run them **on the VM**. The last one looks like:
   ```bash
   sudo cloudflared service install eyJhIjoi...
   ```
   Wait until the connector shows **Connected**, then click **Next**.
4. Add a **Public hostname**:
   - **Subdomain:** `copilot`. Use a subdomain that **no other project already uses**, because another subdomain on our domain is already in use.
   - **Domain:** our domain.
   - **Service:** `HTTP` → `localhost:8000`.
5. Save. Cloudflare creates the DNS record automatically.

## Step 8: Check that it works

From your phone on mobile data:
1. Open `https://copilot.<our-domain>`. The **Sign in** page should appear.
2. **Create an account** without the invite code or with a wrong one. It must be refused.
3. Register with the correct invite code, then open **AI settings**, add **your own** API key, and click **Test connection**.
4. Register a second test account. It must **not** see the first account's key status, chats, reminders or action log.
5. Share the URL and the invite code with the team. Each person registers and adds their own key.

## Step 9: Keep it running

**Deploying a new version:**

```bash
cd ~/copilot
git pull
.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)
sudo systemctl restart copilot
```

**Backups:** copy these two files somewhere safe, for example from your laptop:

```bash
scp -i ssh-key-copilot.key ubuntu@<PUBLIC_IP>:copilot/backend/.frontend-demo.sqlite3 .
scp -i ssh-key-copilot.key ubuntu@<PUBLIC_IP>:copilot/backend/.ai-credentials.key .
```

If `.ai-credentials.key` is lost, saved AI keys can't be decrypted and everyone has to re-enter their key. Accounts and chats stay.

**Idle reclamation:** Oracle may stop Always Free VMs that stay almost idle (very low CPU, network and memory use over 7 days). If the site suddenly disappears, check the instance state in the console and start it again. Upgrading the account to *Pay As You Go* removes this rule, and Always Free resources stay free.

**Changing the invite code:** edit `deploy.env`, then run `sudo systemctl restart copilot`. Existing accounts keep working.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `copilot.service` fails, log says **frontend/dist is missing** | Run `cd frontend && npm ci && npm run build`, then restart. |
| Log says **Set COPILOT_INVITE_CODE** | `deploy.env` is missing the code, or the code is shorter than 8 characters. |
| Browser shows **502 Bad Gateway** | The tunnel is up but the app isn't running. Check `sudo systemctl status copilot`. |
| Browser shows a Cloudflare **1033** error | `cloudflared` on the VM is not connected. Check `sudo systemctl status cloudflared`. |
| `git clone` says **Permission denied (publickey)** | The VM's deploy key hasn't been added to the repo yet (Step 4). |
| `npm run build` gets **Killed** | The VM ran out of memory. Add swap (Step 3) or use the A1.Flex shape. |
| **"Too many failed sign-ins"** | 5 wrong passwords in 15 minutes. Wait, or run `sudo systemctl restart copilot`, which clears the counter. |
| Forgot password | There is no reset yet. Register again with another e-mail. |
