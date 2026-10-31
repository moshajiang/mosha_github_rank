import json
from .db import utcnow


def source_states(db):
    preferences = {row["source_id"]: bool(row["enabled"]) for row in db.rows("SELECT * FROM source_preferences")}
    result = []
    for row in db.rows("SELECT * FROM sources ORDER BY id"):
        item = {**json.loads(row["data"]), **{k: v for k, v in row.items() if k != "data"}}
        item["enabled"] = preferences.get(row["id"], item.get("enabled", True))
        item["effective_status"] = item["status"] if item["enabled"] else "paused"
        result.append(item)
    return result


def source_enabled(db, source):
    pref = db.rows("SELECT enabled FROM source_preferences WHERE source_id=?", (source["id"],))
    return bool(pref[0]["enabled"]) if pref else source.get("enabled", True)


def set_enabled(db, source_id, enabled):
    if not db.rows("SELECT id FROM sources WHERE id=?", (source_id,)):
        raise ValueError("Unknown source ID")
    db.execute("INSERT INTO source_preferences VALUES(?,?,?) ON CONFLICT(source_id) DO UPDATE SET enabled=excluded.enabled,updated_at=excluded.updated_at", (source_id, int(enabled), utcnow()))
