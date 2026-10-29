# 部署到自己的域名（GitHub + Cloudflare Tunnel）

本指南把项目放到 GitHub 私有仓库，并通过你的域名访问，例如 `https://copilot.你的域名.com`。网站自带账号系统：每人用邮箱和密码登录，注册需要你发的邀请码。

## 整体结构

```text
组员/老师的浏览器
   │  https://copilot.你的域名.com
   ▼
（可选）Cloudflare Access：邮箱验证码，作为第二道门
   ▼
Cloudflare Tunnel（加密隧道，不用开放路由器端口）
   ▼
你的电脑：cloudflared  →  http://127.0.0.1:8000（后端 + 网页，同一个进程）
```

- **服务跑在你的电脑上**：演示期间电脑要**开机并联网**，项目要在运行。
- **必须登录**：除了登录和注册页面，所有接口都要求登录。注册需要邀请码 `COPILOT_INVITE_CODE`，没设邀请码时服务拒绝启动。连续输错密码 5 次会锁定 15 分钟。
- **每人用自己的 key**：每个账号在 **AI settings** 里保存自己的 API key，费用记在各自账户上。key 加密保存在你电脑上的数据库里，不会返回浏览器，也不会进入 GitHub。
- **哪些共享、哪些私有**：工厂数据（订单、产量）大家共享且只读；聊天记录、聊天记忆、提醒和动作记录都只属于各自的账号。

---

## 第 1 步：上传到 GitHub（私有仓库）

本地仓库已经初始化好，并且做了第一次提交。

1. 登录 <https://github.com>，点右上角 **+ → New repository**。
   - Repository name：例如 `gm-copilot`
   - 选择 **Private**
   - **不要**勾选 "Add a README" 等任何初始化选项
2. 创建后，在项目根目录执行（把地址换成你的仓库地址）：
   ```powershell
   cd C:\Users\Lenovo\Desktop\5105project
   git remote add origin https://github.com/你的用户名/gm-copilot.git
   git push -u origin main
   ```
   第一次推送时会弹出浏览器，让你登录 GitHub 授权。
3. 邀请组员：仓库页面 **Settings → Collaborators → Add people**。

> 以下内容不会上传：API key、加密主密钥、数据库、`deploy.env`、`node_modules`、`.venv`，已经由 `.gitignore` 排除。组员克隆后按 [Team_Local_Setup_ZH.md](Team_Local_Setup_ZH.md) 安装，并用自己的 key。

---

## 第 2 步：把域名接入 Cloudflare

如果你的域名是在 Cloudflare 上买的，可以跳过这一步。

1. 登录 <https://dash.cloudflare.com>，点 **Add a domain**，输入你的域名，选择 Free 套餐。
2. Cloudflare 会给出两个 nameserver（名称服务器）。到你**购买域名的网站**，把 nameserver 改成这两个。
3. 等待生效（通常几分钟到几小时），Cloudflare 显示域名状态为 **Active** 后再继续。

## 第 3 步：创建 Tunnel，把电脑接到域名上

1. 在 Cloudflare 后台进入 **Zero Trust**（第一次进入会让你给团队起名，例如 `gm16`，并选择 Free 套餐）。
2. 进入 **Networks → Tunnels → Create a tunnel**，选择 **Cloudflared**，起个名字（例如 `copilot`）。
3. 选择 **Windows**，复制页面给出的安装命令（形如 `cloudflared.exe service install eyJ...`）：
   - 先按页面提示下载安装 cloudflared；
   - 用**管理员身份**打开 PowerShell，粘贴并执行这条命令。cloudflared 会被安装成系统服务，开机自动运行。
4. 回到页面，看到 Connector 状态变成 **Connected** 后点 Next，添加 **Public hostname**：
   - Subdomain：`copilot`
   - Domain：选择你的域名
   - Service：Type 选 **HTTP**，URL 填 **`localhost:8000`**
5. 保存。

## 第 4 步：在电脑上启动项目

1. 在项目根目录，把 `deploy.env.example` 复制一份，改名为 `deploy.env`，设置邀请码（至少 8 个字符，只发给组员和老师）：
   ```text
   COPILOT_INVITE_CODE=换成你自己的一串邀请码
   ```
2. 启动（这个脚本会自动安装依赖、打包网页并启动服务）：
   ```powershell
   cd C:\Users\Lenovo\Desktop\5105project
   powershell -ExecutionPolicy Bypass -File scripts\start-production.ps1
   ```
   看到 `Serving on http://127.0.0.1:8000` 就说明启动成功了，**这个窗口不要关**。
3. 打开网站，点 **Create an account** 注册（填邮箱、密码和邀请码），登录后到 **AI settings** 填入**你自己的** API key。
4. 把网址和邀请码发给组员。他们各自注册，各自填自己的 key。

## 第 5 步（可选）：加一道 Cloudflare Access

只有在你想让陌生人连登录页都看不到时才需要做这一步。

1. 在 **Zero Trust** 里进入 **Access → Applications → Add an application → Self-hosted**，Application domain 填第 3 步的 hostname。
2. 添加策略：Action 选 **Allow**，Include 选 **Emails**，填入组员和老师的邮箱。登录方式保持默认的 **One-time PIN**。
3. 复制应用的 **Application Audience (AUD) Tag**，以及 Zero Trust **Settings** 里的 **Team domain**（形如 `gm16.cloudflareaccess.com`）。
4. 填进 `deploy.env` 的 `CF_ACCESS_TEAM_DOMAIN` 和 `CF_ACCESS_AUD`，重启脚本。后端会额外校验 Access 凭证。

> Cloudflare 后台的菜单名称偶尔会调整。如果找不到对应的位置，可以在后台顶部搜索 "Tunnels"、"Access applications" 或 "AUD"。

## 第 6 步：验证

- 用手机流量（不连家里 Wi-Fi）打开 `https://copilot.你的域名.com`：应该看到网站的登录页。
- 不填邀请码或填错邀请码注册：应该被拒绝。
- 用两个账号分别登录：A 保存的 key、聊天和提醒，B 都看不到。
- 关掉 `start-production.ps1` 的窗口后再打开网站：应该显示 502 或连接失败，这说明服务确实是从你的电脑提供的。

---

## 常见问题

**启动脚本报错 `deploy.env not found` 或 `Set COPILOT_INVITE_CODE`。**
按第 4 步创建 `deploy.env` 并填写至少 8 个字符的邀请码。这是有意设计的：没有邀请码时，公网模式不允许启动。

**打开网站显示 `Sign-in through Cloudflare Access is required` 或 `could not be verified`。**
只有做了第 5 步才会出现。检查 Access 应用的域名是否和第 3 步的 hostname 完全一致，`deploy.env` 里的 AUD 和 team domain 是否复制正确。改完后要重启脚本。

**有人忘记密码了怎么办？**
目前没有找回密码功能。可以让他用另一个邮箱重新注册。

**显示 502 Bad Gateway。**
cloudflared 已经连上了，但你的电脑上项目没在运行，或者端口不是 8000。重新运行启动脚本即可。

**电脑睡眠后网站就打不开了。**
在 Windows 的"设置 → 系统 → 电源"里，把"接通电源时进入睡眠"设为"从不"。

**组员能用我的 API key 吗？**
不能。每个账号只能使用自己在 AI settings 里保存的 key；没保存 key 的账号用 AI 聊天时会提示先去设置。key 永远不会返回到浏览器。

**大家看到的数据是共享的吗？**
工厂数据（订单、产量、风险分析）是共享且只读的。聊天记录、聊天记忆、提醒和动作记录按账号隔离，别人看不到，也确认不了你准备的动作。

**本地开发还能照常使用吗？**
可以，`backend.dev` + `npm run dev` 的方式完全不变，也不需要 `deploy.env`。
