"""Resolve browser-owned library references without storing personal state."""
import json
import re
from .db import utcnow
from .repositories import apply_override, overrides_by_repo
from .agent_resources import resource_items
from .news_events import news_items, grouped_item
from .summaries import annotate_summaries


def resolve_library(db, projects="", resources="", news=""):
    references = []
    for kind, value in (("project",projects),("resource",resources),("news",news)):
        ids = list(dict.fromkeys(value.split(","))) if value else []
        for item_id in ids:
            valid = bool(re.fullmatch(r"[a-f0-9]{32}",item_id)) if kind != "project" else bool(re.fullmatch(r"[1-9]\d{0,15}",item_id)) and int(item_id) <= 9007199254740991
            if not valid:
                raise ValueError("Invalid library reference")
            references.append((kind,item_id))
    if len(references)>200:
        raise ValueError("Resolve at most 200 references per request")
    by_kind = {kind:{} for kind in ("project","resource","news")}
    project_ids = [key for kind,key in references if kind=="project"]
    if project_ids:
        overrides = overrides_by_repo(db)
        placeholders = ",".join("?" for _ in project_ids)
        for row in db.rows(f"SELECT data,first_seen_at FROM repositories WHERE id IN ({placeholders})",project_ids):
            item = json.loads(row["data"])
            item = apply_override(item,overrides.get(item["id"]))
            item.pop("readme_excerpt",None)
            item["first_seen_at"] = row["first_seen_at"]
            by_kind["project"][str(item["id"])] = item
    if resources:
        by_kind["resource"] = {r["id"]:r for r in resource_items(db,include_excluded=True)}
    if news:
        items = news_items(db)
        groups = {}
        for item in items:
            groups.setdefault(item["event_group_id"],[]).append(item)
        by_kind["news"] = {r["id"]:grouped_item(r,groups[r["event_group_id"]]) for r in items}
    selected = {kind:[] for kind in by_kind}
    for kind,item_id in references:
        if item_id in by_kind[kind]:
            selected[kind].append(by_kind[kind][item_id])
    for kind,items in selected.items():
        annotate_summaries(db,items,kind)
    return {"as_of":utcnow(),"items":[{"type":kind,"id":item_id,
             "state":"missing" if item_id not in by_kind[kind] else "excluded" if by_kind[kind][item_id].get("ranking_excluded") else "current",
             "data":by_kind[kind].get(item_id)} for kind,item_id in references]}
