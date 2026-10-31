"""Persistent single-owner scheduler with an independent heartbeat and cooperative stop."""
from datetime import datetime, timezone, timedelta
import json
import threading
import uuid
from .db import dumps, utcnow
from .jobs import collect
from .summaries import summarize


CST = timezone(timedelta(hours=8))
HEARTBEAT_SECONDS = 5
STALE_SECONDS = 90
ACTIVE = ("running", "stopping")


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def repository_due(db, now):
    local = now.astimezone(CST)
    due = local.replace(hour=8, minute=0, second=0, microsecond=0)
    runs = db.rows("SELECT started_at FROM job_runs WHERE kind='all' AND status IN ('ok','partial') ORDER BY started_at DESC LIMIT 1")
    if runs and parse_time(runs[0]["started_at"]).astimezone(CST).date() == local.date():
        due += timedelta(days=1)
    return due.astimezone(timezone.utc)


def scheduler_status(db, now=None):
    now = now or datetime.now(timezone.utc)
    rows = db.rows("SELECT * FROM scheduler_state WHERE id=1")
    if not rows:
        return {"status": "never", "online": False, "next_check_at": None,
                "next_repository_at": None, "heartbeat_timeout_seconds": STALE_SECONDS}
    state = rows[0]
    age = max((now-parse_time(state["heartbeat_at"])).total_seconds(), 0)
    online = state["status"] in ACTIVE and age <= STALE_SECONDS
    return {**state, "status": "stale" if state["status"] in ACTIVE and not online else state["status"],
            "online": online, "heartbeat_age_seconds": round(age),
            "next_check_at": state["next_check_at"] if online and not state["stop_requested"] else None,
            "next_repository_at": repository_due(db, now).isoformat(timespec="seconds") if online and not state["stop_requested"] else None,
            "heartbeat_timeout_seconds": STALE_SECONDS}


def claim_scheduler(db, instance_id, interval, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM scheduler_state WHERE id=1").fetchone()
        if row and row["status"] in ACTIVE and (now-parse_time(row["heartbeat_at"])).total_seconds() <= STALE_SECONDS:
            raise RuntimeError("A scheduler is already running for this database")
        if row and row["status"] in ACTIVE:
            # Only recover leases/jobs explicitly owned by this expired scheduler.
            con.execute("DELETE FROM leases WHERE name='collection' AND owner=?", ("scheduler:"+row["instance_id"],))
            for job in con.execute("SELECT id,report FROM job_runs WHERE status='running'").fetchall():
                report = json.loads(job["report"])
                if report.get("scheduler_instance") == row["instance_id"]:
                    report["interrupted_at"] = stamp
                    con.execute("UPDATE job_runs SET status='interrupted',finished_at=?,report=? WHERE id=?", (stamp, dumps(report), job["id"]))
        con.execute("INSERT INTO scheduler_state(id,instance_id,started_at,heartbeat_at,status,interval_seconds,next_check_at) VALUES(1,?,?,?,'running',?,?) ON CONFLICT(id) DO UPDATE SET instance_id=excluded.instance_id,started_at=excluded.started_at,heartbeat_at=excluded.heartbeat_at,status='running',interval_seconds=excluded.interval_seconds,next_check_at=excluded.next_check_at,stopped_at=NULL,current_mode=NULL,last_cycle_at=NULL,last_result=NULL,error=NULL,stop_requested=0", (instance_id, stamp, stamp, interval, stamp))


def request_stop(db, instance_id=None):
    with db.connect() as con:
        row = con.execute("SELECT instance_id,status FROM scheduler_state WHERE id=1").fetchone()
        if not row or row["status"] not in ACTIVE or instance_id and row["instance_id"] != instance_id:
            return False
        con.execute("UPDATE scheduler_state SET stop_requested=1,status='stopping',next_check_at=NULL WHERE id=1 AND instance_id=?", (row["instance_id"],))
    return True


class Scheduler:
    def __init__(self, settings, db, interval=60, instance_id=None, collector=collect, summarizer=summarize):
        self.settings, self.db = settings, db
        self.interval = max(int(interval), 30)
        self.instance_id = instance_id or uuid.uuid4().hex
        self.collector, self.summarizer = collector, summarizer
        self.stop_event = threading.Event()
        self.heartbeat_done = threading.Event()

    def should_stop(self):
        if self.stop_event.is_set():
            return True
        rows = self.db.rows("SELECT instance_id,stop_requested FROM scheduler_state WHERE id=1")
        return not rows or rows[0]["instance_id"] != self.instance_id or bool(rows[0]["stop_requested"])

    def pulse(self):
        rows = self.db.rows("SELECT instance_id,stop_requested FROM scheduler_state WHERE id=1")
        if not rows or rows[0]["instance_id"] != self.instance_id:
            self.stop_event.set()
            return
        if rows[0]["stop_requested"]:
            self.stop_event.set()
        self.db.execute("UPDATE scheduler_state SET heartbeat_at=? WHERE id=1 AND instance_id=?", (utcnow(), self.instance_id))

    def heartbeat(self):
        while not self.heartbeat_done.wait(HEARTBEAT_SECONDS):
            try:
                self.pulse()
            except Exception:
                # Fail closed: do not continue collecting after losing persisted ownership.
                self.stop_event.set()
                return

    def cycle(self, now=None):
        now = now or datetime.now(timezone.utc)
        mode = "all" if repository_due(self.db, now) <= now else "news"
        self.db.execute("UPDATE scheduler_state SET current_mode=?,next_check_at=NULL WHERE id=1 AND instance_id=?", (mode, self.instance_id))
        try:
            report = self.collector(self.settings, self.db, mode, cancelled=self.should_stop, scheduler_instance=self.instance_id)
            result, error = report["status"], None
            if not self.should_stop() and self.settings.summary_auto and self.settings.summary_model:
                self.summarizer(self.settings, self.db, limit=5)
        except RuntimeError as exc:
            # A manual collector may hold the shared collection lease. Retry on the next check.
            busy = bool(self.db.rows("SELECT owner FROM leases WHERE name='collection'"))
            result, error = ("deferred", None) if busy else ("failed", type(exc).__name__)
        except Exception as exc:
            result, error = "failed", type(exc).__name__
        finished = datetime.now(timezone.utc)
        next_check = None if self.should_stop() else (finished+timedelta(seconds=self.interval)).isoformat(timespec="seconds")
        self.db.execute("UPDATE scheduler_state SET current_mode=NULL,next_check_at=?,last_cycle_at=?,last_result=?,error=? WHERE id=1 AND instance_id=?", (next_check, finished.isoformat(timespec="seconds"), result, error, self.instance_id))
        return {"status": result, "mode": mode, "error": error}

    def run(self, max_cycles=None):
        claim_scheduler(self.db, self.instance_id, self.interval)
        worker = threading.Thread(target=self.heartbeat, daemon=True, name="scheduler-heartbeat")
        worker.start()
        failed = False
        try:
            cycles = 0
            while not self.should_stop():
                print(dumps(self.cycle()), flush=True)
                cycles += 1
                if max_cycles is not None and cycles >= max_cycles:
                    break
                self.stop_event.wait(self.interval)
        except KeyboardInterrupt:
            self.stop_event.set()
        except BaseException:
            failed = True
            raise
        finally:
            self.heartbeat_done.set()
            worker.join(timeout=35)
            stamp = utcnow()
            self.db.execute("UPDATE scheduler_state SET status=?,stopped_at=?,heartbeat_at=?,next_check_at=NULL,current_mode=NULL WHERE id=1 AND instance_id=?", ("failed" if failed else "stopped", stamp, stamp, self.instance_id))
