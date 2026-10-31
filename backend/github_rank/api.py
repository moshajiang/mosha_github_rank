from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import json
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from .classify import CATEGORIES, AGENT_TYPES, TOPICS
from .db import Database, utcnow
from .jobs import register_sources
from .ranking import compute_rankings
from .settings import Settings, ROOT
from .sources import source_states, source_events
from .summaries import annotate_summaries
from .identity import workspace_id
from .repositories import repository_items, resolve_repository, overrides_by_repo, apply_override, canonical_resource
from .scheduler import scheduler_status
from .agent_resources import enrich_resource, resource_items, resource_catalog, duplicate_key, with_duplicates
from .news_events import news_catalog, news_detail as get_news_detail
from .library import resolve_library


def create_app(settings=None):
    settings = settings or Settings.from_env()
    db = Database(settings.db_path)
    register_sources(db, settings.config())
    app = FastAPI(title="GitHub Rank", version="0.1.0")
    app.state.db = db

    def lookup_repository(name):
        try:
            record = resolve_repository(db, name)
        except ValueError:
            record = None
        if not record:
            raise HTTPException(404, "Project not found")
        return record

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0", "app_id": "github-rank",
                "workspace_id": workspace_id(ROOT),
                "instance_id": os.environ.get("GITHUB_RANK_DESKTOP_INSTANCE")}

    @app.get("/api/config")
    def config():
        languages = sorted({json.loads(row["data"]).get("language") for row in db.rows("SELECT data FROM repositories")} - {None, ""})
        return {"categories": CATEGORIES, "agent_types": AGENT_TYPES, "topics": TOPICS, "languages": languages}

    @app.get("/api/library")
    def library(projects: str = Query("",max_length=4000), resources: str = Query("",max_length=7000), news: str = Query("",max_length=7000)):
        try:
            return resolve_library(db,projects,resources,news)
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc

    @app.get("/api/runtime-status")
    def runtime_status():
        events = []
        for row in source_events(db):
            source = json.loads(row.pop("source_data"))
            events.append({**row, "source_name": source["name"]})
        now = datetime.now(timezone.utc)
        oldest = db.rows("SELECT min(updated_at) AS t FROM repositories")[0]["t"]
        return {"as_of": now.isoformat(timespec="seconds"), "scheduler": scheduler_status(db, now),
                "source_events": events, "oldest_repository_update": oldest,
                "repositories_stale": bool(oldest and now-datetime.fromisoformat(oldest) > timedelta(hours=36))}

    @app.get("/api/data-status")
    def data_status():
        counts = {}
        for table in ("repositories", "resources", "news", "snapshots", "summaries"):
            counts[table] = db.rows(f"SELECT count(*) AS n FROM {table}")[0]["n"]
        last_snapshot = db.rows("SELECT max(observed_at) AS t FROM snapshots")[0]["t"]
        last_news = db.rows("SELECT max(fetched_at) AS t FROM news")[0]["t"]
        jobs = db.rows("SELECT * FROM job_runs ORDER BY started_at DESC LIMIT 8")
        for job in jobs:
            job["report"] = json.loads(job["report"])
        return {"as_of": utcnow(), "counts": counts, "last_snapshot": last_snapshot,
                "last_news": last_news, "github_token_configured": bool(settings.github_token),
                "summary_mode": "ollama" if settings.summary_model else "template", "jobs": jobs,
                "summary_model_configured": bool(settings.summary_model),
                "summary_daily_limit": settings.summary_daily_limit,
                "summary_attempts_today": db.rows("SELECT count(*) AS n FROM summary_attempts WHERE day=?", (datetime.now(timezone(timedelta(hours=8))).date().isoformat(),))[0]["n"],
                "note": "已跟踪候选池排行；不代表全部 GitHub。无完整历史时显示观察中。"}

    def repositories(q="", category="", language="", agent_type="", min_stars=0, max_stars=None):
        items = []
        for repo in repository_items(db):
            repo.pop("readme_excerpt", None)
            haystack = (repo["full_name"] + " " + repo["description"] + " " + " ".join(repo.get("topics", []))).lower()
            language_matches = not language or language == "__unknown__" and not repo.get("language") or repo.get("language") == language
            if q.lower() not in haystack or category and repo["category"] != category or not language_matches:
                continue
            if agent_type == "any" and not repo.get("agent_types") or agent_type not in ("", "any") and agent_type not in repo.get("agent_types", []):
                continue
            if repo["stars"] >= min_stars and (max_stars is None or repo["stars"] <= max_stars):
                items.append(repo)
        return sorted(items, key=lambda r: (-r["stars"], r["id"]))

    @app.get("/api/projects")
    def projects(q: str = Query("", max_length=200), category: str = "", language: str = "",
                 agent_type: str = "", min_stars: int = Query(0, ge=0), max_stars: int | None = Query(None, ge=0), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
        if max_stars is not None and max_stars < min_stars:
            raise HTTPException(422, "max_stars must be at least min_stars")
        items = repositories(q, category, language, agent_type, min_stars, max_stars)
        return {"items": annotate_summaries(db, items[offset:offset + limit], "project"), "total": len(items), "sort": "current_stars"}

    @app.get("/api/projects/{owner}/{repo}/history")
    def project_history(owner: str, repo: str):
        record = lookup_repository(owner + "/" + repo)
        return {"items": db.rows("SELECT * FROM snapshots WHERE repo_id=? ORDER BY observed_at", (record["id"],)),
                "full_name": record["full_name"], "method": "daily_observed_totals"}

    @app.get("/api/projects/{owner}/{repo}")
    def project_detail(owner: str, repo: str):
        name = owner + "/" + repo
        record = lookup_repository(name)
        data = apply_override(json.loads(record["data"]), overrides_by_repo(db).get(record["id"]))
        annotate_summaries(db, [data], "project")
        data.pop("readme_excerpt", None)
        data["requested_name"] = name
        data["aliases"] = [r["full_name"] for r in db.rows("SELECT full_name FROM repository_aliases WHERE repo_id=? ORDER BY full_name", (record["id"],))]
        data["resources"] = [enrich_resource(json.loads(r["data"]), data) for r in db.rows("SELECT data FROM resources WHERE repo_id=?", (record["id"],))]
        project_url = data["url"].rstrip("/").lower()
        project_urls = {project_url, *("https://github.com/" + alias.lower() for alias in data["aliases"])}
        data["related_news"] = []
        for news in db.rows("SELECT data FROM news ORDER BY published_at DESC LIMIT 1000"):
            item = json.loads(news["data"])
            if project_urls.intersection(u.rstrip("/").lower() for u in item.get("related_repositories", [])):
                data["related_news"].append(item)
        return data

    @app.get("/api/rankings")
    def rankings(kind: Literal["hot", "potential"] = "hot", window: Literal["7d", "30d"] = "7d",
                 category: str = "", agent_type: str = "", q: str = Query("", max_length=200),
                 run_id: str | None = None, limit: int = Query(100, ge=1, le=500),
                 language: str = "", min_stars: int = Query(0, ge=0), max_stars: int | None = Query(None, ge=0)):
        if max_stars is not None and max_stars < min_stars:
            raise HTTPException(422, "max_stars must be at least min_stars")
        days = 7 if window == "7d" else 30
        if run_id:
            rows = db.rows("SELECT data FROM ranking_runs WHERE id=? AND window_days=?", (run_id, days))
            if not rows:
                raise HTTPException(404, "Ranking snapshot not found")
            data = json.loads(rows[0]["data"])
        else:
            data = compute_rankings(db, days)
        items = [r for r in data["items"] if (not category or r["category"] == category)
                 and (not agent_type or agent_type == "any" and r["agent_types"] or agent_type in r["agent_types"])
                 and q.lower() in (r["full_name"] + " " + r["description"]).lower()
                 and (not language or language == "__unknown__" and not r.get("language") or r.get("language") == language)
                 and r["stars"] >= min_stars and (max_stars is None or r["stars"] <= max_stars)]
        formal = [r for r in items if r[f"{kind}_eligible"]]
        formal.sort(key=lambda r: (-(r["potential_score"] if kind == "potential" else r["delta_stars"]), -(r["delta_forks"] or 0), r["id"]))
        for i, r in enumerate(formal, 1):
            r["rank"] = i
        observed = sorted([r for r in items if not r[f"{kind}_eligible"] and not r.get("archived") and not r.get("is_fork")], key=lambda r: (-r["stars"], r["id"]))
        if not run_id:
            annotate_summaries(db, formal[:limit], "project")
            annotate_summaries(db, observed[:limit], "project")
        return {**{k: v for k, v in data.items() if k != "items"}, "kind": kind,
                "items": formal[:limit], "total": len(formal), "observing": observed[:limit],
                "observing_total": len(observed), "run_id": run_id,
                "note": "观察列表按当前总 Star 排序，不是区间增长榜。"}

    @app.get("/api/agent-resources")
    def agent_resources(kind: Literal["", "skill", "plugin", "mcp"] = "", q: str = Query("", max_length=200),
                        limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0, le=100000), group_duplicates: bool = True):
        result, matched = resource_catalog(db, kind, q, group_duplicates)
        return {"items": annotate_summaries(db, result[offset:offset+limit], "resource"), "total": len(result), "offset": offset,
                "matching_source_total": matched, "group_duplicates": group_duplicates,
                "note": "同类型、文件字节相同的资源合并展示，来源可展开；仓库 Star 不代表资源安装或使用量。"}

    @app.get("/api/agent-resources/{resource_id}")
    def resource(resource_id: str):
        items = resource_items(db, include_excluded=True)
        item = next((r for r in items if r["id"] == resource_id), None)
        if not item:
            raise HTTPException(404, "Resource not found")
        peers = [r for r in items if duplicate_key(r) == duplicate_key(item) and (not r["ranking_excluded"] or r["id"] == resource_id)]
        return annotate_summaries(db, [with_duplicates(item, peers)], "resource")[0]

    @app.get("/api/news/sources")
    def news_sources():
        return {"items": source_states(db)}

    @app.get("/api/news")
    def news(window: Literal["24h", "7d", "30d", "all"] = "7d", topic: str = "", source: str = "",
             sort: Literal["latest", "important"] = "latest", q: str = Query("", max_length=200),
             limit: int = Query(100, ge=1, le=500)):
        data = news_catalog(db, window, topic, source, sort, q)
        data["items"] = annotate_summaries(db, data["items"][:limit], "news")
        data["unknown_time"] = annotate_summaries(db, data["unknown_time"][:limit], "news")
        return data

    @app.get("/api/news/{item_id}")
    def news_detail(item_id: str, version_hash: str | None = Query(None, pattern="^[a-f0-9]{64}$")):
        data = get_news_detail(db, item_id, version_hash)
        if not data:
            raise HTTPException(404, "News item or local version not found")
        if not data.get("version_view") or data["version_view"]["is_current"]:
            annotate_summaries(db, [data], "news")
        data["source_state"] = next((r for r in source_states(db) if r["id"] == data["source_id"]), None)
        data["related_projects"] = []
        for url in data.get("related_repositories", []):
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.hostname != "github.com" or parts.username or parts.password:
                continue
            name = parts.path.strip("/")
            try:
                record = resolve_repository(db, name)
            except ValueError:
                continue
            data["related_projects"].append({"full_name":record["full_name"] if record else name,
                                             "url":json.loads(record["data"])["url"] if record else url,
                                             "tracked":bool(record)})
        return data

    @app.get("/api/archives")
    def archives():
        return {"items": db.rows("SELECT id,created_at,window_days,algorithm FROM ranking_runs ORDER BY created_at DESC LIMIT 100")}

    @app.get("/api/exports")
    def export(run_id: str | None = None, format: Literal["json", "markdown"] = "json",
               kind: Literal["hot", "potential"] = "hot", window: Literal["7d", "30d"] = "7d",
               q: str = "", category: str = "", agent_type: str = "", language: str = "",
               min_stars: int = Query(0, ge=0), max_stars: int | None = Query(None, ge=0)):
        data = rankings(kind=kind, window=window, run_id=run_id, limit=500, q=q, category=category,
                        agent_type=agent_type, language=language, min_stars=min_stars, max_stars=max_stars)
        if format == "json":
            return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                            headers={"Content-Disposition": 'attachment; filename="github-rank.json"'})
        lines = [f"# GitHub Rank · {window} · {kind}", "", f"数据截至：{data['as_of']}", ""]
        for item in data["items"]:
            lines.extend([f"- [{item['full_name']}]({item['url']})：净增 {item['delta_stars']} Star。{item['summary']}"])
        if not data["items"]:
            lines.append("完整历史不足，暂无正式榜单。")
        return Response("\n".join(lines), media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="github-rank.md"'})

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Endpoint not found")
        dist = ROOT / "frontend/dist"
        target = (dist / path).resolve()
        if not target.is_relative_to(dist.resolve()):
            raise HTTPException(404)
        if target.is_file():
            return FileResponse(target)
        if (dist / "index.html").exists():
            return FileResponse(dist / "index.html")
        return {"message": "Build frontend with npm run build in frontend/", "api_docs": "/docs"}

    return app
