# 手动跟踪、分类修订与仓库改名

更新：2026-10-31。管理命令在项目根目录执行，网页保持只读。命令行使用进程环境变量，数据库和配置路径设置方式与采集任务一致。

## 添加项目

```powershell
.\.venv\Scripts\python.exe -m github_rank.cli projects add https://github.com/owner/repository
# 同样接受 owner/repository 和不含查询参数的 HTTPS .git 地址。
```

立即采集这一个公开仓库，不必等待日常批次的候选名额。成功后进入跟踪池，后续每日任务会继续更新。元数据来自 GitHub；采集失败会保留任务失败记录，不插入空项目。重复执行保留每天首次成功快照。入口不下载或运行仓库代码。

支持 GitHub API 和现有公开页面精确计数降级；GitHub Token 可用时也拒绝将私有仓库发布到本地公开浏览接口。

## 修订分类和 Agent 标签

```powershell
.\.venv\Scripts\python.exe -m github_rank.cli projects list
.\.venv\Scripts\python.exe -m github_rank.cli projects set owner/repository --category devtools --agent-types coding plugin --reason '核对作者文档：编程助手插件'
# --agent-types 后没有值时清空人工 Agent 标签；省略参数则保留已有覆盖。
.\.venv\Scripts\python.exe -m github_rank.cli projects set owner/repository --agent-types --reason '核对后确认不属于 Agent 工具'
```

主分类允许值：`ai`、`devtools`、`frontend`、`backend`、`data`、`devops`、`security`、`productivity`、`games`、`learning`、`other`。Agent 标签允许值：`framework`、`coding`、`mcp`、`plugin`、`skill`、`workflow`。

原始自动分类保存在采集元数据中，人工覆盖独立保存；刷新仓库不会冲掉修订。项目筛选、实时榜单、导出使用同一套生效分类。人工 Agent 标签也参与后续资源扫描判断。项目卡片标明人工修订；详情展示当前分类、自动识别、修订说明和时间。

## 排除、恢复和审计

```powershell
.\.venv\Scripts\python.exe -m github_rank.cli projects set owner/repository --exclude --reason '与当前关注方向无关'
.\.venv\Scripts\python.exe -m github_rank.cli projects set owner/repository --include --reason '重新纳入关注'
.\.venv\Scripts\python.exe -m github_rank.cli projects history owner/repository
.\.venv\Scripts\python.exe -m github_rank.cli projects reset owner/repository --reason '恢复自动分类与默认可见状态'
```

排除会隐藏当前项目列表、热门/潜力榜、观察列表及资源目录中的条目，同时不参与潜力评分参照集合。详情、资源直接链接、历史快照和已有归档仍可查；继续采集以保留连续观测。排除不表示停止采集，也不表示删除项目。

`--include` 只恢复可见性，保留分类覆盖。`reset` 移除该项目的所有覆盖，包括排除状态，采用最近一次采集的自动分类。每次修订、恢复都要求说明（1—500 字符），记录修改前后值。管理操作与采集共用任务锁，繁忙时明确报错，避免并发覆盖。

修改立即影响实时读取，不会改写已发布榜单。如果需要新的归档，另行执行 `python -m github_rank.cli publish`；旧 `run_id` 内容保持不变。

## 改名和转移

采集按 GitHub 返回的仓库数字 ID 更新当前名称，记录此次请求的旧名称及原先存储名称。本站旧详情/历史地址会解析到同一 ID，详情提示新名称，并提供当前地址入口。未重新扫描的资源按当前仓库地址打开，保留原证据 commit 和路径。人工覆盖和修订记录始终绑定仓库 ID。

例如：本次真实采集 `tiangolo/fastapi` 返回 `fastapi/fastapi`，ID 为 `160919119`。旧地址 `/projects/tiangolo/fastapi` 已可打开现有项目及历史。该行为也参考了 [GitHub 的仓库重命名说明](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository)。

仅保存实际观测的别名，不猜测转移关系。若后续采集发现旧名称被另一个仓库 ID 使用，当前名称优先，删除冲突旧别名；不会合并两个仓库的历史。还未被采集发现的名称复用无法自动识别，可用 `projects add` 直接刷新该地址。

## 数据升级和验证范围

数据库自动从 v1/v2 迁移到 v3，新增别名、人工覆盖和审计表。本次升级前已通过 SQLite backup API 备份真实数据库，升级后核对原始记录数量及完整性。

自动化测试覆盖修订跨刷新保留、重置使用最新自动分类、排除与归档隔离、筛选/导出一致、同 ID 改名、旧名复用、固定 commit 资源链接、失败记录、私有仓库拒绝及任务锁。界面测试在独立数据库副本上设置修订和排除，正式数据库未写入测试覆盖。尚无网页管理表单、任意历史修订一键回退或自动分类质量评估工具。
