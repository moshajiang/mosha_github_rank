import argparse
import json
import sys
import signal
from .db import Database
from .jobs import collect, register_sources, add_repository
from .ranking import publish_rankings
from .settings import Settings
from .sources import source_states, set_enabled
from .summaries import summarize
from .classify import CATEGORIES, AGENT_TYPES
from .repositories import repository_items, edit_repository, edit_history
from .scheduler import Scheduler, scheduler_status, request_stop


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
    schedule_action = schedule.add_mutually_exclusive_group()
    schedule_action.add_argument("--status", action="store_true", help="Show persisted scheduler status")
    schedule_action.add_argument("--stop", action="store_true", help="Request a cooperative stop")
    schedule.add_argument("--once", action="store_true", help="Run one due-task check then exit")
    schedule.add_argument("--instance-id", help=argparse.SUPPRESS)
    summaries = commands.add_parser("summarize")
    summaries.add_argument("--kind", choices=["all", "project", "news", "resource"], default="all")
    summaries.add_argument("--limit", type=int, default=10)
    sources = commands.add_parser("sources")
    sources.add_argument("action", choices=["list", "enable", "disable"], default="list", nargs="?")
    sources.add_argument("source_id", nargs="?")
    projects = commands.add_parser("projects", help="Manage tracked repositories and local curation")
    project_actions = projects.add_subparsers(dest="action", required=True)
    project_actions.add_parser("list")
    add = project_actions.add_parser("add", help="Immediately collect one public GitHub repository")
    add.add_argument("repository")
    edit = project_actions.add_parser("set", help="Apply a persistent local classification or visibility override")
    edit.add_argument("repository")
    edit.add_argument("--category", choices=CATEGORIES)
    edit.add_argument("--agent-types", nargs="*", choices=AGENT_TYPES, help="Replace all Agent types; no values clears them")
    visibility = edit.add_mutually_exclusive_group()
    visibility.add_argument("--exclude", dest="excluded", action="store_const", const=True, default=None)
    visibility.add_argument("--include", dest="excluded", action="store_const", const=False)
    edit.add_argument("--reason", required=True)
    reset = project_actions.add_parser("reset", help="Remove overrides and use the current automatic classification")
    reset.add_argument("repository")
    reset.add_argument("--reason", required=True)
    history = project_actions.add_parser("history")
    history.add_argument("repository")
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
    elif args.command == "projects":
        try:
            if args.action == "add":
                output = add_repository(settings, db, args.repository)
            elif args.action == "set":
                item = edit_repository(db, args.repository, category=args.category, agent_types=args.agent_types,
                                       excluded=args.excluded, reason=args.reason)
                output = {k: item[k] for k in ("id", "full_name", "category", "agent_types", "ranking_excluded", "classification")}
            elif args.action == "reset":
                item = edit_repository(db, args.repository, reason=args.reason, reset=True)
                output = {k: item[k] for k in ("id", "full_name", "category", "agent_types", "ranking_excluded", "classification")}
            elif args.action == "history":
                output = edit_history(db, args.repository)
            else:
                output = [{k: item[k] for k in ("id", "full_name", "category", "agent_types", "ranking_excluded", "classification")}
                          for item in repository_items(db, include_excluded=True)]
        except (ValueError, RuntimeError) as exc:
            parser.error(str(exc))
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        if args.status:
            print(json.dumps(scheduler_status(db), ensure_ascii=False, indent=2))
        elif args.stop:
            print(json.dumps({"stop_requested": request_stop(db)}, ensure_ascii=False))
        else:
            runner = Scheduler(settings, db, interval=args.interval, instance_id=args.instance_id)
            previous = signal.signal(signal.SIGTERM, lambda *_: runner.stop_event.set())
            try:
                runner.run(max_cycles=1 if args.once else None)
            except RuntimeError as exc:
                parser.error(str(exc))
            finally:
                signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    main()
