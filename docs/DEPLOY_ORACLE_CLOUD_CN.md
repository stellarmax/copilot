# 部署到 Oracle Cloud（Always Free）+ Cloudflare Tunnel

> 这是 [DEPLOY_ORACLE_CLOUD_EN.md](DEPLOY_ORACLE_CLOUD_EN.md) 的中文版，内容一致。

本指南从**注册完 Oracle Cloud 账号**之后开始。做完以后，项目会在 Oracle 的免费虚拟机上全天运行，可以通过 `https://copilot.<我们的域名>` 访问。每个人用自己的账号登录，并使用自己的 AI key。

```text
浏览器 ──https──▶ Cloudflare ──Tunnel（由虚拟机主动向外连接）──▶ Oracle 虚拟机：cloudflared → http://127.0.0.1:8000（uvicorn：API + 网页）
```

虚拟机**不需要开放任何入站端口**，因为 `cloudflared` 是从虚拟机主动连到 Cloudflare 的。所以不用改 Oracle 的安全列表，也不用改 Ubuntu 的防火墙。

**开始前需要准备：**
- SSH 客户端：Windows 用 PowerShell 自带的 `ssh`，Mac 用"终端"。
- GitHub 仓库 `stellarmax/copilot` 的读取权限。仓库要是带账号系统的版本，也就是包含 `backend/app/auth.py`。
- 管理我们域名的 Cloudflare 账号权限，或者请有权限的人帮你做第 7 步。
- 一个网站邀请码：至少 8 个字符，和组员约定好。

---

## 第 1 步：创建虚拟机

1. 在 Oracle Cloud 控制台打开 **☰ → Compute → Instances → Create instance**。
2. **Name**：`copilot`。
3. **Image**：点 *Change image*，选择 **Canonical Ubuntu 24.04**。
4. **Shape**：点 *Change shape → Ampere → VM.Standard.A1.Flex*，设置为 **1 OCPU、6 GB 内存**。这在 Always Free 免费额度之内，免费额度总共最多 4 OCPU、24 GB。
   - 如果提示 **"Out of capacity"**，在同一页换一个 *Availability domain*（可用区），或者过段时间再试。免费的 Ampere 资源经常不够。
   - 备选方案是 `VM.Standard.E2.1.Micro`（AMD 处理器，1 GB 内存），也是免费的。1 GB 足够**运行**这个项目，但请按第 3、5 步里"1 GB 机器"的说明操作：网页在你自己的笔记本上打包，不在虚拟机上打包。
5. **Networking**：保持默认，也就是新建 VCN 和公共子网，并保持 *Assign a public IPv4 address* 开启。公网 IP 只用来 SSH 登录。
6. **SSH keys**：选择 *Generate a key pair for me*，然后**下载私钥**，例如 `ssh-key-copilot.key`。请妥善保存，丢了就登录不了。
7. 点 **Create**。状态变成 **Running** 后，复制 **Public IP address**（公网 IP）。

> 免费的 Ampere 机型只能在**主区域（home region）**创建，也就是注册时选的那个区域。

## 第 2 步：用 SSH 登录

Windows PowerShell：

```powershell
icacls .\ssh-key-copilot.key /inheritance:r /grant:r "$($env:USERNAME):R"
ssh -i .\ssh-key-copilot.key ubuntu@<公网IP>
```

Mac：

```bash
chmod 600 ~/Downloads/ssh-key-copilot.key
ssh -i ~/Downloads/ssh-key-copilot.key ubuntu@<公网IP>
```

从这里开始，下面所有命令都在**虚拟机上**执行。

## 第 3 步：安装软件

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install git python3-venv python3-pip build-essential
# Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt -y install nodejs
python3 --version   # 需要 3.11 或更高（Ubuntu 24.04 自带 3.12）
node --version      # 需要 v20 或更高
```

**仅限 1 GB 的 Micro 机器：**
- 加 2 GB swap，留一点余量。
- 可以完全不装 Node.js，改为在笔记本上打包网页（见第 5 步）。

项目运行时占用的内存很少：后端约 60 MB，`cloudflared` 约 30 MB。真正吃内存的只有 `npm ci` 和 `npm run build`。

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 第 4 步：拉取代码

仓库是私有的，所以要给虚拟机单独生成一把只读密钥：

```bash
ssh-keygen -t ed25519 -C "copilot-vm" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

把打印出来的那一行发给仓库管理员。管理员在 **GitHub 仓库 → Settings → Deploy keys → Add deploy key** 里添加，**不要**勾选 *Allow write access*。添加好以后执行：

```bash
cd ~
git clone git@github.com:stellarmax/copilot.git
cd copilot
ls backend/app/auth.py    # 必须存在；如果不存在，说明账号系统还没推上去，先停下来问一下
```

## 第 5 步：安装依赖、打包、配置

```bash
cd ~/copilot
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r backend/requirements.txt

cd frontend
npm ci
npm run build          # 生成 frontend/dist
cd ..
```

> **1 GB Micro 机器：改在笔记本上打包。** 跳过上面 `frontend` 那几行命令，第 3 步也不用装 Node.js。
>
> 在笔记本上自己 clone 的仓库里，切到同一个版本，依次执行 `cd frontend`、`npm ci`、`npm run build`。然后把打包结果传上去：
> ```bash
> # 在笔记本上、仓库根目录执行
> scp -i <私钥路径>/ssh-key-copilot.key -r frontend/dist ubuntu@<公网IP>:copilot/frontend/
> ```
> 以后每次 `git pull` 拉到了 `frontend/` 的改动，都要重新打包、上传一次。

```bash
cp deploy.env.example deploy.env
nano deploy.env        # 设置 COPILOT_INVITE_CODE=<团队邀请码>；两行 CF_ACCESS_* 留空
chmod 600 deploy.env
```

快速测试。下面的命令运行几秒后，按 `Ctrl+C` 停止：

```bash
set -a; . ./deploy.env; set +a
.venv/bin/python -m uvicorn backend.serve:app --host 127.0.0.1 --port 8000
# 另开一个 SSH 窗口执行：curl -s http://127.0.0.1:8000/health   → {"status":"ok"...}
```

第一次启动时会生成两个文件，都不在 git 里：
- `backend/.ai-credentials.key`：加密主密钥，用来加密每个人保存的 AI key；
- `backend/.frontend-demo.sqlite3`：数据库。

**这两个文件不要提交、不要外传、不要删除**（见第 9 步）。

## 第 6 步：注册成系统服务（开机自启、崩溃自动重启）

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
sudo systemctl status copilot --no-pager      # 应显示 "active (running)"
curl -s http://127.0.0.1:8000/health
```

查看日志：`journalctl -u copilot -f`。

`--host 127.0.0.1` 不要改。项目只能通过 Tunnel 访问，不能直接通过公网 IP 访问。

## 第 7 步：用 Cloudflare Tunnel 接上域名

这一步在管理我们域名的那个 Cloudflare 账号里操作。如果你没有权限，就请有权限的人把 tunnel token 发给你。

1. 打开 **Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared**，起名 `copilot-oracle`。
2. 在 *Choose your environment* 里选 **Debian**：
   - Ampere（A1.Flex）机器选 **arm64**；
   - Micro（AMD）机器选 **64-bit**。
3. 页面会给出一组安装命令，**在虚拟机上**执行。最后一条长这样：
   ```bash
   sudo cloudflared service install eyJhIjoi...
   ```
   等 Connector 显示 **Connected** 后点 **Next**。
4. 添加 **Public hostname**：
   - **Subdomain**：`copilot`。必须用一个**没被其他项目占用**的子域名，因为我们域名下已经有一个子域名在跑别的项目。
   - **Domain**：选我们的域名。
   - **Service**：`HTTP` → `localhost:8000`。
5. 保存。Cloudflare 会自动创建 DNS 记录。

## 第 8 步：验证

用手机流量（不要连 Wi-Fi）：
1. 打开 `https://copilot.<我们的域名>`，应该出现 **Sign in** 登录页。
2. 点 **Create an account** 注册，不填邀请码或者填错邀请码，必须被拒绝。
3. 用正确的邀请码注册，然后打开 **AI settings**，填入**你自己的** API key，点 **Test connection**。
4. 再注册一个测试账号。这个账号**不能**看到第一个账号的 key 状态、聊天、提醒和动作记录。
5. 把网址和邀请码发给组员。每个人自己注册、填自己的 key。

## 第 9 步：日常维护

**发布新版本：**

```bash
cd ~/copilot
git pull
.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)   # 1 GB 机器：改为在笔记本上打包，再 scp 上传 frontend/dist（见第 5 步）
sudo systemctl restart copilot
```

**备份：** 定期把下面两个文件拷到安全的地方，比如在笔记本上执行：

```bash
scp -i ssh-key-copilot.key ubuntu@<公网IP>:copilot/backend/.frontend-demo.sqlite3 .
scp -i ssh-key-copilot.key ubuntu@<公网IP>:copilot/backend/.ai-credentials.key .
```

如果丢了 `.ai-credentials.key`，已保存的 AI key 就解不开了，每个人都要重新填一次 key。账号和聊天记录不受影响。

**闲置回收：** 如果免费虚拟机连续 7 天几乎闲置（CPU、网络、内存使用都很低），Oracle 可能会把它停掉。网站突然打不开时，先去控制台看看实例状态，必要时重新启动。把账号升级为 *Pay As You Go* 就不会被回收，而且 Always Free 范围内的资源仍然免费。

**更换邀请码：** 修改 `deploy.env`，然后执行 `sudo systemctl restart copilot`。已有账号不受影响。

---

## 常见问题

| 现象 | 原因 / 解决办法 |
|---|---|
| `copilot.service` 启动失败，日志显示 **frontend/dist is missing** | 网页还没打包。执行 `cd frontend && npm ci && npm run build`；1 GB 机器在笔记本上打包后上传。然后重启服务。 |
| 日志显示 **Set COPILOT_INVITE_CODE** | `deploy.env` 里没有邀请码，或者邀请码不足 8 个字符。 |
| 浏览器显示 **502 Bad Gateway** | Tunnel 已连上，但项目没在运行。用 `sudo systemctl status copilot` 检查。 |
| 浏览器显示 Cloudflare **1033** 错误 | 虚拟机上的 `cloudflared` 没连上。用 `sudo systemctl status cloudflared` 检查。 |
| `git clone` 提示 **Permission denied (publickey)** | 虚拟机的 Deploy key 还没加到仓库里（见第 4 步）。 |
| `npm run build` 显示 **Killed** | 内存不够。加 swap（第 3 步），或改在笔记本上打包（第 5 步）。 |
| 提示 **"Too many failed sign-ins"** | 15 分钟内输错了 5 次密码。等一会儿，或者执行 `sudo systemctl restart copilot` 清空计数。 |
| 忘记密码 | 目前没有找回密码功能，只能换一个邮箱重新注册。 |
