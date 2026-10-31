"""Observed net growth only. Never backfill missing history with current stars."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
from .db import dumps, utcnow


ALGORITHM = "potential-v1"


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def nearest(snapshots, target):
    if not snapshots:
        return None
    row = min(snapshots, key=lambda s: abs((dt(s["observed_at"]) - target).total_seconds()))
    return row if abs((dt(row["observed_at"]) - target).total_seconds()) <= 6 * 3600 else None


def percentile(value, values):
    if len(values) <= 1:
        return 0.5
    lower = sum(v < value for v in values)
    equal = sum(v == value for v in values)
    return (lower + (equal - 1) / 2) / (len(values) - 1)


def compute_rankings(db, window=7, as_of=None):
    snapshot_rows = db.rows("SELECT * FROM snapshots ORDER BY observed_at")
    latest = max((r["observed_at"] for r in snapshot_rows), default=None)
    timestamp = dt(as_of or latest or utcnow())
    by_repo = defaultdict(list)
    for row in snapshot_rows:
        if dt(row["observed_at"]) <= timestamp + timedelta(hours=6):
            by_repo[row["repo_id"]].append(row)
    result = []
    for record in db.rows("SELECT * FROM repositories"):
        repo = json.loads(record["data"])
        repo.pop("readme_excerpt", None)
        snapshots = by_repo[record["id"]]
        end = nearest(snapshots, timestamp)
        start = nearest(snapshots, timestamp - timedelta(days=window))
        previous = nearest(snapshots, timestamp - timedelta(days=2 * window))
        repo.update({"delta_stars": None, "delta_forks": None, "growth_rate": None,
                     "acceleration": None, "potential_score": None, "score_breakdown": None,
                     "hot_eligible": False, "potential_eligible": False,
                     "observed_since": min((s["observed_at"] for s in snapshots), default=None),
                     "history_points": len(snapshots), "window_days": window})
        reasons = []
        excluded = repo.get("archived") or repo.get("disabled") or repo.get("is_fork")
        if excluded:
            reasons.append("归档、禁用或 Fork 项目不进入默认榜单")
        if end and start:
            repo["delta_stars"] = end["stars"] - start["stars"]
            repo["delta_forks"] = end["forks"] - start["forks"]
            repo["growth_rate"] = repo["delta_stars"] / max(start["stars"], 100)
            repo["period_start"], repo["period_end"] = start["observed_at"], end["observed_at"]
            repo["hot_eligible"] = not excluded and repo["delta_stars"] > 0
            if repo["delta_stars"] <= 0:
                reasons.append("该周期没有正净增长")
        else:
            reasons.append(f"观察中：尚无完整 {window} 天端点")
        coverage = len({s["day"] for s in snapshots if timestamp - timedelta(days=2 * window, hours=6) <= dt(s["observed_at"]) <= timestamp + timedelta(hours=6)}) / (2 * window + 1)
        repo["coverage"] = min(coverage, 1)
        if end and start and previous:
            previous_delta = start["stars"] - previous["stars"]
            repo["acceleration"] = (repo["delta_stars"] - previous_delta) / max(abs(previous_delta), 20)
            days_push = max((timestamp - dt(repo["pushed_at"])).total_seconds() / 86400, 0) if repo.get("pushed_at") else math.inf
            threshold = 20 if window == 7 else 50
            if repo["hot_eligible"] and 50 <= end["stars"] <= 20_000 and repo["delta_stars"] >= threshold and days_push <= 30 and coverage >= .9:
                repo["potential_eligible"] = True
                repo["_features"] = [repo["growth_rate"], repo["acceleration"], max(repo["delta_forks"], 0),
                                     math.exp(-days_push / 30), .5 * bool(repo.get("has_readme")) + .5 * bool(repo.get("has_docs"))]
            else:
                reasons.append("未满足潜力榜的规模、增长、近期推送或覆盖率门槛")
        else:
            reasons.append(f"潜力评分需 {2 * window} 天双周期观测")
        repo["observation_note"] = "；".join(reasons) or "统计端点完整"
        result.append(repo)
    eligible = [r for r in result if r["potential_eligible"]]
    for repo in eligible:
        peers = [r for r in eligible if r["category"] == repo["category"]]
        scope = "同分类"
        if len(peers) < 30:
            peers, scope = eligible, "全站同周期"
        if len(peers) < 30:
            repo["potential_eligible"] = False
            repo["observation_note"] = "合格样本不足 30 个，暂不发布正式潜力分"
            continue
        features = repo["_features"]
        values = [percentile(features[i], [p["_features"][i] for p in peers]) for i in range(3)] + features[3:]
        names, weights = ["增长率", "加速度", "Fork 净增", "近期推送", "资料完备度"], [.4, .25, .15, .1, .1]
        repo["score_breakdown"] = [{"name": name, "value": round(value, 4), "contribution": round(100 * weight * value, 2)} for name, weight, value in zip(names, weights, values)]
        repo["potential_score"] = round(sum(100 * w * v for w, v in zip(weights, values)), 2)
        repo["score_scope"] = scope
        repo["score_peer_count"] = len(peers)
    for repo in result:
        repo.pop("_features", None)
    return {
        "as_of": timestamp.isoformat(timespec="seconds"), "window_days": window,
        "algorithm": ALGORITHM, "tracked_count": len(result),
        "stale": (datetime.now(timezone.utc) - timestamp).total_seconds() > 36 * 3600,
        "items": result,
    }


def publish_rankings(db):
    now = utcnow()
    outputs = []
    with db.connect() as con:
        for window in (7, 30):
            data = compute_rankings(db, window)
            run_id = f"{now}:{window}d"
            con.execute("INSERT OR IGNORE INTO ranking_runs VALUES(?,?,?,?,?)", (run_id, now, window, ALGORITHM, dumps(data)))
            outputs.append(run_id)
    return outputs
