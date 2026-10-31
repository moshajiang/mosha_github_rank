from datetime import datetime, timezone, timedelta
import json
import uuid
from itertools import zip_longest
from .collectors import collect_repo, discover, discover_from_list, github_json
from .db import dumps, utcnow
from .news import build_item, collect_source, store_item, parse_feed
from .ranking import publish_rankings
from .transport import Fetcher, RateLimited
from .sources import source_enabled
from .repositories import normalize_name


def register_sources(db, config):
    for source in config.get("news_sources", []):
        db.execute("INSERT INTO sources(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (source["id"], dumps(source)))


def add_repository(settings, db, name, fetcher=None):
    """Fetch one explicit candidate immediately without competing with the daily batch."""
    name = normalize_name(name)
    owned = fetcher is None
    fetcher = fetcher or Fetcher(db, settings.github_token)
    run_id = uuid.uuid4().hex
    report = {"requested_name": name, "repositories": [], "errors": []}
    try:
        with db.lease("collection"):
            db.execute("INSERT INTO job_runs VALUES(?,?,?,?,?,?)", (run_id, "manual_repository", utcnow(), None, "running", dumps(report)))
            try:
                repo = collect_repo(db, fetcher, name, settings.config().get("collection", {}).get("max_resource_files", 30))
                report["repositories"].append({"id": repo["id"], "name": repo["full_name"], "warnings": repo["warnings"], "resource_scan": repo["resource_scan"]})
            except Exception as exc:
                report["errors"].append({"source": name, "error": str(exc)[:300]})
                db.execute("UPDATE job_runs SET finished_at=?,status='failed',report=? WHERE id=?", (utcnow(), dumps(report), run_id))
                raise
            db.execute("UPDATE job_runs SET finished_at=?,status='ok',report=? WHERE id=?", (utcnow(), dumps(report), run_id))
            return {"id": run_id, "status": "ok", **report}
    finally:
        if owned:
            fetcher.close()


def collect(settings, db, mode="all", discovery=True, repo_limit=None, force=False, fetcher=None):
    config = settings.config()
    limits = config.get("collection", {})
    register_sources(db, config)
    fetcher_owned = fetcher is None
    fetcher = fetcher or Fetcher(db, settings.github_token)
    report = {"repositories": [], "sources": [], "discovery": [], "seed_lists": [], "errors": [], "token_configured": bool(settings.github_token)}
    run_id = uuid.uuid4().hex
    try:
        # One writer job at a time, even when news and repository tasks overlap.
        with db.lease("collection"):
            db.execute("INSERT INTO job_runs VALUES(?,?,?,?,?,?)", (run_id, mode, utcnow(), None, "running", dumps(report)))
            if mode in ("all", "repositories"):
                names = list(config.get("repositories", []))
                if discovery:
                    discoveries = []
                    for query in config.get("queries", []):
                        query = query.format(
                            recent_30=(datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat(),
                            recent_7=(datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat(),
                        )
                        try:
                            found, details = discover(fetcher, query, limits.get("search_per_query", 10))
                            discoveries.append(found)
                            report["discovery"].append(details)
                        except Exception as exc:
                            report["errors"].append({"source": "discovery", "error": str(exc)[:300]})
                            if isinstance(exc, RateLimited):
                                break
                    for url in config.get("seed_lists", []):
                        try:
                            found, details = discover_from_list(fetcher, url)
                            discoveries.append(found)
                            report["seed_lists"].append(details)
                        except Exception as exc:
                            report["errors"].append({"source": "seed_list", "error": str(exc)[:300]})
                    names.extend(name for row in zip_longest(*discoveries) for name in row if name)
                names = list({name.lower(): name for name in names}.values())
                # Refresh already tracked repositories before admitting newly discovered candidates.
                # Oldest metadata first keeps a bounded batch from starving its existing history.
                existing = [row["full_name"] for row in db.rows("SELECT full_name FROM repositories ORDER BY updated_at,id")]
                names = list({name.lower(): name for name in [*existing, *names]}.values())
                batch_limit = repo_limit or limits.get("max_repositories", 200)
                report["deferred_repositories"] = max(len(names) - batch_limit, 0)
                for name in names[:batch_limit]:
                    try:
                        repo = collect_repo(db, fetcher, name, limits.get("max_resource_files", 30))
                        report["repositories"].append({"name": repo["full_name"], "warnings": repo["warnings"], "resource_scan": repo["resource_scan"]})
                    except Exception as exc:
                        report["errors"].append({"source": name, "error": str(exc)[:300]})
                        if isinstance(exc, RateLimited):
                            break
                report["ranking_runs"] = publish_rankings(db)
            if mode in ("all", "news"):
                for source in config.get("news_sources", []):
                    if not source_enabled(db, source):
                        report["sources"].append({"id": source["id"], "status": "paused"})
                        continue
                    state = db.rows("SELECT last_checked_at FROM sources WHERE id=?", (source["id"],))[0]
                    if not force and state["last_checked_at"]:
                        elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(state["last_checked_at"])
                        if elapsed < timedelta(minutes=source.get("interval_minutes", 30)):
                            report["sources"].append({"id": source["id"], "status": "not_due"})
                            continue
                    try:
                        count = collect_source(db, fetcher, source, limits.get("news_items_per_source", 25))
                        now = utcnow()
                        db.execute("UPDATE sources SET last_checked_at=?,last_success_at=?,status='ok',error=NULL,item_count=? WHERE id=?", (now, now, count, source["id"]))
                        report["sources"].append({"id": source["id"], "status": "ok", "count": count})
                    except Exception as exc:
                        error = str(exc)[:300]
                        db.execute("UPDATE sources SET last_checked_at=?,status='error',error=? WHERE id=?", (utcnow(), error, source["id"]))
                        report["errors"].append({"source": source["id"], "error": error})
            if mode in ("all", "releases"):
                for name in config.get("repositories", [])[:limits.get("release_repositories", 3)]:
                    source_id = "release:" + name.lower()
                    source = {"id": source_id, "name": name + " Releases", "kind": "release", "url": "https://github.com/" + name + "/releases", "adapter": "github"}
                    db.execute("INSERT INTO sources(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (source_id, dumps(source)))
                    if not source_enabled(db, source):
                        report["sources"].append({"id": source_id, "status": "paused"})
                        continue
                    try:
                        releases = github_json(fetcher, f"/repos/{name}/releases?per_page=5")
                        for release in releases:
                            if release.get("draft"):
                                continue
                            item = build_item(source, name + " · " + (release.get("name") or release["tag_name"]), release["html_url"], release.get("body", "")[:1500], release.get("published_at"))
                            item["related_repositories"] = ["https://github.com/" + name]
                            store_item(db, item)
                        now = utcnow()
                        db.execute("UPDATE sources SET last_checked_at=?,last_success_at=?,status='ok',error=NULL,item_count=? WHERE id=?", (now, now, len(releases), source_id))
                        report["sources"].append({"id": source_id, "status": "ok", "count": len(releases)})
                    except Exception as exc:
                        if isinstance(exc, RateLimited):
                            try:
                                feed_source = {**source, "url": "https://github.com/" + name + "/releases.atom"}
                                items = parse_feed(feed_source, fetcher.get(feed_source["url"]))[:5]
                                for item in items:
                                    item["related_repositories"] = ["https://github.com/" + name]
                                    store_item(db, item)
                                now = utcnow()
                                db.execute("UPDATE sources SET last_checked_at=?,last_success_at=?,status='ok',error=NULL,item_count=? WHERE id=?", (now, now, len(items), source_id))
                                report["sources"].append({"id": source_id, "status": "ok", "count": len(items), "fallback": "releases.atom"})
                                continue
                            except Exception as fallback_exc:
                                exc = fallback_exc
                        db.execute("UPDATE sources SET last_checked_at=?,status='error',error=? WHERE id=?", (utcnow(), str(exc)[:300], source_id))
                        report["errors"].append({"source": source_id, "error": str(exc)[:300]})
            status = "partial" if report["errors"] else "ok"
            db.execute("UPDATE job_runs SET finished_at=?,status=?,report=? WHERE id=?", (utcnow(), status, dumps(report), run_id))
            return {"id": run_id, "status": status, **report}
    except BaseException:
        db.execute("UPDATE job_runs SET finished_at=?,status='failed',report=? WHERE id=?", (utcnow(), dumps(report), run_id))
        raise
    finally:
        if fetcher_owned:
            fetcher.close()
