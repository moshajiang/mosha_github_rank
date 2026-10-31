import base64
import json
import httpx
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from conftest import add_repo
from github_rank.api import create_app
from github_rank.collectors import collect_repo, resource_record, github_page_data
from github_rank.transport import FetchError
import pytest
from github_rank.news import build_item, store_item
from github_rank.transport import Fetcher
from github_rank.jobs import collect


def test_repeated_collection_does_not_overwrite_daily_snapshot(db):
    repo = {"id": 100, "full_name": "owner/tool", "html_url": "https://github.com/owner/tool", "description": "A command line tool", "stargazers_count": 100, "forks_count": 2, "language": "Python", "default_branch": "main"}
    def handler(request):
        data = {"encoding": "base64", "content": base64.b64encode(b"# Tool").decode()} if request.url.path.endswith("readme") else repo
        return httpx.Response(200, json=data)
    fetcher = Fetcher(db, transport=httpx.MockTransport(handler))
    collect_repo(db, fetcher, "owner/tool")
    repo["stargazers_count"] = 200
    collect_repo(db, fetcher, "owner/tool")
    assert db.rows("SELECT stars FROM snapshots")[0]["stars"] == 100
    assert json.loads(db.rows("SELECT data FROM repositories")[0]["data"])["stars"] == 200
    fetcher.close()


def test_resource_preserves_commit_and_never_inherits_individual_stars():
    resource = resource_record({"id": 1, "full_name": "o/r"}, "skills/test/SKILL.md", "---\nname: test\ndescription: Test work\n---\nInstructions", "commit123")
    assert "commit123" in resource["url"]
    assert "stars" not in resource and "installs" not in resource
    assert resource_record({"id": 1, "full_name": "o/r"}, "SKILL.md", "Just an instruction", "sha") is None


def test_api_limit_falls_back_only_to_exact_public_counters(db):
    payload = {"payload": {"codeViewRepoRoute": {"refInfo": {"currentOid": "abc123"}, "tree": {"items": []}},
                           "codeViewLayoutRoute": {"repo": {"id": 101, "name": "tool", "ownerLogin": "owner", "defaultBranch": "main"}},
                           "sidebarAbout": {"stargazerCount": 12345, "forksCount": 111, "description": "A tool", "topics": []}}}
    body = '<script data-target="react-app.embeddedData" type="application/json">' + json.dumps(payload) + '</script>'
    def handler(request):
        return httpx.Response(429) if request.url.host == "api.github.com" else httpx.Response(200, text=body)
    fetcher = Fetcher(db, transport=httpx.MockTransport(handler))
    repo = collect_repo(db, fetcher, "owner/tool")
    assert repo["stars"] == 12345 and repo["data_source"] == "github_public_page"
    assert repo["pushed_at"] is None and db.rows("SELECT stars FROM snapshots")[0]["stars"] == 12345
    payload["payload"]["sidebarAbout"]["stargazerCount"] = "12.3k"
    body = '<script data-target="react-app.embeddedData" type="application/json">' + json.dumps(payload) + '</script>'
    with pytest.raises(FetchError, match="Exact public counters"):
        github_page_data(fetcher, "owner/tool")
    fetcher.close()


def test_news_time_filter_and_unknown_items_are_separate(settings):
    app = create_app(settings)
    db = app.state.db
    source = {"id": "lab", "name": "Lab", "kind": "official"}
    old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    store_item(db, build_item(source, "Old model announcement", "https://example.com/old", published_at=old))
    store_item(db, build_item(source, "Undated model announcement", "https://example.com/unknown"))
    client = TestClient(app)
    result = client.get("/api/news?window=24h").json()
    assert result["items"] == [] and len(result["unknown_time"]) == 1
    assert client.get("/api/news/sources").status_code == 200
    assert client.get("/api/news?window=invalid").status_code == 422


def test_empty_rankings_and_export_and_api_404(settings):
    client = TestClient(create_app(settings))
    assert client.get("/api/rankings").json()["items"] == []
    assert client.get("/api/exports?format=markdown").status_code == 200
    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/api/projects/missing/repository").status_code == 404


def test_project_and_agent_filters(settings):
    app = create_app(settings)
    add_repo(app.state.db)
    add_repo(app.state.db, 2, category="frontend", agent_types=[])
    client = TestClient(app)
    assert client.get("/api/projects?agent_type=any").json()["total"] == 1
    assert client.get("/api/rankings?category=frontend").json()["observing_total"] == 1
    assert client.get("/api/projects?min_stars=-1").status_code == 422


def test_one_broken_source_does_not_discard_other_news(settings):
    settings.config_path.write_text('''repositories: []
news_sources:
  - {id: good, name: Good, kind: official, adapter: feed, url: "https://good.example/feed"}
  - {id: broken, name: Broken, kind: official, adapter: feed, url: "https://broken.example/feed"}
''', encoding="utf-8")
    app = create_app(settings)
    db = app.state.db
    def handler(request):
        if request.url.host == "good.example":
            return httpx.Response(200, text='<rss version="2.0"><channel><title>Lab</title><item><title>A real model release</title><link>https://good.example/post</link></item></channel></rss>')
        return httpx.Response(200, text="<html>A broken feed</html>")
    fetcher = Fetcher(db, transport=httpx.MockTransport(handler))
    report = collect(settings, db, mode="news", force=True, fetcher=fetcher)
    assert report["status"] == "partial"
    assert len(db.rows("SELECT * FROM news")) == 1
    states = {r["id"]: r["status"] for r in db.rows("SELECT id,status FROM sources")}
    assert states == {"good": "ok", "broken": "error"}
    assert db.rows("SELECT status FROM job_runs")[0]["status"] == "partial"
    fetcher.close()


def test_tracked_repositories_refresh_before_new_candidates(settings):
    settings.config_path.write_text('repositories: ["new/candidate"]\nqueries: []\nnews_sources: []\n', encoding="utf-8")
    app = create_app(settings)
    db = app.state.db
    add_repo(db)
    original = {"id": 1, "full_name": "owner/repo-1", "html_url": "https://github.com/owner/repo-1", "description": "A useful tool", "stargazers_count": 1200, "forks_count": 20}
    def handler(request):
        assert "new/candidate" not in request.url.path
        return httpx.Response(200, json={"encoding": "base64", "content": ""} if request.url.path.endswith("readme") else original)
    fetcher = Fetcher(db, transport=httpx.MockTransport(handler))
    report = collect(settings, db, mode="repositories", discovery=False, repo_limit=1, fetcher=fetcher)
    assert report["repositories"][0]["name"] == "owner/repo-1"
    assert report["deferred_repositories"] == 1
    assert len(db.rows("SELECT * FROM snapshots")) == 1
    fetcher.close()
