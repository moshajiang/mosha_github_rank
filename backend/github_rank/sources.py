import json
import uuid
from datetime import datetime, timezone, timedelta
from .db import utcnow


def source_states(db, now=None):
    now = now or datetime.now(timezone.utc)
    preferences = {row["source_id"]: bool(row["enabled"]) for row in db.rows("SELECT * FROM source_preferences")}
    health = {row["source_id"]: row for row in db.rows("SELECT * FROM source_health")}
    result = []
    for row in db.rows("SELECT * FROM sources ORDER BY id"):
        item = {**json.loads(row["data"]), **{k: v for k, v in row.items() if k != "data"}}
        item["enabled"] = preferences.get(row["id"], item.get("enabled", True))
        item["effective_status"] = item["status"] if item["enabled"] else "paused"
        item.update({"consecutive_failures": 0, "last_error_at": None, "last_recovered_at": None, **health.get(row["id"], {})})
        interval = max(int(item.get("interval_minutes", 1440 if item.get("kind") == "release" else 30)), 1)
        checked = datetime.fromisoformat(item["last_checked_at"]) if item["last_checked_at"] else None
        success = datetime.fromisoformat(item["last_success_at"]) if item["last_success_at"] else None
        item["next_due_at"] = (checked + timedelta(minutes=interval)).isoformat(timespec="seconds") if checked and item["enabled"] and item.get("kind") != "release" else None
        item["cadence_note"] = "随每日全量任务采集" if item.get("kind") == "release" else f"每 {interval} 分钟检查"
        item["freshness"] = "paused" if not item["enabled"] else "never" if not success else "stale" if now-success > timedelta(minutes=max(interval*3, 60)) else "fresh"
        result.append(item)
    return result


def record_source_result(db, source_id, *, count=None, error=None, now=None):
    now = now or utcnow()
    with db.connect() as con:
        previous = con.execute("SELECT status FROM sources WHERE id=?", (source_id,)).fetchone()
        if not previous:
            raise ValueError("Unknown source ID")
        if error is not None:
            error = str(error)[:300]
            con.execute("UPDATE sources SET last_checked_at=?,status='error',error=? WHERE id=?", (now, error, source_id))
            con.execute("INSERT INTO source_health(source_id,consecutive_failures,last_error_at) VALUES(?,1,?) ON CONFLICT(source_id) DO UPDATE SET consecutive_failures=consecutive_failures+1,last_error_at=excluded.last_error_at", (source_id, now))
            kind = "failure" if previous["status"] != "error" else None
        else:
            con.execute("UPDATE sources SET last_checked_at=?,last_success_at=?,status='ok',error=NULL,item_count=? WHERE id=?", (now, now, count or 0, source_id))
            recovered = now if previous["status"] == "error" else None
            con.execute("INSERT INTO source_health(source_id,consecutive_failures,last_recovered_at) VALUES(?,0,?) ON CONFLICT(source_id) DO UPDATE SET consecutive_failures=0,last_recovered_at=coalesce(excluded.last_recovered_at,source_health.last_recovered_at)", (source_id, recovered))
            kind = "recovered" if recovered else None
        if kind:
            con.execute("INSERT INTO source_events VALUES(?,?,?,?,?)", (uuid.uuid4().hex, source_id, kind, now, error))


def source_events(db, limit=20):
    return db.rows("SELECT e.*,s.data AS source_data FROM source_events e JOIN sources s ON s.id=e.source_id ORDER BY e.occurred_at DESC,e.rowid DESC LIMIT ?", (limit,))


def source_enabled(db, source):
    pref = db.rows("SELECT enabled FROM source_preferences WHERE source_id=?", (source["id"],))
    return bool(pref[0]["enabled"]) if pref else source.get("enabled", True)


def set_enabled(db, source_id, enabled):
    if not db.rows("SELECT id FROM sources WHERE id=?", (source_id,)):
        raise ValueError("Unknown source ID")
    db.execute("INSERT INTO source_preferences VALUES(?,?,?) ON CONFLICT(source_id) DO UPDATE SET enabled=excluded.enabled,updated_at=excluded.updated_at", (source_id, int(enabled), utcnow()))
