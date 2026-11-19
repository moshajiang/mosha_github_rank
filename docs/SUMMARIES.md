# 项目中文简介与摘要

项目卡片和详情可显示基于 GitHub 描述和 README 的中文简介，详情页同时保留原始描述和可展开的原文引用。书生·端砚 API 和 Ollama 共用来源校验、缓存与用量限制。

## 书生·端砚 API

把以下配置加入项目根目录的 `.env`。`GITHUB_RANK_SUMMARY_MODEL` 填平台模型列表中的模型 ID，留空使用已验证的 `intern-s2`。如需更换模型，先确认平台列出的协议和计费。 [书生·端砚接入文档](https://discovery.intern-ai.org.cn/token-plan/home?dockey=07-agent-tools.md) · [模型与计费](https://discovery.intern-ai.org.cn/token-plan/home?dockey=04-model-limits-and-pricing.md&tabIndex=3)

```dotenv
GITHUB_RANK_SUMMARY_PROVIDER=inkstone
GITHUB_RANK_SUMMARY_MODEL=intern-s2
GITHUB_RANK_INKSTONE_API_KEY=
GITHUB_RANK_SUMMARY_DAILY_LIMIT=20
GITHUB_RANK_AUTO_SUMMARY=false
```

在本机 `.env` 的 `GITHUB_RANK_INKSTONE_API_KEY` 一行填入密钥。该文件由 Git 忽略。Windows 快捷入口优先使用该文件，直接运行 Python 命令时同名进程环境变量优先。容器通过 Compose 环境变量读取。

双击 `更新.cmd` 可按到期规则采集并同步项目简介。只需补简介时，运行以下命令并刷新网页。 [一键更新说明](OPERATIONS.md#一键更新)

```powershell
.\.venv\Scripts\python.exe -m github_rank.cli summarize --kind project --limit 5
```

请求发送到 `https://discovery-api.intern-ai.org.cn/v1/chat/completions`，只提供条目原文与生成要求。默认处理公开 GitHub 项目。服务返回 HTTP 错误或请求超时时结束当前批次，已通过校验的简介继续可用。密钥缺失时命令返回 `not_configured`。

## 已有 Ollama 服务

有现成 Ollama 服务时可改用以下配置，模型名称填本机已安装的名称。 [Ollama Chat API](https://docs.ollama.com/api/chat) · [结构化输出](https://docs.ollama.com/capabilities/structured-outputs)

```powershell
$env:GITHUB_RANK_SUMMARY_PROVIDER = 'ollama'
$env:GITHUB_RANK_SUMMARY_MODEL = '填入本机已安装的模型名'
$env:GITHUB_RANK_SUMMARY_URL = 'http://127.0.0.1:11434'
$env:GITHUB_RANK_SUMMARY_DAILY_LIMIT = '20'
.\.venv\Scripts\python.exe -m github_rank.cli summarize --kind news --limit 5
```

容器中的 `127.0.0.1` 指向容器自身。使用 Ollama 时配置容器可访问的服务地址，远端 Ollama 地址使用 HTTPS。

## 批次、用量与缓存

`--kind` 支持 `project`、`news`、`resource` 和 `all`。每批最多尝试 1 至 100 条。书生·端砚默认处理项目，Ollama 默认轮流处理三个类型。按需配置 `GITHUB_RANK_AUTO_SUMMARY=true` 并重启采集器，可让调度按默认类型生成。

默认每天最多 20 次调用，按北京时间自然日计数，失败调用计入额度。缓存命中直接复用。书生·端砚单次输出限制为 650 Token，README 输入最多 6,000 字符。数据库记录响应提供的输入和输出 Token，实际费用按平台当时价格计算。

## 来源、校验与展示

- 项目输入为描述与有限 README 片段；资讯输入为标题和原始摘要；资源输入为 manifest 的原始描述。
- 不给模型提供工具或执行权限，明确把资料内的指令视作不可信数据。
- 模型须返回结构化中文介绍和逐字原文引用；source_id 必须属于本次输入，引用不得翻译或编造。
- 拒绝不符合格式、缺乏中文、引入 URL/HTML 或引用不存在的结果；失败时保留原文模式。
- 页面显示“AI 中文摘要”，可展开查看引用、来源链接、模型和生成时间。引用逐字相符不等于语义一定正确，仍应对照原文抽查。
- 缓存键包含实体、原文内容、模型及提示词版本。书生·端砚通过 `inkstone/模型ID` 和本机模型区分，离线评估的 `--model` 也使用该名称。原文变化后，后续生成才会补入与新原文匹配的简介。
- 不覆盖原始描述；历史榜单快照不动态补入之后才生成的摘要。

## 验证

书生-S2 已用真实公开仓库验证模型调用、原文引用和用量记录。自动化测试覆盖配置、输出校验、缓存复用、原文变化、额度和接口异常。Ollama 接口通过模拟验证。

可用 `summary-eval prepare` 分层抽取项目并加载匹配的真实缓存，人工审阅事实和实用性后，用 `summary-eval report` 汇总。 [固定输入评估包与报告](SUMMARY_EVALUATION.md)
