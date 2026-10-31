import argparse
import json
import time
import sys
from .db import Database
from .jobs import collect, register_sources
from .ranking import publish_rankings
from .settings import Settings
from .sources import source_states, set_enabled
from .summaries import summarize


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="GitHub Rank data tasks")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    task = commands.add_parser("collect")
    task.add_argument("--mode", choices=["all", "repositories", "news", "releases"], default="all")
    task.add_argument("--no-discovery", action="store_true")
    task.add_argument("--repo-limit", type=int)
    task.add_argument("--force", action="store_true")
    commands.add_parser("publish")
    backup = commands.add_parser("backup")
    backup.add_argument("path")
    schedule = commands.add_parser("schedule")
    schedule.add_argument("--interval", type=int, default=60, help="Due-task check interval in seconds")
    summaries = commands.add_parser("summarize")
    summaries.add_argument("--kind", choices=["all", "project", "news", "resource"], default="all")
    summaries.add_argument("--limit", type=int, default=10)
    sources = commands.add_parser("sources")
    sources.add_argument("action", choices=["list", "enable", "disable"], default="list", nargs="?")
    sources.add_argument("source_id", nargs="?")
    args = parser.parse_args()
    settings = Settings.from_env()
    db = Database(settings.db_path)
    register_sources(db, settings.config())
    if args.command == "init":
        print("Database and source configuration initialized")
    elif args.command == "publish":
        print(json.dumps(publish_rankings(db)))
    elif args.command == "backup":
        db.backup(args.path)
        print("Backup created")
    elif args.command == "collect":
        if args.repo_limit is not None and args.repo_limit < 1:
            parser.error("--repo-limit must be positive")
        print(json.dumps(collect(settings, db, args.mode, not args.no_discovery, args.repo_limit, args.force), ensure_ascii=False, indent=2))
    elif args.command == "summarize":
        if not 1 <= args.limit <= 100:
            parser.error("--limit must be between 1 and 100")
        print(json.dumps(summarize(settings, db, args.kind, args.limit), ensure_ascii=False, indent=2))
    elif args.command == "sources":
        if args.action != "list":
            if not args.source_id:
                parser.error("source_id is required for enable/disable")
            try:
                set_enabled(db, args.source_id, args.action == "enable")
            except ValueError as exc:
                parser.error(str(exc))
        print(json.dumps(source_states(db), ensure_ascii=False, indent=2))
    else:
        while True:
            # News sources have their own persisted due times; repository/release jobs run once daily after 08:00 CST.
            from datetime import datetime, timezone, timedelta
            local = datetime.now(timezone(timedelta(hours=8)))
            date = local.date().isoformat()
            runs = db.rows("SELECT started_at FROM job_runs WHERE kind='all' AND status IN ('ok','partial') ORDER BY started_at DESC LIMIT 1")
            last_day = datetime.fromisoformat(runs[0]["started_at"]).astimezone(timezone(timedelta(hours=8))).date().isoformat() if runs else None
            mode = "all" if local.hour >= 8 and last_day != date else "news"
            try:
                report = collect(settings, db, mode)
                if settings.summary_auto and settings.summary_model:
                    report["summaries"] = summarize(settings, db, limit=5)
                print(json.dumps({"id": report["id"], "status": report["status"], "errors": report["errors"]}), flush=True)
            except Exception as exc:
                print(json.dumps({"status": "failed", "error": str(exc)[:300]}), flush=True)
            time.sleep(max(args.interval, 30))


if __name__ == "__main__":
    main()
