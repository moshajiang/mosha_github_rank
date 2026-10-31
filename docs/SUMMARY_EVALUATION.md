# 摘要评估包

更新：2026-11-01。此流程生成可人工复核的本地 JSON 文件，不调用模型、不自动下载模型，也不写入模拟评分。

## 准备与报告

在项目根目录执行：

~~~powershell
.\.venv\Scripts\python.exe -m github_rank.cli summary-eval prepare --projects 30 --news 30 --resources 10 --output data/evaluations/sample.json
.\.venv\Scripts\python.exe -m github_rank.cli summary-eval report data/evaluations/sample.json --output data/evaluations/report.json
~~~

每种类型可选 0—100 条，总请求数须大于零，实际条目不足时报告真实数量。默认按项目分类/语言、资讯来源/主题、资源类型/生态确定性轮流抽取，不等同于随机抽样或对全部 GitHub 的代表性评估。项目排除、归档、禁用和 Fork 不进入项目样本；排除项目的资源也不进入资源样本。

每条样本包含原始输入、输入 SHA-256、实体 ID、链接、候选输出、缓存模型/提示词版本/生成时间，以及人工审阅字段。只读取输入 hash 与当前提示词版本匹配的已有摘要。可指定 --model 模型名，避免将不同模型输出混合评价；不指定时每条选最新匹配缓存，可能来自不同模型。

没有候选输出时 candidate 为 null，状态为 missing_outputs；自动有效率和人工通过率没有分母时均为 null，不补成 0 或 100%。如需实测模型，先按 [摘要说明](SUMMARIES.md) 配置已有服务并生成摘要，再准备包含匹配输出的评估包。两个包只对相同实体、相同输入 hash 的结果作比较；采集期间输入变化不能当作同一评估条件。

## 人工复核

保留输入与候选原文，逐条核对：

| 字段 | 审阅问题 |
| --- | --- |
| facts_supported | 用途、功能及限定条件是否均获给定资料支持？ |
| chinese_clear | 中文表达是否清楚，是否保留必要的原文限定？ |
| useful | 是否帮助读者判断项目或资讯是否值得继续查看？ |
| notes | 记录错误事实、遗漏、歧义和其他发现。 |

三个判断均需填 JSON true / false；未填完保持 awaiting_review，不计人工通过率。全部 true 为人工通过，任一 false 为人工不通过。候选引用必须逐字存在于输入，引用 URL 须与输入来源一致；格式或引用失败单列 invalid_output，不进入人工通过率。

报告按样本记录状态与错误，并汇总缺输出、输入变更/格式错误、输出错误、待审阅、已审阅及通过/拒绝。输入 hash 和样本 ID 用于发现误编辑，不是签名或防篡改证明；评估文件仍应保留可信来源。自动有效率只衡量格式和逐字引用校验，不证明语义事实准确，也不能替代人工审阅。

输入文件上限 10 MB，输出必须为尚不存在的 .json 文件，以保留旧评估结果。评估 prepare/report 不修改采集内容或注册来源；在当前 v5 数据库上无需迁移。真实耗时、内存、Token 量和费用仍需在配置模型后另行测量。

## 本轮实际结果

2026-10-31 已从真实数据库准备 30 项目、30 资讯、10 资源，共 70 条样本。文件保存在忽略版本控制的 data/evaluations/20261031-prepared.json，汇总在同目录 20261031-report.json。

实际摘要缓存为零：missing_outputs=70、generated=0、human_reviewed=0，两项通过率均为 null。生产库未写入测试摘要，没有声称完成真实模型质量评估。
