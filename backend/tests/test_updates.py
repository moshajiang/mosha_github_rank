from dataclasses import replace
from conftest import add_repo
from github_rank.scheduler import claim_scheduler
from github_rank.summaries import summarize
from github_rank.updates import update
from test_summaries_sources import FakeProvider


def test_update_collects_once_then_reuses_the_project_summary(settings, db, monkeypatch):
    settings.config_path.write_text(
        "repositories: [owner/repo-1]\ncollection: {release_repositories: 0}\n", encoding="utf-8",
    )
    settings = replace(settings, summary_model="test")
    provider = FakeProvider()

    def collect_project(database, fetcher, name, *limits):
        assert name == "owner/repo-1"
        return add_repo(database, warnings=[], resource_scan={})

    monkeypatch.setattr("github_rank.jobs.collect_repo", collect_project)
    monkeypatch.setattr("github_rank.updates.summarize",
                        lambda settings, db, kind, limit: summarize(settings, db, kind, limit, provider))
    first = update(settings, db, summary_limit=10)
    second = update(settings, db, summary_limit=10)
    assert first["collection"]["mode"] == "all" and first["collection"]["repositories"] == 1
    assert first["project_summaries"]["generated"] == 1
    assert second["collection"]["mode"] == "news" and second["collection"]["repositories"] == 0
    assert second["project_summaries"]["cached"] == 1 and second["project_summaries"]["remaining"] == 0
    assert provider.calls == 1


def test_update_reuses_active_scheduler_and_defers_colliding_tasks(settings, db):
    with db.lease("collection"):
        assert update(settings, db, 10)["collection"]["status"] == "busy"

    settings = replace(settings, summary_model="test")
    claim_scheduler(db, "active", 60)
    with db.lease("summaries"):
        report = update(settings, db, 10)
        assert report["collection"]["status"] == "scheduled"
        assert report["project_summaries"]["status"] == "busy"
    db.execute("UPDATE scheduler_state SET current_mode='all' WHERE id=1")
    assert update(settings, db, 10)["project_summaries"]["status"] == "deferred"
    assert db.rows("SELECT id FROM job_runs") == []
