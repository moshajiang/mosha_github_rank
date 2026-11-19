"""Resume Agent resource coverage in small, auditable batches."""
from collections import Counter
import json
import uuid

from .agent_resources import last_complete_scan
from .collectors import collect_repo
from .db import dumps, utcnow
from .repositories import apply_override, overrides_by_repo, resolve_repository
from .transport import CollectionCancelled, Fetcher, FetchError, RateLimited


MAX_RESCAN_REPOSITORIES = 30
STOP_MESSAGES = {
    "github_api_limit": "GitHub REST API rate or batch limit reached",
    "batch_resource_budget": "Resource request budget reached for this batch",
    "resource_rate_limit": "Resource file host rate limit reached",
    "cancelled": "Collection was cancelled",
    "interrupted": "Collection was interrupted",
}


def plan_rescan(db, names=(), limit=10):
    if not 1 <= limit <= MAX_RESCAN_REPOSITORIES:
        raise ValueError(f"Limit must be between 1 and {MAX_RESCAN_REPOSITORIES}")
    with db.read_view() as view:
        overrides = overrides_by_repo(view)
        counts = {row["repo_id"]: row["n"] for row in view.rows(
            "SELECT repo_id,count(*) AS n FROM resources GROUP BY repo_id"
        )}
        if names:
            selected = {}
            for name in names:
                row = resolve_repository(view, name)
                if row is None:
                    raise ValueError(f"Repository is not tracked: {name}")
                selected[row["id"]] = row
            rows = selected.values()
        else:
            rows = view.rows("SELECT id,full_name,data,updated_at FROM repositories")

    candidates = []
    for row in rows:
        repo = apply_override(json.loads(row["data"]), overrides.get(row["id"]))
        if repo["ranking_excluded"] or repo.get("archived") or repo.get("disabled") or repo.get("is_fork"):
            if names:
                raise ValueError(f"Repository is excluded, archived, disabled or a fork: {row['full_name']}")
            continue
        scan = repo.get("resource_scan_report") or {}
        known_resources = counts.get(row["id"], 0)
        status = repo.get("resource_scan", "not_scanned")
        if not names and (status == "complete" or not (repo["agent_types"] or scan or known_resources)):
            continue
        previous = last_complete_scan(repo)
        candidates.append({
            "id": row["id"], "name": row["full_name"], "previous_scan_status": status,
            "known_resources": known_resources, "candidate_files": scan.get("candidate_files"),
            "last_scan_at": scan.get("observed_at") or row["updated_at"],
            "previous_complete": previous,
        })
    if not names:
        candidates.sort(key=lambda item: (
            bool(item["previous_complete"] and item["previous_complete"]["resource_count"] >= 2),
            item["known_resources"] < 2,
            item["last_scan_at"],
            item["id"],
        ))
    return {"status": "planned", "candidate_total": len(candidates), "candidates": candidates[:limit]}


def rescan_repositories(settings, db, names=(), limit=10, *, fetcher=None):
    limits = settings.config().get("collection", {})
    owned = fetcher is None
    fetcher = fetcher or Fetcher(
        db, settings.github_token, resource_budget=limits.get("max_resource_requests_per_batch", 300)
    )
    try:
        with db.lease("collection"):
            plan = plan_rescan(db, names, limit)
            report = {
                "id": uuid.uuid4().hex, "started_at": utcnow(), "status": "running",
                "candidate_total": plan["candidate_total"],
                "repositories": [{**item, "status": "pending"} for item in plan["candidates"]],
                "errors": [], "stop_reason": None,
                "resource_request_limit": fetcher.resource_request_limit,
            }
            if not report["repositories"]:
                return {**report, "status": "no_candidates"}
            db.execute("INSERT INTO job_runs VALUES(?,?,?,?,?,?)",
                       (report["id"], "resource_rescan", report["started_at"], None, "running", dumps(report)))
            first_api_request = fetcher.github_requests
            first_resource_request = fetcher.resource_requests
            try:
                for item in report["repositories"]:
                    # A scan needs at least one branch lookup and one tree request.
                    if fetcher.github_core_limited:
                        report["stop_reason"] = "github_api_limit"
                        break
                    if fetcher.resource_request_limit - fetcher.resource_requests < 2:
                        report["stop_reason"] = "batch_resource_budget"
                        break
                    item["status"] = "running"
                    db.execute("UPDATE job_runs SET report=? WHERE id=?", (dumps(report), report["id"]))
                    try:
                        repo = collect_repo(
                            db, fetcher, item["name"], limits.get("max_resource_files", 30),
                            limits.get("max_tree_requests", 20), limits.get("max_tree_depth", 12),
                            force_resources=True, require_api=True, expected_id=item["id"],
                        )
                    except RateLimited as exc:
                        item.update(status="deferred", error=str(exc)[:300])
                        report["stop_reason"] = "github_api_limit"
                        break
                    except FetchError as exc:
                        item.update(status="failed", error=str(exc)[:300])
                        report["errors"].append({"source": item["name"], "error": item["error"]})
                    else:
                        scan = repo["resource_scan_report"]
                        item.update(name=repo["full_name"], status=scan["status"], commit=scan["commit"],
                                    tree_complete=scan["tree_complete"], candidate_files=scan["candidate_files"],
                                    read_files=scan["read_files"], invalid_files=scan["invalid_files"],
                                    resource_count=len(scan["resource_ids"]), reasons=scan["reasons"])
                        report["stop_reason"] = next(
                            (reason for reason in scan["reasons"] if reason in STOP_MESSAGES), None
                        )
                    db.execute("UPDATE job_runs SET report=? WHERE id=?", (dumps(report), report["id"]))
                    if report["stop_reason"]:
                        break
                statuses = {item["status"] for item in report["repositories"]}
                report["status"] = "ok" if statuses == {"complete"} else "partial"
            except (CollectionCancelled, KeyboardInterrupt):
                report.update(status="cancelled", stop_reason="cancelled")
                raise
            except BaseException:
                report.update(status="failed", stop_reason="interrupted")
                raise
            finally:
                for item in report["repositories"]:
                    if item["status"] in ("pending", "running"):
                        item["status"] = "deferred" if item["status"] == "pending" else "interrupted"
                        item["error"] = STOP_MESSAGES[report["stop_reason"]]
                report["counts"] = dict(Counter(item["status"] for item in report["repositories"]))
                report["complete_multiresource"] = sum(
                    item["status"] == "complete" and item["resource_count"] >= 2
                    for item in report["repositories"]
                )
                report["deferred_repositories"] = report["counts"].get("deferred", 0)
                report["github_requests"] = fetcher.github_requests - first_api_request
                report["resource_requests"] = fetcher.resource_requests - first_resource_request
                report["finished_at"] = utcnow()
                db.execute("UPDATE job_runs SET finished_at=?,status=?,report=? WHERE id=?",
                           (report["finished_at"], report["status"], dumps(report), report["id"]))
            return report
    finally:
        if owned:
            fetcher.close()
