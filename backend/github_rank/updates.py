"""Run the due collection and project summary tasks from one local command."""
from .db import LeaseBusyError
from .jobs import collect
from .scheduler import scheduler_status
from .summaries import summarize


def update(settings, db, summary_limit):
    scheduler = scheduler_status(db)
    if scheduler["online"]:
        collection = {"status": "scheduled", "mode": scheduler.get("current_mode")}
        if collection["mode"] == "all":
            return {"collection": collection, "project_summaries": {"status": "deferred"}}
    else:
        try:
            result = collect(settings, db, mode="due")
        except LeaseBusyError:
            return {"collection": {"status": "busy"}, "project_summaries": {"status": "deferred"}}
        collection = {"status": result["status"], "mode": result["mode"], "run_id": result["id"],
                      "repositories": len(result["repositories"]),
                      "sources_updated": sum(source["status"] == "ok" for source in result["sources"]),
                      "errors": len(result["errors"])}

    try:
        summaries = summarize(settings, db, kind="project", limit=summary_limit)
    except LeaseBusyError:
        summaries = {"status": "busy"}
    return {"collection": collection, "project_summaries": summaries}
