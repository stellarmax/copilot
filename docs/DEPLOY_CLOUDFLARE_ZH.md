# 在自己电脑上运行 + Cloudflare Tunnel 发布到域名

项目跑在你的 Windows 电脑上，Cloudflare Tunnel 把 `https://copilot.你的域名.com` 转发到电脑上的 `http://127.0.0.1:8000`。

- 不用买服务器。
- 不用开放路由器端口。
- 不用公网 IP。

```text
组员/老师的浏览器
   │  https://copilot.你的域名.com
   ▼
Cloudflare（HTTPS 证书自动配好）
   ▼
Cloudflare Tunnel（cloudflared 从你的电脑主动连出去）
   ▼
你的电脑：http://127.0.0.1:8000（后端 + 网页，同一个进程）
```

**安全：**
- 除了登录页，所有接口都要求登录。
- 注册需要邀请码；没设邀请码时，脚本拒绝启动。
- 连续输错 5 次密码，锁定 15 分钟。
- 接口文档页（`/docs`）在这个模式下是关闭的。

**谁付 AI 费用：** 每个账号只能用自己在 **AI settings** 里保存的 key，费用记在各自账户上。key 加密保存在你电脑的数据库里，不会返回浏览器，也不会进入 GitHub。

**哪些共享：**
- 订单、产量这类工厂数据：大家共享，只读。
- 聊天、记忆、提醒、动作记录：每个账号各自私有。

**限制：** 只有你的电脑开着、联网、而且启动脚本在运行时，网站才能访问。

---

## 准备

- 已按 [Team_Local_Setup_ZH.md](Team_Local_Setup_ZH.md) 在这台电脑上装好 Python 3.11+ 和 Node.js 20+，项目能正常在本地运行。
- 域名已经接入 Cloudflare，也就是 Cloudflare 后台显示域名状态为 **Active**。
- 想好一个**没被占用**的子域名，例如 `copilot`。不要用另一个项目正在用的那个子域名。

## 第 1 步：设置邀请码

在项目根目录，把 `deploy.env.example` 复制一份，改名为 `deploy.env`（这个文件不会上传到 GitHub）。打开它，只改第一项：

```text
COPILOT_INVITE_CODE=换成你自己的一串邀请码
CF_ACCESS_TEAM_DOMAIN=
CF_ACCESS_AUD=
```

邀请码至少 8 个字符，只发给组员和老师。后两行留空。

## 第 2 步：在电脑上启动项目

先关掉开发模式的后端（`backend.dev`）。它也用 8000 端口，两个不能同时开。然后在 PowerShell 里执行：

```powershell
cd C:\Users\Lenovo\Desktop\5105project
powershell -ExecutionPolicy Bypass -File scripts\start-production.ps1
```

脚本会安装依赖、打包网页，然后启动服务。第一次大约需要一两分钟。看到 `Serving on http://127.0.0.1:8000` 就成功了。**这个窗口不要关**，关掉网站就停了。

在本机浏览器打开 <http://127.0.0.1:8000>，点 **Create an account**，用邮箱、密码和邀请码注册。登录后到 **AI settings** 填入你自己的 API key。

> 这个模式和开发模式用的是同一个数据库，所以之前在开发模式注册的账号可以直接登录。

## 第 3 步：创建 Tunnel（只需做一次）

1. 登录 <https://dash.cloudflare.com>，进入 **Zero Trust**。第一次进入会让你起个团队名，并选择 **Free** 套餐。
2. 进入 **Networks → Tunnels → Create a tunnel**，选择 **Cloudflared**，起个名字，例如 `copilot-laptop`。
   - 如果另一个项目已经有 tunnel，而且跑在别的机器上，这里要**新建**一个，不要复用那个。
3. 环境选 **Windows**，按页面提示下载并安装 cloudflared。
4. 用**管理员身份**打开 PowerShell，粘贴页面给出的命令，形如 `cloudflared.exe service install eyJ...`。cloudflared 会被装成系统服务，开机自动运行，以后不用再管它。
5. 页面上 Connector 显示 **Connected** 后，点 **Next**，添加 **Public hostname**：
   - **Subdomain**：`copilot`（或你选的其他没被占用的名字）
   - **Domain**：选你的域名
   - **Service**：Type 选 **HTTP**，URL 填 **`127.0.0.1:8000`**。建议不要写 `localhost`，因为 Windows 上它可能被解析成 IPv6 地址。
6. 保存。Cloudflare 会自动添加 DNS 记录，你**原来那个项目的子域名不受影响**。

> Cloudflare 后台的菜单名称偶尔会调整。如果找不到对应的位置，可以在后台顶部搜索 "Tunnels"。

## 第 4 步：验证

用手机流量（不要连家里 Wi-Fi）：

1. 打开 `https://copilot.你的域名.com`，应该看到网站的登录页。
2. 注册时不填邀请码或者填错邀请码，应该被拒绝。
3. 用正确的邀请码注册另一个账号。这个新账号看不到你的 key 状态、聊天和提醒。
4. 关掉启动脚本的窗口，再刷新网页，应该显示 **502**。这说明网站确实是从你电脑提供的。重新运行脚本后就能恢复。

然后把网址和邀请码发给组员。每个人自己注册，填自己的 key。

---

## 日常使用

- **每次要让网站上线：** 运行第 2 步的启动脚本，窗口保持打开。cloudflared 是系统服务，会自动运行，不用管。
- **下线：** 关掉脚本窗口就行。想彻底断开，在 Cloudflare 的 tunnel 页面删掉这个 Public hostname，或者用管理员 PowerShell 执行 `cloudflared.exe service uninstall`。
- **防止睡眠：** 演示期间，在 Windows"设置 → 系统 → 电源"里，把"接通电源时进入睡眠"设为"从不"，并插上电源。
- **更新代码：** `git pull` 之后，关掉脚本再重新运行。脚本每次启动都会重新打包网页。
- **换邀请码：** 修改 `deploy.env`，然后重启脚本。已有账号不受影响。
- **备份：** 定期备份 `backend\.frontend-demo.sqlite3`（账号、聊天、提醒等数据）和 `backend\.ai-credentials.key`（加密主密钥）。主密钥丢了，大家保存的 AI key 就解不开了，需要重新填。

## 常见问题

**启动脚本提示 `deploy.env not found` 或 `Set COPILOT_INVITE_CODE`。**
按第 1 步创建 `deploy.env`，邀请码至少 8 个字符。

**提示 `Port 8000 is already in use`。**
开发模式的后端，或者上一次打开的启动脚本还在运行。先把它关掉。

**网站显示 502 Bad Gateway。**
tunnel 是通的，但项目没在运行，或者 Public hostname 的 URL 不是 `127.0.0.1:8000`。

**网站显示 Cloudflare 1033 错误。**
cloudflared 没连上。在"服务"（services.msc）里检查 **Cloudflared agent** 是否正在运行，或者重新执行第 3 步第 4 点的安装命令。

**本机打开 127.0.0.1:8000 注册，也要填邀请码吗？**
要。设置了邀请码以后，所有注册都需要填它。

**忘记密码怎么办？**
目前没有找回密码功能，只能换一个邮箱重新注册。

**能再加一道 Cloudflare 的邮箱验证吗？（可选）**
可以。在 Zero Trust 的 **Access → Applications** 里给这个子域名建一个 Self-hosted 应用，只放行指定邮箱。然后把应用的 **AUD Tag** 和 **Team domain** 填进 `deploy.env` 的 `CF_ACCESS_AUD` 和 `CF_ACCESS_TEAM_DOMAIN`，重启脚本。这样访客要先过邮箱验证码，再用网站账号登录。
