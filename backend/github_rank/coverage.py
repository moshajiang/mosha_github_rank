"""Read-only coverage diagnostics against one SQLite snapshot and a fixed clock."""
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
import re
from .ranking import compute_rankings, dt, ELIGIBILITY_REASONS
from .repositories import apply_override, overrides_by_repo
from .scheduler import scheduler_status
from .sources import source_states


REFRESH_REASONS = {
    "metadata_stale": "元数据超过 36 小时未更新",
    "metadata_not_api": "最近元数据不是 GitHub API 来源",
    "resource_incomplete": "资源扫描不完整",
    "resource_scan_stale": "资源扫描过期或无观测日期",
}


class ReadView:
    def __init__(self, connection):
        self.connection = connection

    def rows(self, sql, params=()):
        return [dict(row) for row in self.connection.execute(sql, params)]


def coverage_report(db, limit=20, now=None):
    if type(limit) is not int or not 0 <= limit <= 100:
        raise ValueError("Candidate limit must be between 0 and 100")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Use a timezone-aware audit time")
    now = now.astimezone(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    with db.connect() as connection:
        connection.execute("BEGIN")
        view = ReadView(connection)
        overrides = overrides_by_repo(view)
        records = view.rows("SELECT * FROM repositories ORDER BY id")
        snapshots = view.rows("SELECT * FROM snapshots ORDER BY observed_at")
        resources = view.rows("SELECT * FROM resources")
        sources = source_states(view, now)
        scheduler = scheduler_status(view, now)
        current_points = [r for r in snapshots if dt(r["observed_at"]) <= now]
        latest = max((r["observed_at"] for r in current_points), key=dt, default=None)
        # Match the application's daily observation anchor while it is fresh.
        # A complete but expired historical window must not imply current readiness.
        rank_time = latest if latest and now-dt(latest)<=timedelta(hours=36) else stamp
        ranks = [compute_rankings(view, window, rank_time) for window in (7, 30)]
        summary_count = view.rows("SELECT count(*) AS n FROM summaries")[0]["n"]
    active, excluded = [], 0
    for row in records:
        item = apply_override(json.loads(row["data"]), overrides.get(row["id"]))
        if item["ranking_excluded"]:
            excluded += 1
            continue
        active.append((row, item))
    active_ids = {item["id"] for _, item in active}
    resource_data = [json.loads(row["data"]) for row in resources if row["repo_id"] in active_ids]
    earliest = min((r["observed_at"] for r in current_points), key=dt, default=None)
    days = sorted({r["day"] for r in current_points})
    day_span = (now.date()-dt(earliest).date()).days+1 if earliest else 0
    fields = ("language", "license", "pushed_at")
    unavailable = {key:sum(not item.get(key) or item[key] in ("未声明","NOASSERTION") for _, item in active) for key in fields}
    windows = []
    for rank in ranks:
        windows.append({
            "window_days": rank["window_days"], "as_of": rank["as_of"],
            "included": len(rank["items"]), "excluded": rank["excluded_count"],
            "hot_eligible": sum(r["hot_eligible"] for r in rank["items"]),
            "potential_eligible": sum(r["potential_eligible"] for r in rank["items"]),
            "blockers": {kind:dict(Counter(code for r in rank["items"] for code in r["eligibility_reasons"][kind])) for kind in ("hot","potential")},
        })
    candidates = []
    scan_states, stale_scans = Counter(), 0
    for row, item in active:
        agent = bool(item.get("agent_types") or item.get("resource_scan_report"))
        scan = item.get("resource_scan_report") or {}
        observed = scan.get("observed_at")
        scan_stale = not observed or now-dt(observed) > timedelta(hours=36)
        if agent:
            scan_states[item.get("resource_scan","not_scanned")] += 1
            stale_scans += scan_stale
        reasons = []
        if now-dt(row["updated_at"]) > timedelta(hours=36):
            reasons.append("metadata_stale")
        if item.get("data_source") != "github_api":
            reasons.append("metadata_not_api")
        if agent and item.get("resource_scan") != "complete":
            reasons.append("resource_incomplete")
        if agent and scan_stale:
            reasons.append("resource_scan_stale")
        if reasons and not (item.get("archived") or item.get("disabled") or item.get("is_fork")):
            candidates.append({"id":item["id"], "full_name":item["full_name"], "url":item["url"],
                               "updated_at":row["updated_at"], "reasons":reasons,
                               "unavailable_fields":[key for key in fields if not item.get(key) or item[key] in ("未声明","NOASSERTION")],
                               "resource_scan":item.get("resource_scan","not_scanned") if agent else "not_applicable"})
    candidates.sort(key=lambda item:("metadata_stale" not in item["reasons"], -len(item["reasons"]),dt(item["updated_at"]),item["id"]))
    return {
        "format":"github-rank-coverage", "version":1, "as_of":stamp,
        "repositories":{"tracked":len(records),"included":len(active),"excluded":excluded,
                        "metadata_fresh":sum(now-dt(row["updated_at"])<=timedelta(hours=36) for row,_ in active),
                        "metadata_stale":sum(now-dt(row["updated_at"])>timedelta(hours=36) for row,_ in active),
                        "data_sources":dict(Counter(item.get("data_source","unknown") for _,item in active)),
                        "unavailable_fields":unavailable},
        "history":{"snapshot_count":len(snapshots),"observed_days":len(days),"first_observation":earliest,
                   "last_observation":latest,"days_without_observation":max(day_span-len(days),0),
                   "stale":not latest or now-dt(latest)>timedelta(hours=36),
                   "current_endpoint_count":len(active)-windows[0]["blockers"]["hot"].get("missing_end",0),
                   "day_counts":dict(Counter(r["day"] for r in current_points))},
        "rankings":windows, "reason_labels":ELIGIBILITY_REASONS,
        "resources":{"included_records":len(resource_data),"excluded_records":len(resources)-len(resource_data),
                     "with_file_hash":sum(bool(re.fullmatch("[a-f0-9]{64}",r.get("content_hash") or "")) for r in resource_data),
                     "scan_repositories":dict(scan_states),"stale_or_undated_scans":stale_scans},
        "news_sources":{"total":len(sources),"freshness":dict(Counter(s["freshness"] for s in sources)),
                        "items":[{key:s.get(key) for key in ("id","name","enabled","status","freshness","last_success_at")} for s in sources]},
        "scheduler":{key:scheduler.get(key) for key in ("status","online","started_at","heartbeat_at","heartbeat_age_seconds")},
        "summary_cache_count":summary_count,
        "refresh_candidates":candidates[:limit], "refresh_candidate_total":len(candidates),
        "refresh_reason_labels":REFRESH_REASONS,
        "notes":[
            "新鲜快照以最近实际观测为统计端点；超过 36 小时则按报告当前时间检验，不以陈旧完整区间冒充当前榜。",
            "阻塞原因可重叠；全局有观测的日期不代表每个仓库当日都有数据。",
            "最近一条观测新鲜不代表全库新鲜，请同时查看当前端点覆盖和元数据过期项目数。",
            "未记录字段可能是来源未声明或页面降级，不直接等同于采集失败。",
            "扫描完整仅限该次默认分支、已支持的清单格式和扫描预算；旧扫描不表示当前完整。",
            "刷新只能补当前观测，无法补回过去的逐日快照。",
            "单个实时心跳与当前状态不能证明连续运行 48 小时。",
        ],
    }


def coverage_markdown(report):
    def text(value):
        return str(value).replace("\n"," ").replace("\r"," ").replace("|","\\|").replace("<","&lt;").replace(">","&gt;")
    rows = ["# GitHub Rank 数据覆盖体检","",f"统计时间：{report['as_of']}","",
            f"- 跟踪 {report['repositories']['tracked']} 个项目，手动排除 {report['repositories']['excluded']} 个。",
            f"- {report['history']['snapshot_count']} 条快照，实际观测 {report['history']['observed_days']} 个 UTC 日期。",
            f"- 最近观测：{report['history']['last_observation'] or '无'}；{'已过期' if report['history']['stale'] else '新鲜'}。",
            f"- 当前端点覆盖：{report['history']['current_endpoint_count']} / {report['repositories']['included']}；元数据过期项目：{report['repositories']['metadata_stale']}。",
            f"- 调度：{report['scheduler']['status']}；{'在线' if report['scheduler']['online'] else '离线'}。","",
            "## 榜单就绪情况","","| 窗口 | 统计端点 | 热门合格 | 潜力合格 |","| --- | --- | --- | --- |"]
    for window in report["rankings"]:
        rows.append(f"| {window['window_days']} 天 | {window['as_of']} | {window['hot_eligible']} | {window['potential_eligible']} |")
    rows.extend(["","## 阻塞原因","","| 窗口 | 榜单 | 原因 | 项目数 |","| --- | --- | --- | --- |"])
    for window in report["rankings"]:
        for kind, counts in window["blockers"].items():
            for code, count in sorted(counts.items()):
                rows.append(f"| {window['window_days']} 天 | {'热门' if kind=='hot' else '潜力'} | {report['reason_labels'][code]} | {count} |")
    rows.extend(["","## 字段与扫描","","- 未记录/未声明字段："+text(json.dumps(report["repositories"]["unavailable_fields"],ensure_ascii=False)),
                 "- 仓库数据来源："+text(json.dumps(report["repositories"]["data_sources"],ensure_ascii=False)),
                 "- 资源扫描状态："+text(json.dumps(report["resources"]["scan_repositories"],ensure_ascii=False)),
                 f"- 资源文件 hash 覆盖：{report['resources']['with_file_hash']} / {report['resources']['included_records']}。",
                 "- 资讯来源新鲜度："+text(json.dumps(report["news_sources"]["freshness"],ensure_ascii=False)),
                 "","## 待刷新候选","",
                 f"展示 {len(report['refresh_candidates'])} / {report['refresh_candidate_total']} 个候选；顺序优先过期记录、缺口数量、最早更新时间。","",
                 "| ID | 项目 | 原因 |","| --- | --- | --- |"])
    for item in report["refresh_candidates"]:
        rows.append(f"| {item['id']} | {text(item['full_name'])} | {'；'.join(report['refresh_reason_labels'][code] for code in item['reasons'])} |")
    rows.extend(["","## 口径","",*("- "+note for note in report["notes"]),""])
    return "\n".join(rows)
