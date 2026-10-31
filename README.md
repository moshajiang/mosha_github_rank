# GitHub Rank

中文优先的 GitHub 项目发现与趋势排行工具，关注近期热门、早期潜力、AI Agent 生态及 AI 前沿资讯。

当前阶段：已完成首个本地版本及第二阶段增强，实采 100 个仓库、51 个 Agent 资源和 111 条资讯。支持语言/Star 筛选、来源启停、可选 Ollama 中文摘要。完整增长榜等待历史积累；当前没有运行中的模型服务，尚未生成真实模型摘要。

- [竞品调研](docs/RESEARCH.md)
- [开发方案](docs/DEVELOPMENT_PLAN.md)
- [AI 前沿资讯方案](docs/AI_NEWS_PLAN.md)
- [待解决问题与参考方案](docs/OPEN_QUESTIONS.md)
- [成熟方案借鉴与实施状态](docs/IMPLEMENTATION.md)
- [验证报告与已知限制](docs/VALIDATION.md)
- [中文摘要配置与调用](docs/SUMMARIES.md)

首版方向：分类周榜/月榜、潜力榜、AI Agent 独立专栏、AI 前沿资讯、中文简要介绍与原始来源链接。榜单使用可追溯的统计周期；数据不足时显示观察状态。资讯按来源节奏定时更新，支持去重、分类与关联项目发现。

调研日期：2026-10-30（Asia/Shanghai）。

## 双击启动（Windows）

首次安装完成后，日常直接双击项目根目录的 [启动.cmd](启动.cmd)：后台启动服务，等待就绪后自动打开浏览器。重复启动复用当前服务，默认端口被占用时自动选择附近空闲端口。

关闭服务时双击 [关闭.cmd](关闭.cmd)。关闭浏览器标签页后后台服务仍会运行；关闭入口核对进程身份，只处理快捷启动器创建的进程。

快捷启动器会读取项目根目录 `.env` 中的 GitHub Rank 配置，无需每次手动设置环境变量。后台服务日志在 `data/desktop-server.log`，启动日志在 `data/desktop-launcher.log`。源码更新后按下方命令重新构建前端即可。

## 本地启动

需要 Python 3.11+、Node.js 和 npm；以下为项目根目录下的 PowerShell 命令。依赖分别锁定在 `requirements.lock` 和 `frontend/package-lock.json`。

```powershell
uv venv --python python .venv
uv pip sync --python .venv\Scripts\python.exe requirements.lock
uv pip install --python .venv\Scripts\python.exe --no-deps -e .
```

```powershell
Set-Location frontend
npm ci
npm run build
Set-Location ..
.\scripts\start.ps1
```

打开 [本地工作台](http://127.0.0.1:8000)，API 文档位于 [接口文档](http://127.0.0.1:8000/docs)。源码内不含演示项目或伪造历史；首次运行需执行采集命令。数据默认保存到 `data/github_rank.sqlite3`，不提交版本库。

## 采集和调度

在另一个 PowerShell 终端运行：

```powershell
# 小批量验证；无需 Token，但受公共额度限制。
.\.venv\Scripts\python.exe -m github_rank.cli collect --no-discovery --repo-limit 12

# 常规采集：配置中的种子、搜索发现、资讯与 Releases。
.\scripts\collect.ps1

# 仅刷新资讯；-Force 跳过来源轮询间隔，不跳过上游限流。
.\scripts\collect.ps1 -Mode news -Force

# 保持此进程运行，按源检查资讯，并在北京时间 08:00 后执行每日任务。
.\scripts\schedule.ps1
```

来源、种子和预算在 [配置文件](config/sources.yaml) 中编辑。命令行后端直接读取进程环境变量；双击启动器和 Docker Compose 会读取 `.env`。可参考 `.env.example`，为服务端设置 `GITHUB_TOKEN`、`GITHUB_RANK_DB` 和 `GITHUB_RANK_CONFIG`。

API 限流时会尝试公开页面结构化精确计数和 Releases Atom；页面不提供的字段保持缺失。正式周/月榜只按实际端点计算净增；潜力分另需双周期历史、覆盖率与足够参照样本。详情和来源面板展示相应状态。

## Docker

```powershell
docker compose up --build -d
```

提供本机 Web 服务和独立 scheduler，共享持久数据卷。Compose 配置已校验；当前环境 Docker daemon 未启动，尚未实际构建运行镜像。备份可执行 `docker compose exec web python -m github_rank.cli backup /app/data/backup.sqlite3`，需使用尚不存在的目标文件。

## 测试和备份

```powershell
uv pip install --python .venv\Scripts\python.exe -e '.[dev]' --constraint requirements.lock
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m github_rank.cli backup data\backup.sqlite3
```

Windows 受限沙箱中，pytest 临时目录需指定到工作区，例如 `--basetemp=D:\MyProject\github_rank\.cache\test-run-01`，每次选择新的目录。API 测试的 asyncio 本机套接字也可能需要运行环境许可。

主要代码位于 `backend/github_rank/` 和 `frontend/src/`。目前没有配置模型、外部消息推送或系统常驻任务；scheduler 只有在进程运行时才工作。

## 来源管理与中文摘要

```powershell
.\.venv\Scripts\python.exe -m github_rank.cli sources list
# 暂停/恢复某个来源；保留已采集内容。
.\.venv\Scripts\python.exe -m github_rank.cli sources disable deepmind
.\.venv\Scripts\python.exe -m github_rank.cli sources enable deepmind
# 配置现有 Ollama 服务后才启用模型摘要；未配置会明确返回 not_configured。
.\.venv\Scripts\python.exe -m github_rank.cli summarize --kind news --limit 5
```

来源启停保存在数据库，优先于配置默认值。中文摘要的引用校验、缓存、输入变化失效、每日调用上限和配置示例见 [摘要说明](docs/SUMMARIES.md)。网页仍只提供读取，管理操作经本机命令执行。
