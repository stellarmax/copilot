# 部署到自己的域名（GitHub + Cloudflare Tunnel + Access）

本指南把项目放到 GitHub 私有仓库，并通过你的域名访问，例如 `https://copilot.你的域名.com`。只有你允许的邮箱能登录。

## 整体结构

```text
组员/老师的浏览器
   │  https://copilot.你的域名.com
   ▼
Cloudflare Access（邮箱验证码登录，只放行名单里的邮箱）
   ▼
Cloudflare Tunnel（加密隧道，不用开放路由器端口）
   ▼
你的电脑：cloudflared  →  http://127.0.0.1:8000（后端 + 网页，同一个进程）
```

- **服务跑在你的电脑上**：演示期间电脑要**开机并联网**，项目要在运行。
- **后端会再检查一遍登录凭证**：后端会验证 Cloudflare Access 的登录凭证，没有凭证的请求一律拒绝。就算 Access 漏配了，网站也不会对外敞开。
- **API key 不会外泄**：key 只保存在你电脑上的加密数据库里，不会进入 GitHub。大家通过网站用的是你保存的 key，**产生的费用记在你的账户上**，所以名单只放组员和老师。

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

## 第 4 步：用 Access 限定谁能登录（必须做）

1. 在 **Zero Trust** 里进入 **Access → Applications → Add an application → Self-hosted**。
2. 填写：
   - Application name：`GM Co-Pilot`
   - Application domain：`copilot` + 你的域名（要和第 3 步一致）
3. 添加策略（Policy）：
   - Action：**Allow**
   - Include：**Emails**，逐个填入组员和老师的邮箱
4. 登录方式保持默认的 **One-time PIN** 即可：打开网站时输入邮箱，收到验证码后登录。
5. 保存后打开这个应用的详情，复制 **Application Audience (AUD) Tag**。
6. 再找到你的 **Team domain**，形如 `gm16.cloudflareaccess.com`。它显示在 Zero Trust 的 **Settings**（设置）里。

> Cloudflare 后台的菜单名称偶尔会调整。如果找不到对应的位置，可以在后台顶部搜索 "Tunnels"、"Access applications" 或 "AUD"。

## 第 5 步：在电脑上启动项目

1. 在项目根目录，把 `deploy.env.example` 复制一份，改名为 `deploy.env`，填入第 4 步得到的两个值：
   ```text
   CF_ACCESS_TEAM_DOMAIN=gm16.cloudflareaccess.com
   CF_ACCESS_AUD=刚才复制的AUD
   ```
2. 启动（这个脚本会自动安装依赖、打包网页并启动服务）：
   ```powershell
   cd C:\Users\Lenovo\Desktop\5105project
   powershell -ExecutionPolicy Bypass -File scripts\start-production.ps1
   ```
   看到 `Serving on http://127.0.0.1:8000` 就说明启动成功了，**这个窗口不要关**。
3. 第一次使用时：在本机打开 <http://127.0.0.1:8000>，到 **AI settings** 填入 API key 并保存。本机访问不需要登录，而 AI 设置只能在本机修改。

## 第 6 步：验证

- 用手机流量（不连家里 Wi-Fi）打开 `https://copilot.你的域名.com`：应该先出现 Cloudflare 的邮箱登录页；输入名单里的邮箱、收到验证码后，能看到网站。
- 用**不在名单里**的邮箱登录：应该被拒绝。
- 关掉 `start-production.ps1` 的窗口后再打开网站：应该显示 502 或连接失败，这说明服务确实是从你的电脑提供的。

---

## 常见问题

**打开网站显示 `Sign-in through Cloudflare Access is required` 或 `could not be verified`。**
说明后端收到了请求，但没有拿到有效的 Access 登录凭证。请检查：第 4 步的应用域名是否和第 3 步的 hostname 完全一致；`deploy.env` 里的 AUD 和 team domain 是否复制正确。改完后要重启脚本。

**启动脚本报错 `deploy.env not found` 或 `Set CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD`。**
按第 5 步创建并填写 `deploy.env`。这是有意设计的：没配置 Access 时，公网模式不允许启动。

**显示 502 Bad Gateway。**
cloudflared 已经连上了，但你的电脑上项目没在运行，或者端口不是 8000。重新运行启动脚本即可。

**电脑睡眠后网站就打不开了。**
在 Windows 的"设置 → 系统 → 电源"里，把"接通电源时进入睡眠"设为"从不"。

**组员能在网站上修改 AI 设置吗？**
不能。保存、测试、删除 API key 只能在运行项目的这台电脑上，通过 <http://127.0.0.1:8000> 操作。经域名访问时，后端会拒绝这些请求（403）。AI key 也永远不会返回到浏览器。组员可以使用 AI 聊天，费用记在你的 key 上，所以名单不要随便扩大。

**大家看到的数据是共享的吗？**
是的。这个项目没有用户账号，所有登录的人共用同一套聊天记录、提醒、动作记录和聊天记忆。如果需要每人独立，就得给项目加上用户系统，这超出了当前的范围。

**本地开发还能照常使用吗？**
可以，`backend.dev` + `npm run dev` 的方式完全不变，也不需要 `deploy.env`。
