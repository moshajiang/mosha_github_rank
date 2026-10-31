# 可选中文摘要

第二阶段已实现 Ollama 适配器，依据其官方 [Chat API](https://docs.ollama.com/api/chat) 和 [结构化输出](https://docs.ollama.com/capabilities/structured-outputs) 文档。当前环境未检测到运行中的本机 Ollama 服务，因此仅完成模拟接口、存储与失效逻辑验证，没有声称已验证真实模型的中文质量。

## 配置已有服务

不自动下载模型、不安装服务，也不会在未配置模型时调用外部模型接口。在运行采集/摘要命令的 PowerShell 中设置：

```powershell
$env:GITHUB_RANK_SUMMARY_MODEL = '填入本机已安装的模型名'
$env:GITHUB_RANK_SUMMARY_URL = 'http://127.0.0.1:11434'
$env:GITHUB_RANK_SUMMARY_DAILY_LIMIT = '20'
.\.venv\Scripts\python.exe -m github_rank.cli summarize --kind news --limit 5
```

`--kind` 支持 project、news、resource、all；每批 limit 为 1—100。all 在三类候选间轮流处理，避免项目用完预算后资讯一直得不到处理。

默认只有手动命令生成摘要。若希望 scheduler 在轮询后处理少量待摘要条目，额外设置 `GITHUB_RANK_AUTO_SUMMARY=true`；仍遵守统一每日上限。Web 服务应使用相同设置启动，以正确显示配置状态。

每日上限按北京时间自然日计数，包含失败调用；缓存命中不消耗调用额度。该上限控制调用次数，并不等同于固定 Token 费用；记录实际输入/输出 Token 供评估。模型输出上限和输入片段长度同时受限。

Docker 中的 127.0.0.1 指向容器本身。容器使用摘要功能时，应配置容器可访问的自托管 Ollama HTTPS 地址；当前适配器只允许本机 HTTP 或远程 HTTPS，不在 URL 中携带凭证。此处不提供通用云厂商兼容性承诺。

## 来源、校验与展示

- 项目输入为描述与有限 README 片段；资讯输入为标题和原始摘要；资源输入为 manifest 的原始描述。
- 不给模型提供工具或执行权限，明确把资料内的指令视作不可信数据。
- 模型须返回结构化中文介绍和逐字原文引用；source_id 必须属于本次输入，引用不得翻译或编造。
- 拒绝不符合格式、缺乏中文、引入 URL/HTML 或引用不存在的结果；失败时保留原文模式。
- 页面显示“AI 中文摘要”，可展开查看引用、来源链接、模型和生成时间。引用逐字相符不等于语义一定正确，仍应对照原文抽查。
- 缓存键包含实体、内容 hash、模型及提示词版本。描述/README/资源 commit 等输入变化后旧摘要不再展示，后续命令重新生成。
- 不覆盖原始描述；历史榜单快照不动态补入之后才生成的摘要。

## 当前验证边界

已验证：结构化请求、无工具调用、引用校验、缓存复用、输入变化失效、失败计入预算和每日调用上限。

待验证：选择实际模型后的中文表达、事实准确性、生成耗时、显存/内存占用及实际预算。未向生产数据库导入测试生成结果。

已提供 [固定输入评估包与报告](SUMMARY_EVALUATION.md)。可用 summary-eval prepare 按类型分层抽取，读取匹配输入的缓存输出，再人工审阅并运行 report。缺少真实输出时两项通过率保持空值；引用逐字匹配不代表事实准确。
