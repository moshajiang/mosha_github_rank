# 同类项目与数据源调研

调研日期：2026-10-30。范围：项目官方页面、README、部分采集源码及官方接口文档。未运行第三方项目，未对其线上服务作完整功能测试；网页可见功能与源码结论分别说明。

## 1. 结论

已有接近需求的产品。值得借鉴的是分类榜单、中文摘要和 Agent 资源目录；本项目应集中做好“可解释的潜力发现 + 明确统计口径 + 中文速读 + Agent 资源细分”。这是一项产品取舍，不代表竞品完全没有相关功能。

建议独立实现轻量核心，参考公开设计，不直接整体 Fork 某个项目。原因是现有方案的数据口径、部署复杂度和资源粒度并不同时适配需求。

## 2. 已查看的同类项目

| 项目 | 已核实的功能或实现 | 可借鉴点 | 与本需求的差异 / 复用判断 |
| --- | --- | --- | --- |
| [GitHub Trending](https://github.com/trending) | 官方热门项目入口，提供日/周/月视图和语言筛选 | 发现近期热门的候选来源 | 页面榜单与本项目自算净增长分开标注；不能假设能通过官方 REST 接口直接获取同款 Trending 榜 |
| [encoreshao/github-trending](https://github.com/encoreshao/github-trending) | README 包含分类、周/月页、中文/英文与导出；MIT；采集使用 Search API | 最接近的轻量页面与定时快照方案 | 源码按创建时间筛选、按累计 Star 排序，不能直接用作区间增长榜 |
| [OSSInsight](https://github.com/pingcap/ossinsight) | 仓库分析、项目比较、分类排行；已有 [AI Agent 框架专题](https://ossinsight.io/collections/ai-agent-frameworks)；Apache-2.0 | 指标展示、分类集合与趋势分析 | 其事件分析体系较重；适合作为设计参考，首版不复制全量事件分析平台 |
| [Trendshift](https://trendshift.io/insights) | 趋势站提供周期入口、主题及月度洞察 | 趋势阅读、主题导航和生态观察 | 本次未核实可直接复用的完整站点源码或稳定数据授权；不作为唯一数据依赖 |
| [HelloGitHub](https://github.com/521xueweihan/HelloGitHub) | 分类介绍有趣、入门级项目；README 说明每月 28 日发布月刊 | 中文简洁介绍、发现有用的小项目 | 属于编辑精选思路；README 内容许可为 CC BY-NC-ND 4.0，不把其文案批量改写后作为本站内容 |
| [skills.sh](https://www.skills.sh/docs) | Skills 发现和安装目录；排行来自 CLI 安装遥测；存在 [API 文档](https://www.skills.sh/docs/api) | Skill 单体粒度、安装量指标、生态筛选 | 安装遥测只代表该渠道；当前 API 文档的认证依赖 Vercel OIDC，需接入验证，作为可选增强 |
| [m-fyi/awesome-agent-skills](https://github.com/m-fyi/awesome-agent-skills) | README 聚合 Skills、MCP、插件、子代理，并链接目录站 | Agent 资源类型划分与候选发现 | 属于聚合目录；逐项核实来源与指标，不能把仓库 Star 自动归属于单个 Skill |

### 最值得注意的源码发现

[github-trending 的 index.js](https://github.com/encoreshao/github-trending/blob/main/index.js) 中，`PERIODS` 的 daily / weekly / monthly 对应回溯创建时间 7 / 30 / 90 天；查询使用 `created:>=...` 和 `sort: stars`。因此其“周榜”主要回答“近 30 天创建的项目中，谁累计 Star 多”，与“最近 7 天谁增长快”是不同问题。

本项目应分别保留“新项目发现”和“区间增长排行”，避免混用名称。

## 3. 数据源可行性

| 来源 | 拟用信息 | 首版定位 | 约束 |
| --- | --- | --- | --- |
| GitHub Search API | 按 topic、描述、创建/推送时间、Star 区间发现候选 | 核心发现源 | 每次搜索最多返回 1,000 条；有单独搜索限流；分片查询也不能宣称覆盖全 GitHub |
| GitHub 仓库元数据、README、目录树 | 当前 Star/Fork、语言、许可证、推送时间、介绍、资源清单 | 核心事实源 | 保存每日观测；按变更获取较重内容，树截断时记录不完整 |
| GitHub Trending 页面 | 热门候选及页面提供的周期指标 | 可选补充 | HTML 可能变化；采集前核实访问规则，不能让其失败阻断主流程 |
| MCP 官方 Registry | MCP 服务名、版本、关联来源 | 可选专项发现源 | 先核实版本化 API 与分页；无 GitHub 来源的服务不进入 GitHub 仓库榜 |
| skills.sh API | 单个 Skill 的安装量及目录信息 | 可选增强 | 需满足其认证、使用条件；没有接通时不显示虚构安装数据 |
| GH Archive | 公共事件历史、扩大候选池 | 第二阶段评估 | 有小时归档和 BigQuery 数据集；存储/扫描成本和完整性需实测，事件计数不等于净 Star 增长 |
| Awesome Lists | 有针对性的候选链接 | 种子来源 | 去重、校验原仓库；不直接复用其长文介绍或把列表顺序视作排行 |

GitHub 官方文档：[Search](https://docs.github.com/en/rest/search/search)、[限流](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)、[仓库 Star 接口](https://docs.github.com/en/rest/activity/starring)。

认证 REST 常见主额度为 5,000 次/小时，未认证为 60 次/小时；搜索另有额度，文档列出的认证搜索通常为 30 次/分钟，代码搜索为 10 次/分钟。实现应读取实际响应头并退避，不能只写固定请求间隔。搜索还可能返回 `incomplete_results`。

### 2026 年的接口变化

GitHub [2026-06-30 公告](https://github.blog/changelog/2026-06-30-upcoming-access-restrictions-to-public-api-endpoints-and-ui-views/) 宣布限制 Star 用户列表等接口，当前 [Starring 文档](https://docs.github.com/en/rest/activity/starring) 也提示限制。因此不把遍历所有项目 stargazers、获取每个用户的 `starred_at` 作为历史补齐的前提。

首版使用当前总数的定期快照计算净变化。历史接口和第三方数据是否可用，在开发第一阶段做小规模验证；无法补齐时明确显示“开始观察日期”，不伪造过去的周/月增长。

### Agent 资源识别依据

- [Agent Skills 规范](https://agentskills.io/specification)：通过 `SKILL.md`、必要 frontmatter 与目录位置识别 Skill，保留原始文件证据。
- [MCP 官方 Registry](https://registry.modelcontextprotocol.io/)：发现服务与来源，不把收录视为质量担保。
- 插件通过各生态公开 manifest 和目录特征识别；“仓库含有一个 SKILL.md”本身不足以证明整个仓库是 Skills 产品。

## 4. 采用与暂缓

采用：中文 Web 界面、周期榜单、配置化分类、快照存储、原链接、资源级档案、基于 README 的有来源摘要。

暂缓：全量 GitHub 事件仓库、复杂个性化模型、自动安装/运行第三方插件、强制登录、多渠道消息推送。这些不会阻碍首版的发现与浏览流程。

尚待开发验证：Token 实际可访问的字段、候选池规模与漏检情况、主数据源耗时、skills.sh OIDC 接入、MCP Registry 的具体 API 合约、历史补齐成本。本文没有将其描述为已接通的功能。

## 5. 增补：AI 前沿资讯来源

根据新增需求，于 2026-10-30 查看以下官方入口。当前核实的是来源入口和公开说明，尚未验证每个站点的 feed 地址、内容再利用条件、分页及长期采集稳定性。

| 来源 | 已查看内容 | 方案中的用途 |
| --- | --- | --- |
| [OpenAI News](https://openai.com/news/) | 官方资讯入口与研究、产品等栏目 | 官方发布候选源，按技术主题过滤 |
| [Anthropic News](https://www.anthropic.com/news) | 官方新闻入口 | 模型、Agent 产品与研究动态 |
| [Google DeepMind](https://deepmind.google/blog/) | 官方研究与产品新闻入口 | 模型、多模态、具身智能和科学研究 |
| [Qwen 原博客](https://qwenlm.github.io/blog/) | 旧页面提示迁移至 qwen.ai | 接入时核实新入口，不将旧 feed 假定为持续更新源 |
| [arXiv RSS 文档](https://info.arxiv.org/help/rss.html) | 官方分类 RSS/Atom 使用说明 | AI/机器学习/NLP/视觉等研究候选；分类与端点在开发时验证 |
| [Hugging Face Trending Papers](https://huggingface.co/changelog/trending-papers) | 官方说明支持论文与代码发现，趋势参考近期 GitHub Star 活动 | 研究发现补充，不当作论文科学质量的独立验证 |

资讯模块与 GitHub 榜单使用不同排序和更新策略。官方发布优先溯源；社区热度只用于发现，同一事件的转载数量不能代替重要性或可信度。详见 [资讯专项方案](AI_NEWS_PLAN.md)。
