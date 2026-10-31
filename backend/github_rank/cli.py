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
from .news_events import news_items, edit_events, edit_history as news_edit_history
from .summary_eval import prepare_evaluation, evaluation_report, write_json


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
    evaluation = commands.add_parser("summary-eval",help="Prepare or report a manual summary evaluation without model calls")
    eval_actions = evaluation.add_subparsers(dest="eval_action",required=True)
    prepare = eval_actions.add_parser("prepare")
    prepare.add_argument("--projects",type=int,default=30)
    prepare.add_argument("--news",type=int,default=30)
    prepare.add_argument("--resources",type=int,default=10)
    prepare.add_argument("--model")
    prepare.add_argument("--output",required=True)
    report = eval_actions.add_parser("report")
    report.add_argument("input")
    report.add_argument("--output",required=True)
    sources = commands.add_parser("sources")
    sources.add_argument("action", choices=["list", "enable", "disable"], default="list", nargs="?")
    sources.add_argument("source_id", nargs="?")
    projects = commands.add_parser("projects", help="Manage tracked repositories and local curation")
    project_actions = projects.add_subparsers(dest="action", required=True)
    project_actions.add_parser("list")
    add = project_actions.add_parser("add", help="Immediately collect one public GitHub repository")
    add.add_argument("repository")
    add.add_argument("--scan-resources", action="store_true", help="Scan manifests even when Agent keyword classification did not match")
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
    news = commands.add_parser("news", help="Inspect and curate local news event groups")
    news_actions = news.add_subparsers(dest="news_action", required=True)
    listing = news_actions.add_parser("list")
    listing.add_argument("--q", default="")
    listing.add_argument("--limit", type=int, default=50)
    for action in ("merge", "split", "reset"):
        edit_news = news_actions.add_parser(action)
        edit_news.add_argument("items", nargs="+")
        edit_news.add_argument("--reason", required=True)
    news_history = news_actions.add_parser("history")
    news_history.add_argument("item_id")
    args = parser.parse_args()
    settings = Settings.from_env()
    db = Database(settings.db_path)
    if args.command != "summary-eval":
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
    elif args.command == "summary-eval":
        try:
            if args.eval_action=="prepare":
                packet=prepare_evaluation(db,args.projects,args.news,args.resources,args.model)
                write_json(args.output,packet)
                output={"selected":packet["selected"],"output":args.output,"note":"No model calls were made"}
            else:
                from pathlib import Path
                path=Path(args.input)
                if path.stat().st_size>10_000_000:
                    parser.error("Evaluation packet exceeds 10 MB")
                packet=json.loads(path.read_text(encoding="utf-8-sig"))
                output=evaluation_report(packet)
                write_json(args.output,output)
                output={k:v for k,v in output.items() if k!="samples"}
                output["output"]=args.output
            print(json.dumps(output,ensure_ascii=False,indent=2))
        except (ValueError,OSError) as exc:
            parser.error(str(exc))
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
                output = add_repository(settings, db, args.repository, force_resources=args.scan_resources)
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
    elif args.command == "news":
        try:
            if args.news_action == "list":
                if not 1 <= args.limit <= 500:
                    parser.error("--limit must be between 1 and 500")
                rows = [r for r in news_items(db) if args.q.casefold() in (r["title"]+" "+r["summary"]).casefold()]
                output = [{k:r[k] for k in ("id","title","source_name","published_at","url","event_group_id","grouping")} for r in rows[:args.limit]]
            elif args.news_action == "history":
                output = news_edit_history(db,args.item_id)
            else:
                output = edit_events(db,args.news_action,args.items,args.reason)
        except (ValueError, RuntimeError) as exc:
            parser.error(str(exc))
        print(json.dumps(output,ensure_ascii=False,indent=2))
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
