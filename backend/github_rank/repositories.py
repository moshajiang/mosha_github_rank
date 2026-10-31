"""Local curation overlays and observed GitHub identities; raw metadata stays intact."""
import json
import re
import uuid
from urllib.parse import urlsplit, quote
from .classify import CATEGORIES, AGENT_TYPES
from .db import dumps, utcnow


REPO_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


def normalize_name(value):
    value = value.strip()
    if value.startswith("https://"):
        parts = urlsplit(value)
        if parts.netloc.lower() != "github.com" or parts.query or parts.fragment:
            raise ValueError("Use a GitHub repository URL without credentials, query or fragment")
        value = parts.path.strip("/")
    if value.endswith(".git"):
        value = value[:-4]
    if not REPO_NAME.fullmatch(value) or any(p in (".", "..") for p in value.split("/")):
        raise ValueError("Use owner/repository or https://github.com/owner/repository")
    return value


def resolve_repository(db, name):
    name = normalize_name(name)
    # A newly created repository can reuse an old name. Its current identity wins.
    current = db.rows("SELECT * FROM repositories WHERE full_name=? COLLATE NOCASE", (name,))
    if current:
        return current[0]
    aliases = db.rows("SELECT r.* FROM repository_aliases a JOIN repositories r ON r.id=a.repo_id WHERE a.full_name=? COLLATE NOCASE", (name,))
    return aliases[0] if aliases else None


def record_aliases(con, repo_id, canonical_name, names, observed_at):
    con.execute("DELETE FROM repository_aliases WHERE full_name=? COLLATE NOCASE", (canonical_name,))
    for name in names:
        if not name or name.lower() == canonical_name.lower():
            continue
        occupied = con.execute("SELECT id FROM repositories WHERE full_name=? COLLATE NOCASE", (name,)).fetchone()
        if occupied:
            continue
        con.execute("INSERT INTO repository_aliases VALUES(?,?,?) ON CONFLICT(full_name) DO UPDATE SET repo_id=excluded.repo_id,observed_at=excluded.observed_at", (name, repo_id, observed_at))


def overrides_by_repo(db):
    return {row["repo_id"]: row for row in db.rows("SELECT * FROM repository_overrides")}


def apply_override(repo, override=None):
    item = repo.copy()
    automatic = {"category": repo["category"], "agent_types": list(repo.get("agent_types", []))}
    if override:
        if override["category"] is not None:
            item["category"] = override["category"]
        if override["agent_types"] is not None:
            item["agent_types"] = json.loads(override["agent_types"])
    item["ranking_excluded"] = bool(override and override["excluded"])
    item["classification"] = {
        "method": "manual" if override and (override["category"] is not None or override["agent_types"] is not None) else "rules",
        "automatic": automatic,
        "reason": override["reason"] if override else None,
        "updated_at": override["updated_at"] if override else None,
    }
    if item.get("summary_method") == "template":
        item["summary"] = f"一个{CATEGORIES[item['category']]}项目。" + (f"主要使用 {item['language']} 开发。" if item.get("language") else "") + "具体功能见作者原始介绍。"
    return item


def repository_items(db, include_excluded=False):
    overrides = overrides_by_repo(db)
    items = []
    for row in db.rows("SELECT data,first_seen_at FROM repositories ORDER BY full_name COLLATE NOCASE"):
        item = json.loads(row["data"])
        item = apply_override(item, overrides.get(item["id"]))
        item["first_seen_at"] = row["first_seen_at"]
        if include_excluded or not item["ranking_excluded"]:
            items.append(item)
    return items


def canonical_resource(item, repo):
    item = item.copy()
    item["repo_name"] = repo["full_name"]
    # Keep the evidence commit and file path, only follow the observed repository identity.
    item["url"] = f"https://github.com/{repo['full_name']}/blob/{quote(item['commit'], safe='')}/{quote(item['path'])}"
    return item


def edit_repository(db, name, *, category=None, agent_types=None, excluded=None, reason, reset=False):
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
        raise ValueError("A reason of 1 to 500 characters is required")
    if category is not None and category not in CATEGORIES:
        raise ValueError("Unknown category")
    if agent_types is not None and (not isinstance(agent_types, list) or any(t not in AGENT_TYPES for t in agent_types)):
        raise ValueError("Unknown Agent type")
    if excluded is not None and not isinstance(excluded, bool):
        raise ValueError("excluded must be a boolean")
    if not reset and category is None and agent_types is None and excluded is None:
        raise ValueError("Choose a category, Agent types or inclusion change")
    with db.lease("collection"):
        record = resolve_repository(db, name)
        if not record:
            raise ValueError("Repository not tracked; add it first")
        now = utcnow()
        with db.connect() as con:
            row = con.execute("SELECT * FROM repository_overrides WHERE repo_id=?", (record["id"],)).fetchone()
            before = dict(row) if row else None
            if reset:
                con.execute("DELETE FROM repository_overrides WHERE repo_id=?", (record["id"],))
                after = None
            else:
                after = {"repo_id": record["id"], "category": category if category is not None else before["category"] if before else None,
                         "agent_types": dumps(sorted(set(agent_types))) if agent_types is not None else before["agent_types"] if before else None,
                         "excluded": int(excluded) if excluded is not None else before["excluded"] if before else 0,
                         "reason": reason.strip(), "updated_at": now}
                con.execute("INSERT INTO repository_overrides VALUES(:repo_id,:category,:agent_types,:excluded,:reason,:updated_at) ON CONFLICT(repo_id) DO UPDATE SET category=excluded.category,agent_types=excluded.agent_types,excluded=excluded.excluded,reason=excluded.reason,updated_at=excluded.updated_at", after)
            con.execute("INSERT INTO repository_edits VALUES(?,?,?,?,?)", (uuid.uuid4().hex, record["id"], "reset" if reset else "set", dumps({"before": before, "after": after, "reason": reason.strip()}), now))
    return apply_override(json.loads(record["data"]), after)


def edit_history(db, name):
    record = resolve_repository(db, name)
    if not record:
        raise ValueError("Repository not tracked")
    rows = db.rows("SELECT * FROM repository_edits WHERE repo_id=? ORDER BY created_at,rowid", (record["id"],))
    return [{**row, "data": json.loads(row["data"])} for row in rows]
