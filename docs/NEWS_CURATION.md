# 资讯详情与事件修订

更新：2026-10-31。网页提供资讯详情和本地版本浏览，管理操作使用本机 CLI。来源摘要不是文章全文，始终保留原文链接。

## 详情与时间

/news/{id} 展示摘要、原发布时间和来源日期原值、独立更新时间、首次发现、抓取时间和来源当前状态。精确时间以北京时间显示，仅日期的条目不补造时分。published/updated 的区分参考 [Atom RFC 4287](https://www.rfc-editor.org/rfc/rfc4287)；抓取、发现和更新时间均不替代首次发布时间。

本地 news_versions 保存内容和解析元数据，不等于作者修改次数。版本列表进入 /news/{id}?version_hash=...；历史视图明确标注，且不使用之后生成的 AI 摘要。当前事件关联、人工分组和项目跟踪状态仍显示当前值，不重建过去的事件图。项目关联仅依据原文明确的 GitHub 链接。

## 自动分组 v2

- 官方 arXiv 域名下相同论文 ID 可关联版本链接，保留各版本 URL；参考 [arXiv identifier](https://info.arxiv.org/help/arxiv_identifier.html)。只识别链接中的 ID，不宣称论文已评审。
- 其他内容仅在同一 UTC 日期、足够长的规范化标题完全相同时关联。保留点号和连字符组成的版本词，5.1、51、5.2 不会因去标点而混合。
- 短标题、未知日期、无强 ID 的论文及跨语言标题默认分立，不自动做语义合并。

API 对旧条目计算生效规则，不改写原始资讯和版本。主题也按当前规则读取，修正 supervision 被误当成 vision 主题的问题；历史视图按自身内容分类。筛选决定组内代表报道，其他关联报道可超出当前筛选，时间各自标注。

source_count 按来源 ID 去重，report_count 表示报道条数，matching_report_count 表示当前筛选匹配数。不将转载数当作热度分。

## 本机命令

```powershell
.\.venv\Scripts\python.exe -m github_rank.cli news list --q agent --limit 50
.\.venv\Scripts\python.exe -m github_rank.cli news merge ID_A ID_B --reason '核对原文，确认为同一发布'
.\.venv\Scripts\python.exe -m github_rank.cli news split ID_A --reason '相同标题对应不同事件'
.\.venv\Scripts\python.exe -m github_rank.cli news reset ID_A --reason '恢复自动规则'
.\.venv\Scripts\python.exe -m github_rank.cli news history ID_A
```

支持条目 ID 或已采集原始 URL。merge 合并所选条目当前组的所有既有成员；每次最多 50 个标识、影响最多 500 条记录。split 将所选条目各自独立成组；reset 只清除所选覆盖。以后新增的其他条目不会自动加入人工组，需另行核对。

每次操作要求说明，原子保存前后值、操作 ID 和时间，并保留审计。采集不覆盖人工组；操作与采集共用 collection 锁，繁忙时明确报错。原始文章、发布时间、采集版本与榜单归档不受修订影响。

GET /api/news 使用生效分组；GET /api/news/{id} 返回来源状态、项目关联、版本、分组依据和修订记录，version_hash 可选择本地版本。Web 仍为只读。

## 验证范围

backend/tests/fixtures/news_event_pairs.json 包含人工设计的 25 对、50 条受控条目，覆盖同标题、模型版本、arXiv、域名伪装、时区、短标题和跨语言。这是规则回归，不是独立真实资讯准确率评估。

已验证整组合并、拆分/重置、刷新保留、源数据不改写、时间精度、历史读取、原文关联、CLI、迁移和审计。真实跨语言质量、自动撤回识别、可信度评分及网页修订表单仍待后续实现。
