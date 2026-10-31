from datetime import datetime, timedelta, timezone
import json
import sqlite3
import threading
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from github_rank.api import create_app
from github_rank.db import Database, SCHEMA, MIGRATION_2, MIGRATION_3, dumps
from github_rank.jobs import collect, register_sources
from github_rank.scheduler import Scheduler, claim_scheduler, scheduler_status, request_stop, repository_due
from github_rank.sources import record_source_result, source_states, source_events
from github_rank.transport import Fetcher, CollectionCancelled


NOW = datetime(2026, 10, 31, 1, tzinfo=timezone.utc)  # 09:00 CST


def test_never_started_and_clean_shutdown_are_not_reported_as_running(settings, db):
    assert scheduler_status(db)["status"] == "never"
    runner = Scheduler(settings, db, collector=lambda *args, **kwargs: {"status": "ok"})
    runner.run(max_cycles=1)
    state = scheduler_status(db)
    assert state["status"] == "stopped" and not state["online"]
    assert state["next_check_at"] is None and state["next_repository_at"] is None


def test_duplicate_scheduler_rejected_but_stale_owner_can_be_replaced(db):
    claim_scheduler(db, "first", 60, NOW)
    with pytest.raises(RuntimeError, match="already"):
        claim_scheduler(db, "second", 60, NOW+timedelta(seconds=10))
    assert scheduler_status(db, NOW+timedelta(seconds=91))["status"] == "stale"
    claim_scheduler(db, "second", 60, NOW+timedelta(seconds=91))
    assert scheduler_status(db, NOW+timedelta(seconds=91))["instance_id"] == "second"
    assert request_stop(db, "first") is False
    assert request_stop(db, "second") is True


def test_stale_restart_recovers_only_its_own_job_and_collection_lease(db):
    claim_scheduler(db, "first", 60, NOW)
    db.execute("INSERT INTO leases VALUES('collection','scheduler:first',?)", ((NOW+timedelta(hours=2)).isoformat(),))
    for job_id, report in [("scheduler-job", {"scheduler_instance": "first"}), ("manual-job", {})]:
        db.execute("INSERT INTO job_runs VALUES(?,?,?,?,?,?)", (job_id, "all", NOW.isoformat(), None, "running", dumps(report)))
    claim_scheduler(db, "second", 60, NOW+timedelta(seconds=91))
    assert db.rows("SELECT * FROM leases") == []
    assert {r["id"]:r["status"] for r in db.rows("SELECT id,status FROM job_runs")} == {"scheduler-job":"interrupted", "manual-job":"running"}
    # A manual writer's lease must survive another scheduler restart.
    db.execute("INSERT INTO leases VALUES('collection','manual-owner',?)", ((NOW+timedelta(hours=2)).isoformat(),))
    claim_scheduler(db, "third", 60, NOW+timedelta(seconds=182))
    assert db.rows("SELECT owner FROM leases")[0]["owner"] == "manual-owner"


def test_daily_boundary_and_restart_do_not_repeat_completed_daily_run(db):
    before = datetime(2026, 10, 30, 23, 59, tzinfo=timezone.utc)
    assert repository_due(db, before) > before
    assert repository_due(db, NOW) <= NOW
    db.execute("INSERT INTO job_runs VALUES('done','all',?,?,'partial','{}')", (NOW.isoformat(), NOW.isoformat()))
    assert repository_due(db, NOW) == datetime(2026, 11, 1, 0, tzinfo=timezone.utc)
    db.execute("UPDATE job_runs SET status='cancelled'")
    assert repository_due(db, NOW) <= NOW


def test_manual_collection_busy_is_deferred_without_clearing_lease(settings, db):
    claim_scheduler(db, "test", 60)
    runner = Scheduler(settings, db, instance_id="test")
    with db.lease("collection"):
        assert runner.cycle()["status"] == "deferred"
        assert len(db.rows("SELECT * FROM leases")) == 1


def test_heartbeat_continues_during_slow_collection_and_stop_is_cooperative(settings, db, monkeypatch):
    monkeypatch.setattr("github_rank.scheduler.HEARTBEAT_SECONDS", .02)
    monkeypatch.setattr("github_rank.scheduler.utcnow", lambda: datetime.now(timezone.utc).isoformat())
    entered, release = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        entered.set()
        release.wait(2)
        return {"status": "cancelled" if kwargs["cancelled"]() else "ok"}
    runner = Scheduler(settings, db, collector=slow)
    worker = threading.Thread(target=runner.run, kwargs={"max_cycles": 1})
    worker.start()
    try:
        assert entered.wait(1)
        first = scheduler_status(db)["heartbeat_at"]
        deadline = time.monotonic()+1
        while scheduler_status(db)["heartbeat_at"] == first and time.monotonic()<deadline:
            time.sleep(.01)
        assert scheduler_status(db)["heartbeat_at"] != first
        request_stop(db, runner.instance_id)
        assert scheduler_status(db)["status"] == "stopping"
        assert scheduler_status(db)["next_check_at"] is None
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert scheduler_status(db)["status"] == "stopped"
    assert scheduler_status(db)["last_result"] == "cancelled"


def test_collection_stop_does_not_mark_source_as_broken_or_publish_partial_rankings(settings, db):
    settings.config_path.write_text('repositories: ["owner/tool"]\nnews_sources: []\n', encoding="utf-8")
    stopped = threading.Event()
    def handler(request):
        stopped.set()
        raise CollectionCancelled("Stop requested")
    fetcher = Fetcher(db, transport=httpx.MockTransport(handler))
    try:
        report = collect(settings, db, mode="repositories", discovery=False, fetcher=fetcher, cancelled=stopped.is_set)
        assert report["status"] == "cancelled" and report["errors"] == []
        assert db.rows("SELECT * FROM ranking_runs") == []
        assert db.rows("SELECT * FROM leases") == []
    finally:
        fetcher.close()


def test_source_failure_repeat_recovery_and_freshness_are_separate(db):
    register_sources(db, {"news_sources":[{"id":"lab","name":"Lab","interval_minutes":30}]})
    record_source_result(db, "lab", count=2, now=NOW.isoformat())
    record_source_result(db, "lab", error="HTTP 503", now=(NOW+timedelta(minutes=30)).isoformat())
    record_source_result(db, "lab", error="HTTP 503", now=(NOW+timedelta(minutes=60)).isoformat())
    state = source_states(db, NOW+timedelta(hours=2))[0]
    assert state["status"] == "error" and state["freshness"] == "stale" and state["consecutive_failures"] == 2
    assert len(source_events(db)) == 1
    recovered = (NOW+timedelta(hours=2)).isoformat()
    record_source_result(db, "lab", count=3, now=recovered)
    state = source_states(db, NOW+timedelta(hours=2))[0]
    assert state["status"] == "ok" and state["freshness"] == "fresh" and state["consecutive_failures"] == 0
    assert state["last_recovered_at"] == recovered
    assert [e["kind"] for e in source_events(db)] == ["recovered", "failure"]
    assert source_states(db, NOW+timedelta(hours=5))[0]["freshness"] == "stale"


def test_paused_source_has_no_due_time_and_runtime_api_is_read_only(settings):
    app = create_app(settings)
    db = app.state.db
    register_sources(db, {"news_sources":[{"id":"lab","name":"Lab","enabled":False}]})
    record_source_result(db, "lab", error="HTTP 503")
    client = TestClient(app)
    result = client.get("/api/runtime-status").json()
    assert result["scheduler"]["status"] == "never"
    assert result["source_events"][0]["source_name"] == "Lab"
    state = client.get("/api/news/sources").json()["items"][0]
    assert state["freshness"] == "paused" and state["next_due_at"] is None
    assert client.post("/api/runtime-status").status_code == 405


def test_v3_migration_preserves_snapshots_and_curation_audit(tmp_path):
    path = tmp_path/"v3.sqlite3"
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA+MIGRATION_2+MIGRATION_3)
        con.execute("INSERT INTO repositories VALUES(1,'owner/tool','ai','[]','{}','old','old')")
        con.execute("INSERT INTO snapshots VALUES(1,'2026-10-30','old',123,4)")
        con.execute("INSERT INTO repository_edits VALUES('edit',1,'set','{}','old')")
    db = Database(path)
    assert db.rows("PRAGMA user_version")[0]["user_version"] == 4
    assert db.rows("SELECT stars FROM snapshots")[0]["stars"] == 123
    assert db.rows("SELECT id FROM repository_edits")[0]["id"] == "edit"
    assert db.rows("PRAGMA integrity_check")[0]["integrity_check"] == "ok"
