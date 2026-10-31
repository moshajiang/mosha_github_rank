"""Conservative event groups with local, audited curation overlays."""
from datetime import datetime, timezone, timedelta
import json
import uuid
from .db import dumps, utcnow
from .news import event_key, canonical_url, iso_date
from .classify import news_topic


RULE_VERSION = "news-events-v2"
REASONS = {"manual": "本机人工修订", "arxiv": "同一 arXiv 论文 ID，保留各版本原链接",
           "title": "同一 UTC 日期、规范化标题完全相同", "url": "原始链接独立成组"}


def news_items(db):
    with db.connect() as con:
        con.execute("BEGIN")
        rows = [dict(r) for r in con.execute("SELECT * FROM news ORDER BY published_at DESC,id")]
        overrides = {r["item_id"]: dict(r) for r in con.execute("SELECT * FROM news_event_overrides")}
    result = []
    for row in rows:
        item = {**json.loads(row["data"]), **{k: row[k] for k in ("id", "title", "url", "source_id", "topic", "published_at", "first_seen_at", "fetched_at", "content_hash")}}
        item["topic"] = news_topic(item["title"]+" "+item["summary"], item.get("source_kind", "official"))
        item["importance"] = 3 if item["topic"] in ("agents","models") else 2 if item["topic"] in ("research","multimodal") else 1
        item["topic_rule_version"] = "news-topics-v2"
        automatic = event_key(item["title"], item["url"], item["published_at"], item.get("source_kind", "official"))
        override = overrides.get(item["id"])
        method = "manual" if override else "arxiv" if automatic.startswith("arxiv:") else "title" if automatic.startswith("title-v2:") else "url"
        item["event_group_id"] = override["group_id"] if override else automatic
        item["grouping"] = {"method": method, "rule_version": RULE_VERSION, "reason": override["reason"] if override else REASONS[method],
                            "automatic_key": automatic, "updated_at": override["updated_at"] if override else None}
        result.append(item)
    return result


def report_reference(item):
    return {k: item.get(k) for k in ("id", "title", "url", "source_id", "source_name", "published_at", "published_precision")}


def grouped_item(item, peers, matching_count=None):
    return {**item, "related_reports": [report_reference(r) for r in peers if r["id"] != item["id"]],
            "report_count": len(peers), "source_count": len({r["source_id"] for r in peers}),
            "matching_report_count": matching_count if matching_count is not None else len(peers)}


def news_catalog(db, window="7d", topic="", source="", sort="latest", q="", now=None):
    now = now or datetime.now(timezone.utc)
    hours = {"24h":24, "7d":168, "30d":720, "all":None}[window]
    cutoff = now-timedelta(hours=hours) if hours else None
    groups, unknown = {}, []
    for item in news_items(db):
        groups.setdefault(item["event_group_id"], []).append(item)
    items = []
    for peers in groups.values():
        matching = []
        for item in peers:
            if topic and item["topic"] != topic or source and item["source_id"] != source or q.casefold() not in (item["title"]+" "+item["summary"]).casefold():
                continue
            stamp = iso_date(item["published_at"])
            if not stamp or window == "24h" and item.get("published_precision") == "day":
                unknown.append({**grouped_item(item, peers), "time_note": "来源仅提供日期，不进入精确 24 小时窗口" if stamp else "发布时间未知或不可解析"})
                continue
            published = datetime.fromisoformat(stamp)
            if published > now+timedelta(minutes=5) or cutoff and published < cutoff:
                continue
            matching.append(item)
        if matching:
            matching.sort(key=lambda r: (iso_date(r["published_at"]), r["id"]), reverse=True)
            items.append(grouped_item(matching[0], peers, len(matching)))
    items.sort(key=lambda r: ((r["importance"] if sort == "important" else 0), iso_date(r["published_at"]), r["id"]), reverse=True)
    return {"items":items, "total":len(items), "unknown_time":unknown, "unknown_time_total":len(unknown),
            "as_of":now.isoformat(timespec="seconds"), "window":window,
            "note":"按原始发布时间筛选；时间未知项独立展示。关联报道保留当前事件的全部来源，可能不在当前筛选范围内。"}


def edit_events(db, action, identifiers, reason):
    if action not in ("merge", "split", "reset"):
        raise ValueError("Unknown event action")
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValueError("A reason of 1 to 500 characters is required")
    identifiers = list(dict.fromkeys(identifiers))
    if not 1 <= len(identifiers) <= 50 or action == "merge" and len(identifiers) < 2:
        raise ValueError("Use 2 to 50 items for merge, or 1 to 50 for split/reset")
    with db.lease("collection"):
        items = news_items(db)
        by_id, by_url = {r["id"]:r for r in items}, {r["url"]:r for r in items}
        chosen = []
        for value in identifiers:
            item = by_id.get(value)
            if not item and value.startswith(("https://", "http://")):
                item = by_url.get(canonical_url(value))
            if not item:
                raise ValueError("News item not found: " + value[:100])
            chosen.append(item)
        selected = {r["id"] for r in chosen}
        if action == "merge" and len(selected) < 2:
            raise ValueError("Merge requires at least two distinct news items")
        if action == "merge":
            group_ids = {r["event_group_id"] for r in chosen}
            selected = {r["id"] for r in items if r["event_group_id"] in group_ids}
        if len(selected) > 500:
            raise ValueError("This operation would affect more than 500 items")
        operation, stamp = uuid.uuid4().hex, utcnow()
        merged_id = "manual:"+uuid.uuid4().hex
        with db.connect() as con:
            for item_id in sorted(selected):
                row = con.execute("SELECT * FROM news_event_overrides WHERE item_id=?",(item_id,)).fetchone()
                before = dict(row) if row else None
                after = None if action == "reset" else {"item_id":item_id, "group_id":merged_id if action == "merge" else "manual:"+uuid.uuid4().hex, "reason":reason.strip(), "updated_at":stamp}
                if after:
                    con.execute("INSERT INTO news_event_overrides VALUES(:item_id,:group_id,:reason,:updated_at) ON CONFLICT(item_id) DO UPDATE SET group_id=excluded.group_id,reason=excluded.reason,updated_at=excluded.updated_at",after)
                else:
                    con.execute("DELETE FROM news_event_overrides WHERE item_id=?",(item_id,))
                data = {"before":before, "after":after, "reason":reason.strip()}
                con.execute("INSERT INTO news_event_edits VALUES(?,?,?,?,?,?)",(uuid.uuid4().hex,operation,item_id,action,dumps(data),stamp))
    return {"operation_id":operation, "action":action, "affected_items":len(selected), "item_ids":sorted(selected)}


def edit_history(db, item_id, limit=100):
    rows = db.rows("SELECT * FROM news_event_edits WHERE item_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?",(item_id,limit))
    return [{**r,"data":json.loads(r["data"])} for r in rows]


def news_detail(db, item_id, version_hash=None):
    items = news_items(db)
    item = next((r for r in items if r["id"] == item_id),None)
    if not item:
        return None
    peers = [r for r in items if r["event_group_id"] == item["event_group_id"]]
    result = grouped_item(item,peers)
    versions = db.rows("SELECT content_hash,observed_at FROM news_versions WHERE item_id=? ORDER BY observed_at DESC,rowid DESC",(item_id,))
    result["versions"] = [{**r,"is_current":r["content_hash"] == item["content_hash"]} for r in versions]
    if version_hash:
        version = db.rows("SELECT data,observed_at FROM news_versions WHERE item_id=? AND content_hash=?",(item_id,version_hash))
        if not version:
            return None
        saved = json.loads(version[0]["data"])
        for key in ("title","summary","published_at","raw_published_at","published_precision","source_updated_at","related_repositories","source_kind","source_name","is_preprint"):
            if key in saved:
                result[key] = saved[key]
            elif key in ("raw_published_at","published_precision","source_updated_at"):
                result.pop(key,None)
        result["version_view"] = {"content_hash":version_hash,"observed_at":version[0]["observed_at"],"is_current":version_hash == item["content_hash"]}
        result["topic"] = news_topic(result["title"]+" "+result["summary"], result.get("source_kind", "official"))
    result["event_edits"] = edit_history(db,item_id,20)
    return result
