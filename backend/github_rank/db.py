from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import sqlite3
import uuid


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS repositories (
 id INTEGER PRIMARY KEY, full_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
 category TEXT NOT NULL, agent_types TEXT NOT NULL, data TEXT NOT NULL,
 first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
 repo_id INTEGER NOT NULL REFERENCES repositories(id), day TEXT NOT NULL,
 observed_at TEXT NOT NULL, stars INTEGER NOT NULL, forks INTEGER NOT NULL,
 PRIMARY KEY(repo_id, day)
);
CREATE INDEX IF NOT EXISTS snapshots_time ON snapshots(observed_at);
CREATE TABLE IF NOT EXISTS resources (
 id TEXT PRIMARY KEY, repo_id INTEGER NOT NULL REFERENCES repositories(id),
 path TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, data TEXT NOT NULL, last_checked_at TEXT,
 last_success_at TEXT, status TEXT NOT NULL DEFAULT 'pending', error TEXT,
 item_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS news (
 id TEXT PRIMARY KEY, event_key TEXT NOT NULL, source_id TEXT NOT NULL,
 url TEXT NOT NULL UNIQUE, title TEXT NOT NULL, topic TEXT NOT NULL,
 published_at TEXT, first_seen_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
 content_hash TEXT NOT NULL, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS news_time ON news(published_at);
CREATE INDEX IF NOT EXISTS news_events ON news(event_key);
CREATE TABLE IF NOT EXISTS news_versions (
 item_id TEXT NOT NULL, content_hash TEXT NOT NULL, data TEXT NOT NULL,
 observed_at TEXT NOT NULL, PRIMARY KEY(item_id, content_hash)
);
CREATE TABLE IF NOT EXISTS job_runs (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, started_at TEXT NOT NULL,
 finished_at TEXT, status TEXT NOT NULL, report TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ranking_runs (
 id TEXT PRIMARY KEY, created_at TEXT NOT NULL, window_days INTEGER NOT NULL,
 algorithm TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS http_cache (
 url TEXT PRIMARY KEY, etag TEXT, modified TEXT, body BLOB NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leases (
 name TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at TEXT NOT NULL
);
PRAGMA user_version=1;
"""

MIGRATION_2 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS source_preferences (
 source_id TEXT PRIMARY KEY REFERENCES sources(id), enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS summaries (
 id TEXT PRIMARY KEY, entity_kind TEXT NOT NULL, entity_id TEXT NOT NULL,
 input_hash TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
 data TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(entity_kind,entity_id,input_hash,model,prompt_version)
);
CREATE INDEX IF NOT EXISTS summaries_entity ON summaries(entity_kind,entity_id,created_at);
CREATE TABLE IF NOT EXISTS summary_attempts (
 id TEXT PRIMARY KEY, day TEXT NOT NULL, entity_kind TEXT NOT NULL, entity_id TEXT NOT NULL,
 model TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
 prompt_tokens INTEGER, output_tokens INTEGER, error TEXT
);
CREATE INDEX IF NOT EXISTS summary_attempts_day ON summary_attempts(day);
PRAGMA user_version=2;
COMMIT;
"""

MIGRATION_3 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS repository_aliases (
 full_name TEXT PRIMARY KEY COLLATE NOCASE,
 repo_id INTEGER NOT NULL REFERENCES repositories(id), observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS repository_alias_repo ON repository_aliases(repo_id);
CREATE TABLE IF NOT EXISTS repository_overrides (
 repo_id INTEGER PRIMARY KEY REFERENCES repositories(id), category TEXT,
 agent_types TEXT, excluded INTEGER NOT NULL DEFAULT 0 CHECK(excluded IN (0,1)),
 reason TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repository_edits (
 id TEXT PRIMARY KEY, repo_id INTEGER NOT NULL REFERENCES repositories(id),
 action TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS repository_edits_repo ON repository_edits(repo_id,created_at);
PRAGMA user_version=3;
COMMIT;
"""

MIGRATION_4 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS scheduler_state (
 id INTEGER PRIMARY KEY CHECK(id=1), instance_id TEXT NOT NULL,
 started_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL, stopped_at TEXT,
 status TEXT NOT NULL, interval_seconds INTEGER NOT NULL,
 current_mode TEXT, next_check_at TEXT, last_cycle_at TEXT,
 last_result TEXT, error TEXT, stop_requested INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS source_health (
 source_id TEXT PRIMARY KEY REFERENCES sources(id), consecutive_failures INTEGER NOT NULL DEFAULT 0,
 last_error_at TEXT, last_recovered_at TEXT
);
CREATE TABLE IF NOT EXISTS source_events (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
 kind TEXT NOT NULL, occurred_at TEXT NOT NULL, error TEXT
);
CREATE INDEX IF NOT EXISTS source_events_time ON source_events(occurred_at);
PRAGMA user_version=4;
COMMIT;
"""

MIGRATION_5 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS news_event_overrides (
 item_id TEXT PRIMARY KEY REFERENCES news(id), group_id TEXT NOT NULL,
 reason TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS news_event_override_group ON news_event_overrides(group_id);
CREATE TABLE IF NOT EXISTS news_event_edits (
 id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, item_id TEXT NOT NULL REFERENCES news(id),
 action TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS news_event_edit_item ON news_event_edits(item_id,created_at);
PRAGMA user_version=5;
COMMIT;
"""


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version > 5:
                raise RuntimeError("Database schema is newer than this application")
            if version == 0:
                con.executescript(SCHEMA)
                version = 1
            if version == 1:
                con.executescript(MIGRATION_2)
                version = 2
            if version == 2:
                con.executescript(MIGRATION_3)
                version = 3
            if version == 3:
                con.executescript(MIGRATION_4)
                version = 4
            if version == 4:
                con.executescript(MIGRATION_5)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            with con:
                yield con
        finally:
            con.close()

    def rows(self, sql, params=()):
        with self.connect() as con:
            return [dict(row) for row in con.execute(sql, params)]

    def execute(self, sql, params=()):
        with self.connect() as con:
            con.execute(sql, params)

    @contextmanager
    def lease(self, name, owner=None):
        owner = owner or uuid.uuid4().hex
        now = utcnow()
        expiry = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(timespec="seconds")
        with self.connect() as con:
            con.execute("DELETE FROM leases WHERE expires_at < ?", (now,))
            try:
                con.execute("INSERT INTO leases VALUES(?,?,?)", (name, owner, expiry))
            except sqlite3.IntegrityError as exc:
                raise RuntimeError(f"Another {name} task is running") from exc
        try:
            yield
        finally:
            self.execute("DELETE FROM leases WHERE name=? AND owner=?", (name, owner))

    def backup(self, target):
        target = Path(target)
        if target.resolve() == self.path.resolve():
            raise ValueError("Backup path must differ from database path")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError("Choose a new backup path")
        with self.connect() as con, sqlite3.connect(target) as destination:
            con.backup(destination)
