# Agent 资源识别与来源证据

更新日期为 2026-11-19。目录支持 Skills、Claude Code 插件清单和带 MCP Registry schema 声明的 server.json。

## 扫描方式与预算

Agent 分类仓库默认扫描；其他仓库可执行 `python -m github_rank.cli projects add owner/repository --scan-resources` 强制扫描。

API 可用时固定默认分支 commit，先请求递归目录；截断或无法读取时改为逐层补扫，参考 [GitHub Git Trees 文档](https://docs.github.com/en/rest/git/trees#get-a-tree)。跳过符号链接和子模块。

API 限流时读取公开页面的目录和 README 资源链接，并对 skills、plugins、src 等可见目录做有界补扫。目录页面的 commit 必须与本轮一致；此方式始终标记部分扫描。

配置位于 config/sources.yaml 的 collection 段：max_resource_files 默认 30，max_tree_requests 默认 20，max_tree_depth 默认 12。max_resource_requests_per_batch 默认 300，约束整批资源读取调用数，不影响仓库元数据及资讯读取；单次调用的重试仍受 HTTP 层限制。另有单文件 200 KB、目录队列及共享 GitHub API 预算。到达上限会记录原因；候选数只表示已发现文件，不代表仓库全部资源数。

只有目录完整、候选全部在预算内处理且无读取失败时，才清理已删除或失效的旧资源。部分/失败扫描保留上次记录，并显示本轮已核对、保留上次记录或待重新扫描。

## 类型与兼容证据

| 类型 | 识别依据 | 提取内容 |
| --- | --- | --- |
| Skill | SKILL.md 的 YAML 名称及用途描述 | compatibility 原文字段、许可、声明版本及基本命名提醒 |
| 插件 | .claude-plugin/plugin.json 路径和有效名称 | 显式兼容声明、版本、许可；格式归入 Claude Code 插件 |
| MCP Server | 官方静态 schema 域名/路径、命名空间名称、描述和版本 | packages/remotes 的传输类型及显式兼容声明 |

格式参考 [Agent Skills specification](https://agentskills.io/specification)、[Claude Code manifest](https://code.claude.com/docs/en/plugins-reference) 和 [MCP server.json](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/generic-server-json.md)。本项目只做目录识别与字段提取，不等于完整 schema 验证、官方注册认证或运行测试。

生态格式与兼容要求分开显示。没有原文字段就标为未声明，旧记录缺少字段证据则提示重新扫描。MCP 清单不复制环境变量值、启动参数或远端访问凭据。

## 内容去重与详情页

资源 ID 由仓库数字 ID 和路径组成；每次读取记录完整文件字节的 SHA-256。名称相同或描述相似不代表内容相同，正文、换行的变化也会改变 hash。

目录按资源类型与文件 hash 分组，保留所有来源 ID、仓库、路径和 commit，不判断原创或转载关系。缺 hash 的旧记录不推测去重；搜索能匹配组内任一仓库，已排除仓库不出现在当前来源分组中。

GET /api/agent-resources 支持 kind=skill|plugin|mcp、q、limit、offset；group_duplicates=false 展示逐文件结果。total 是分组后的条数，matching_source_total 是匹配来源文件数，分页在分组后应用。网页每页 100 项，页码保存在 URL 中。GET /api/agent-resources/{id} 提供具体来源、兼容证据、扫描报告及同内容来源。

网页 /resources/{id} 展示引用字段、证据 commit、文件 hash、预算及不完整原因，并保留原文件入口。仓库 Star 仅为背景指标，资源没有独立安装量。

## 验证范围

自动化测试覆盖截断补扫、预算、固定 commit、失败保留、完整扫描清理、符号链接/大文件、普通 server.json 排除、敏感字段不复制、去重/搜索/排除一致及旧数据降级。

## 定向补扫

~~~powershell
.\.venv\Scripts\python.exe -m github_rank.cli projects rescan --dry-run --limit 10
.\.venv\Scripts\python.exe -m github_rank.cli projects rescan --limit 10
.\.venv\Scripts\python.exe -m github_rank.cli projects rescan owner/repository owner/second-repo
.\.venv\Scripts\python.exe -m github_rank.cli projects rescan --resume --dry-run
.\.venv\Scripts\python.exe -m github_rank.cli projects rescan --resume
~~~

预览读取已有记录。自动选择范围是已跟踪、仍需扫描、且有 Agent 分类或资源证据的仓库，优先尚无完整扫描证据的多资源仓库。显式指定项目按所给顺序执行，接受库内曾用名称并核对 GitHub 数字 ID。单次可选 1 到 30 个项目。

补扫使用同一个 REST 客户端和同一把采集锁。已有采集任务占用锁时会报告忙碌。API 或资源主机限流、整批资源请求额度不足时，本批停止并标记待续条目。原有日常采集仍可使用公开页面。公开 API 的额度和重置条件见 [GitHub REST 限流文档](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)。

命令输出与任务日志记录每个仓库的提交、目录状态、候选文件数、实际读取数、有效资源数和中断原因。覆盖体检汇总有完整证据且当时识别至少两项资源的仓库。之后的部分扫描会保留那次完整扫描的提交和时间，同时更新当次扫描状态。

--resume 从最近一次结束的补扫恢复待续、被中断和受预算限制的项目。也可以传入先前报告的批次 ID，例如 --resume BATCH_ID。续扫按仓库 ID 查找当前名称，并跳过已经完成扫描或已排除的项目。若 --limit 只执行部分待续项目，其余项目仍保存在新批次中。

目前保留最新资源记录及证据 commit；完整版本档案、安装遥测、跨格式语义去重和资源运行测试仍未实现。
