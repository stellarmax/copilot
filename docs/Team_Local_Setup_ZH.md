# 组员本机安装与启动指南（含 AI 聊天功能）

本指南带你在自己的 **Windows** 或 **macOS** 电脑上，从零开始安装并启动 Fieldwork Operations Co-Pilot 演示项目，包括 AI 聊天功能。英文版见 [Team_Local_Setup_EN.md](Team_Local_Setup_EN.md)。

整个过程分三步：**装软件（只需一次）→ 装项目依赖（只需一次）→ 启动（每次使用时）**。首次大约需要 15～20 分钟，并且需要联网。

## 0. 获取项目

从 GitHub 私有仓库克隆（需要仓库所有者先邀请你），或者解压组里发的压缩包，都会得到一个项目文件夹（下文称为**项目目录**）：

```bash
git clone https://github.com/stellarmax/copilot.git
```

| 文件夹 | 内容 |
|---|---|
| `backend/` | 后端：Python + FastAPI，包含业务计算、AI Agent 和 API |
| `frontend/` | 网页：React + TypeScript + Vite |
| `data/` | **课程提供数据**（120 个订单、90 天生产日志、8 家外部车间）。网页和 AI 都读取这里，**必须保留** |
| `docs/` | 本指南和部署指南 |

> 仓库和压缩包都**不包含**任何 API key、数据库或聊天记录。每个人需要用**自己的** API key 配置 AI（见第 4 步）。

---

## 1. 安装软件（只需一次）

需要两个软件：**Python 3.11 或更高版本**、**Node.js 20 或更高版本**。

### Windows

1. **Python**：到 <https://www.python.org/downloads/> 下载最新的 Python 3（3.11 及以上）。
   - 安装第一页**勾选 "Add python.exe to PATH"**，然后点 *Install Now*。
2. **Node.js**：到 <https://nodejs.org/> 下载 **LTS** 版本，一路默认安装。
3. 安装完**关掉所有 PowerShell 窗口重新打开**，检查版本：
   ```powershell
   py --version      # 应显示 Python 3.11.x 或更高
   node --version    # 应显示 v20.x 或更高
   npm --version
   ```
   如果提示 `py` 无法识别，改用 `python --version`。只要显示 3.11 或更高，下一步就把命令里的 `py -3` 换成 `python`。

> 打开 PowerShell：按 `Win` 键，输入 `PowerShell`，回车。

### macOS

1. **Python**：到 <https://www.python.org/downloads/macos/> 下载最新的 Python 3 安装包（3.11 及以上）并安装。
   - 安装完成后，在弹出的 Python 文件夹里双击 **Install Certificates.command**（避免之后下载依赖时报 SSL 错误）。
   - ⚠️ macOS 自带的 `python3` 通常是 3.9，版本太低，**不能用**。
2. **Node.js**：到 <https://nodejs.org/> 下载 **LTS** 版本的 macOS 安装包并安装。
3. 打开**新的** Terminal 窗口，检查版本：
   ```bash
   python3.12 --version   # 按你装的版本写，比如 python3.11 / python3.12 / python3.13
   node --version          # 应显示 v20.x 或更高
   npm --version
   ```

> 打开 Terminal：按 `Cmd + 空格`，输入 `Terminal`，回车。
> 如果你习惯用 Homebrew，也可以用 `brew install python@3.12 node` 安装。

---

## 2. 安装项目依赖（只需一次）

把项目克隆或解压到一个路径里**没有中文和空格**的位置（下面的命令以压缩包的文件夹名为例，克隆得到的文件夹名是 `copilot`，换成你自己的路径即可），例如：
- Windows：`C:\projects\General-Manager-Co-Pilot-AI-Demo`
- macOS：`~/projects/General-Manager-Co-Pilot-AI-Demo`

> 路径里有中文或空格，有时会导致命令出错，建议避开。

### Windows（PowerShell）

```powershell
# 进入项目目录（换成你自己的路径）
cd C:\projects\General-Manager-Co-Pilot-AI-Demo

# 1) 创建 Python 虚拟环境，并安装后端依赖
#    （如果 py 无法识别，这一行改成：python -m venv .venv）
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 2) 安装网页依赖
cd frontend
npm ci
cd ..
```

### macOS（Terminal）

```bash
# 进入项目目录（换成你自己的路径）
cd ~/projects/General-Manager-Co-Pilot-AI-Demo

# 1) 创建 Python 虚拟环境，并安装后端依赖（python3.12 换成你装的版本）
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

# 2) 安装网页依赖
cd frontend
npm ci
cd ..
```

看到 `Successfully installed ...` 和 `added ... packages` 就说明装好了。`npm` 输出里的 `warn` 和 `vulnerabilities` 提示可以忽略。

---

## 3. 启动（每次使用时）

需要**同时开两个终端窗口**，并且两个都要**保持运行、不要关**：

| 窗口 | 运行什么 | 端口 |
|---|---|---|
| 窗口 1 | 后端 | 8000 |
| 窗口 2 | 网页 | 5173 |

### Windows

**窗口 1：后端**
```powershell
cd C:\projects\General-Manager-Co-Pilot-AI-Demo
.\.venv\Scripts\python.exe -m uvicorn backend.dev:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend
```

**窗口 2：网页**（另开一个 PowerShell）
```powershell
cd C:\projects\General-Manager-Co-Pilot-AI-Demo\frontend
npm run dev
```

### macOS

**窗口 1：后端**
```bash
cd ~/projects/General-Manager-Co-Pilot-AI-Demo
source .venv/bin/activate
python -m uvicorn backend.dev:app --host 127.0.0.1 --port 8000 --reload --reload-dir backend
```

**窗口 2：网页**（按 `Cmd + T` 新开一个标签页）
```bash
cd ~/projects/General-Manager-Co-Pilot-AI-Demo/frontend
npm run dev
```

### 确认启动成功

- 窗口 1 出现 `Application startup complete.`
- 窗口 2 出现 `Local: http://127.0.0.1:5173/`

然后在浏览器打开：

| 地址 | 用途 |
|---|---|
| <http://127.0.0.1:5173> | **网页主界面** |
| <http://127.0.0.1:8000/health> | 后端健康检查，显示 `{"status":"ok"}` 即正常 |
| <http://127.0.0.1:8000/docs> | 后端 API 文档 |

网页右上角显示 **API connected** 就说明前后端连通了。

### 停止

在两个窗口里分别按 `Ctrl + C`。下次使用时只需重新执行第 3 步，不用再装依赖。

---

## 4. 配置 AI 聊天（第一次使用 AI 时）

不配置 AI 也可以使用订单、生产、可行性等页面；但 AI 聊天需要一个大模型厂家的 API key。

1. 先在下面任意一家申请 API key（一般需要注册并充值少量余额）：

   | 厂家 | 申请地址 |
   |---|---|
   | ChatGPT (OpenAI) | <https://platform.openai.com/api-keys> |
   | Claude (Anthropic) | <https://console.anthropic.com/settings/keys> |
   | Gemini (Google) | <https://aistudio.google.com/apikey> |
   | DeepSeek | <https://platform.deepseek.com/api_keys> |

2. 在网页左侧点 **AI settings**。
3. **AI provider**：选择厂家；**Model**：选择模型（每家的第一个模型都是推荐的默认选项）。
4. **API key**：粘贴你的 key，点 **Save settings**。
5. 点 **Test connection**，显示 *AI provider connection succeeded.* 就成功了。
6. 回到 **Overview**，在 *Ask operations* 输入框提问，或点下方的示例问题试试。

关于 API key：
- 它只保存在你自己电脑上，并且是**加密**保存的。加密用的主密钥由后端第一次启动时自动生成，存放在 `backend/.ai-credentials.key`。
- **不要**把 `backend/.ai-credentials.key` 或 `backend/*.sqlite3` 发给别人或上传到 Git。
- 每次提问都会调用厂家的 API，会**产生少量费用**。

---

## 5. 常见问题

**Q1：Windows 执行 `npm` 报错 "无法加载文件 ... npm.ps1，因为在此系统上禁止运行脚本"。**
这是 PowerShell 的安全策略导致的。二选一：
- 把命令里的 `npm` 换成 `npm.cmd`，例如 `npm.cmd ci`、`npm.cmd run dev`；
- 或者执行一次下面的命令（只影响当前用户），然后重开 PowerShell：
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```

**Q2：Windows 提示 `py` 无法识别。**
有些电脑没有安装 `py` 启动器。先试 `python --version`：
- 如果显示 3.11 或更高，把创建虚拟环境的命令换成 `python -m venv .venv` 即可。之后的命令都以 `.\.venv\Scripts\python.exe` 开头，不受影响。
- 如果 `python` 也无法识别，或者打开了微软应用商店，说明安装 Python 时没勾选 "Add python.exe to PATH"。重新运行 Python 安装程序，选 *Modify*，勾上 *py launcher* 和 *Add Python to environment variables*；或者卸载后重装并勾选 "Add python.exe to PATH"。

**Q3：macOS 提示 `python3.12: command not found`。**
把命令里的版本号换成你实际安装的版本，比如 `python3.11` 或 `python3.13`。在 Terminal 输入 `python3.` 后按两次 `Tab` 键，可以看到已安装的版本。

**Q4：启动后端提示 `No module named uvicorn`。**
没有用项目虚拟环境里的 Python。Windows 必须用 `.\.venv\Scripts\python.exe` 开头；macOS 每次新开窗口都要先执行 `source .venv/bin/activate`（激活后命令行开头会显示 `(.venv)`）。如果还是不行，重新执行第 2 步的 `pip install`。

**Q5：`pip install` 很慢，或者报网络 / SSL 错误。**
- macOS 先确认运行过第 1 步的 *Install Certificates.command*。
- 国内网络可以换用镜像源：
  ```bash
  python -m pip install -r backend/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  ```

**Q6：`npm ci` 很慢或失败。**
国内网络可以先切换镜像，再重新执行 `npm ci`：
```bash
npm config set registry https://registry.npmmirror.com
```

**Q7：提示端口 8000 或 5173 已被占用（`address already in use` / `Port 5173 is in use`）。**
之前启动的服务没关。先关掉旧的终端窗口；如果找不到：
- Windows：执行 `Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess` 查到进程号，再到任务管理器"详细信息"里结束这个进程。
- macOS：执行 `lsof -i :8000` 查到 PID，再执行 `kill <PID>`。

**Q8：网页右上角显示 "API offline"。**
后端没在运行。检查窗口 1 有没有报错、是不是被关掉了，然后打开 <http://127.0.0.1:8000/health> 确认。

**Q9：AI 聊天提示 "AI is not configured"。**
还没在 AI settings 保存 API key，按第 4 步操作。

**Q10：Test connection 提示 key 被拒绝（rejected），或者报 HTTP 错误。**
- **key 被拒绝**：key 复制错了，或者和所选厂家不匹配（比如 OpenAI 的 key 选了 Claude）。
- **429**：请求太频繁或余额不足，去厂家后台检查余额。
- **400 / 404**：你的账号可能没有这个模型的权限，换一个模型试试。

**Q11：想清空所有演示记录，重新开始。**
停止后端，删除 `backend/.frontend-demo.sqlite3`，再重新启动后端。这会清空动作记录、聊天记录、AI 设置和记忆，API key 需要重新填。

**Q12：能不能让同学通过局域网访问我的电脑？**
不支持。项目没有登录认证，AI 设置和聊天接口只允许本机访问。请每个人在自己电脑上运行。
---

## 6. 注意事项

- 页面使用 `data/` 中的**课程提供数据**，业务日期固定为 2026-04-01。
- 所有服务只监听本机地址（`127.0.0.1`），请勿开放到局域网或公网。
- AI 可以帮你**准备**提醒、订单备注和催单草稿，但只有你在聊天卡片上点 **Confirm** 才会执行。催单草稿**永远不会**真的发出去，提醒只在网页里显示（使用电脑的真实时间）。
- 所有数字都由后端确定性计算；回答末尾的 **Evidence** 可以点开查看计算依据。
