from dataclasses import replace
import json
import sqlite3
import httpx
import pytest
from conftest import add_repo
from github_rank.api import create_app
from github_rank.db import Database, SCHEMA, dumps
from github_rank.jobs import collect, register_sources
from github_rank.sources import set_enabled, source_states
from github_rank.summaries import OllamaProvider, SummaryError, summarize, annotate_summaries
from github_rank.transport import Fetcher
from fastapi.testclient import TestClient


SUMMARY = "这是一个面向开发者的智能代理框架项目，原始介绍说明其提供代理构建能力。具体功能和使用要求请结合项目原始文档进一步了解。"


class FakeProvider:
    def __init__(self, invalid=False):
        self.calls = 0
        self.invalid = invalid

    def generate(self, payload):
        self.calls += 1
        quote = "A fabricated quote absent from the source" if self.invalid else payload["sources"][0]["text"][:80]
        return {"summary": SUMMARY, "title_zh": "", "evidence": [{"source_id": payload["sources"][0]["id"], "quote": quote}]}, {"prompt_tokens": 50, "output_tokens": 30}


def test_disabled_model_does_not_call_provider(settings, db):
    provider = FakeProvider()
    assert summarize(settings, db, provider=provider)["status"] == "not_configured"
    assert provider.calls == 0


def test_cache_reuse_does_not_spend_daily_budget(settings, db):
    add_repo(db)
    settings = replace(settings, summary_model="test", summary_daily_limit=1)
    provider = FakeProvider()
    assert summarize(settings, db, "project", provider=provider)["generated"] == 1
    assert summarize(settings, db, "project", provider=provider)["cached"] == 1
    assert provider.calls == 1
    assert db.rows("SELECT count(*) AS n FROM summary_attempts")[0]["n"] == 1


def test_daily_budget_stops_additional_calls(settings, db):
    add_repo(db)
    add_repo(db, 2)
    provider = FakeProvider()
    report = summarize(replace(settings, summary_model="test", summary_daily_limit=1), db, "project", provider=provider)
    assert report["status"] == "budget_reached" and provider.calls == 1


def test_invalid_citation_is_rejected_and_failed_attempt_counts(settings, db):
    add_repo(db)
    provider = FakeProvider(invalid=True)
    settings = replace(settings, summary_model="test", summary_daily_limit=1)
    report = summarize(settings, db, "project", provider=provider)
    assert report["failed"] == 1 and db.rows("SELECT * FROM summaries") == []
    assert db.rows("SELECT status FROM summary_attempts")[0]["status"] == "failed"
    assert summarize(settings, db, "project", provider=provider)["status"] == "budget_reached"
    assert provider.calls == 1


def test_changed_input_hides_stale_summary(settings, db):
    original = add_repo(db)
    summarize(replace(settings, summary_model="test"), db, "project", provider=FakeProvider())
    assert annotate_summaries(db, [original.copy()], "project")[0]["summary_zh"] == SUMMARY
    updated = {**original, "description": "A changed description for a new version"}
    db.execute("UPDATE repositories SET data=? WHERE id=1", (dumps(updated),))
    assert "summary_zh" not in annotate_summaries(db, [updated], "project")[0]


def test_ollama_request_has_schema_and_no_tools():
    observed = []
    def handler(request):
        payload = json.loads(request.content)
        observed.append(payload)
        return httpx.Response(200, json={"message": {"content": json.dumps({"summary": SUMMARY, "evidence": [{"source_id": "description", "quote": "An agent framework"}]})}, "prompt_eval_count": 20, "eval_count": 40})
    provider = OllamaProvider("http://127.0.0.1:11434", "test", httpx.MockTransport(handler))
    output, usage = provider.generate({"sources": [{"id": "description", "text": "An agent framework", "url": "https://github.com/o/r"}]})
    assert output["summary"] == SUMMARY and usage["output_tokens"] == 40
    assert observed[0]["stream"] is False and "tools" not in observed[0]
    assert observed[0]["format"]["type"] == "object"
    provider.close()


def test_remote_insecure_summary_endpoint_rejected():
    with pytest.raises(SummaryError, match="HTTPS"):
        OllamaProvider("http://example.com", "test")


def test_schema_migration_preserves_existing_repositories(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA)
        con.execute("INSERT INTO repositories VALUES(1,'owner/repo','ai','[]','{}','old','old')")
    db = Database(path)
    assert db.rows("PRAGMA user_version")[0]["user_version"] == 5
    assert db.rows("SELECT count(*) AS n FROM repositories")[0]["n"] == 1
    assert db.rows("SELECT * FROM summaries") == []


def test_paused_source_is_not_fetched(settings):
    settings.config_path.write_text('news_sources:\n  - {id: lab, name: Lab, adapter: feed, url: "https://example.com/feed"}\n', encoding="utf-8")
    db = Database(settings.db_path)
    register_sources(db, settings.config())
    set_enabled(db, "lab", False)
    def handler(request):
        raise AssertionError("Paused source must not be fetched")
    fetcher = Fetcher(db, transport=httpx.MockTransport(handler))
    assert collect(settings, db, mode="news", force=True, fetcher=fetcher)["sources"][0]["status"] == "paused"
    assert source_states(db)[0]["effective_status"] == "paused"
    set_enabled(db, "lab", True)
    assert source_states(db)[0]["enabled"] is True
    fetcher.close()


def test_language_star_filters_match_export(settings):
    app = create_app(settings)
    add_repo(app.state.db, stars=500)
    add_repo(app.state.db, 2, language="Go", stars=2000)
    client = TestClient(app)
    query = "language=Python&min_stars=100&max_stars=1000"
    listed = client.get("/api/rankings?" + query).json()
    exported = client.get("/api/exports?" + query).json()
    assert listed["observing_total"] == exported["observing_total"] == 1
    assert client.get("/api/rankings?min_stars=1000&max_stars=500").status_code == 422
    assert client.get("/api/config").json()["languages"] == ["Go", "Python"]


def test_search_limit_keeps_core_budget_available(db):
    def handler(request):
        if request.url.path.startswith("/search/"):
            return httpx.Response(403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Resource": "search"})
        return httpx.Response(200, json={"id": 1})
    from github_rank.transport import RateLimited
    fetcher = Fetcher(db, transport=httpx.MockTransport(handler))
    with pytest.raises(RateLimited):
        fetcher.get("https://api.github.com/search/repositories?q=test")
    assert json.loads(fetcher.get("https://api.github.com/repos/o/r"))["id"] == 1
    fetcher.close()
