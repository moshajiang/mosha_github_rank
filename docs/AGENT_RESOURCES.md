# Agent 资源识别与来源证据

更新：2026-10-31。目录支持 Skills、Claude Code 插件清单和带 MCP Registry schema 声明的 server.json。元数据只用于展示，不安装资源或运行清单中的指令。

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

scripts/verify_resource_samples.py 会读取 10 个真实仓库，将各自覆盖状态、读取数和限制原因写入本地 data/resource-sample-report.json。先做一致性备份。当前无 GitHub Token，公共 API 限流下的页面结果不能算作 10 个多资源仓库的全量识别。

目前保留最新资源记录及证据 commit；完整版本档案、安装遥测、跨格式语义去重和资源运行测试仍未实现。
