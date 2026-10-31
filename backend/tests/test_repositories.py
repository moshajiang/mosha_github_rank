import base64
import json
import sqlite3
import sys
from datetime import timedelta
import httpx
import pytest
from fastapi.testclient import TestClient
from conftest import add_repo, snapshot
from github_rank.api import create_app
from github_rank.cli import main
from github_rank.collectors import collect_repo, resource_record
from github_rank.db import Database, SCHEMA, MIGRATION_2, dumps
from github_rank.jobs import add_repository
from github_rank.ranking import compute_rankings, publish_rankings
from github_rank.repositories import normalize_name, edit_repository, edit_history, resolve_repository
from github_rank.transport import Fetcher, FetchError
from test_ranking import END


def repo_fetcher(db, payload, requests=None):
    def handler(request):
        if requests is not None:
            requests.append(str(request.url))
        if request.url.path.endswith("/readme"):
            return httpx.Response(200, json={"encoding": "base64", "content": base64.b64encode(b"# A useful tool").decode()})
        if "/branches/" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, json=payload)
    return Fetcher(db, transport=httpx.MockTransport(handler))


def upstream(repo_id=42, name="owner/tool", **extra):
    return {"id": repo_id, "full_name": name, "html_url": "https://github.com/" + name,
            "description": "A CLI tool", "stargazers_count": 120, "forks_count": 4, "default_branch": "main", **extra}


@pytest.mark.parametrize("value", ["https://evil.example/a/b", "http://github.com/a/b", "https://github.com@evil.example/a/b", "https://user@github.com/a/b", "https://github.com/a/b?token=secret", "https://github.com/a/b/tree/main", "a/..", "a/b/extra"])
def test_manual_candidate_rejects_non_repository_addresses(value):
    with pytest.raises(ValueError):
        normalize_name(value)


def test_manual_add_accepts_clone_url_and_records_job_without_overwriting_history(settings, db):
    payload = upstream()
    fetcher = repo_fetcher(db, payload)
    try:
        assert add_repository(settings, db, "https://github.com/owner/tool.git", fetcher)["status"] == "ok"
        payload["stargazers_count"] = 200
        add_repository(settings, db, "owner/tool", fetcher)
        assert db.rows("SELECT stars FROM snapshots") == [{"stars": 120}]
        assert len(db.rows("SELECT * FROM repositories")) == 1
        assert [r["status"] for r in db.rows("SELECT status FROM job_runs")] == ["ok", "ok"]
    finally:
        fetcher.close()


def test_private_repository_is_not_published_and_failure_is_recorded(settings, db):
    fetcher = repo_fetcher(db, upstream(private=True))
    try:
        with pytest.raises(FetchError, match="public"):
            add_repository(settings, db, "owner/tool", fetcher)
        assert db.rows("SELECT * FROM repositories") == db.rows("SELECT * FROM snapshots") == []
        assert db.rows("SELECT status FROM job_runs") == [{"status": "failed"}]
        assert db.rows("SELECT * FROM leases") == []
    finally:
        fetcher.close()


def test_override_survives_refresh_and_reset_uses_new_automatic_classification(db):
    payload = upstream()
    requests = []
    fetcher = repo_fetcher(db, payload, requests)
    try:
        collect_repo(db, fetcher, "owner/tool")
        edit_repository(db, "owner/tool", category="frontend", agent_types=["coding"], reason="人工核对用途")
        payload["description"] = "A database"
        refreshed = collect_repo(db, fetcher, "owner/tool")
        assert (refreshed["category"], refreshed["agent_types"]) == ("frontend", ["coding"])
        assert any("/branches/" in url for url in requests)
        raw = json.loads(db.rows("SELECT data FROM repositories")[0]["data"])
        assert raw["category"] == "data" and raw["agent_types"] == []
        restored = edit_repository(db, "owner/tool", reset=True, reason="恢复自动规则")
        assert restored["category"] == "data" and restored["agent_types"] == []
        assert [r["action"] for r in edit_history(db, "owner/tool")] == ["set", "reset"]
    finally:
        fetcher.close()


def test_exclusion_applies_to_lists_resources_rankings_exports_but_preserves_archives(settings):
    app = create_app(settings)
    db = app.state.db
    add_repo(db)
    for days, stars in [(7, 100), (0, 500)]:
        snapshot(db, 1, (END - timedelta(days=days)).isoformat(), stars)
    resource = resource_record({"id": 1, "full_name": "owner/repo-1"}, "SKILL.md", "---\nname: tool\ndescription: Useful agent tool\n---\n", "sha123")
    db.execute("INSERT INTO resources VALUES(?,?,?,?,?,?)", (resource["id"], 1, resource["path"], resource["kind"], dumps(resource), END.isoformat()))
    run_id = publish_rankings(db)[0]
    archived_before = db.rows("SELECT data FROM ranking_runs WHERE id=?", (run_id,))[0]["data"]
    edit_repository(db, "owner/repo-1", excluded=True, reason="不符合关注范围")
    client = TestClient(app)
    assert client.get("/api/projects").json()["total"] == 0
    assert client.get("/api/agent-resources").json()["total"] == 0
    for path in ("/api/rankings", "/api/exports"):
        output = client.get(path).json()
        assert output["total"] == output["observing_total"] == 0
        assert output["excluded_count"] == 1 and output["tracked_count"] == 1
    assert client.get("/api/projects/owner/repo-1").json()["ranking_excluded"] is True
    assert len(client.get("/api/projects/owner/repo-1/history").json()["items"]) == 2
    assert client.get("/api/rankings", params={"run_id": run_id}).json()["total"] == 1
    assert db.rows("SELECT data FROM ranking_runs WHERE id=?", (run_id,))[0]["data"] == archived_before
    edit_repository(db, "owner/repo-1", excluded=False, reason="重新关注")
    assert client.get("/api/projects").json()["total"] == 1


def test_effective_category_and_agent_type_filters_match_export(settings):
    app = create_app(settings)
    add_repo(app.state.db)
    edit_repository(app.state.db, "owner/repo-1", category="devtools", agent_types=["skill"], reason="验证分类修订")
    client = TestClient(app)
    query = "category=devtools&agent_type=skill"
    assert client.get("/api/projects?" + query).json()["total"] == 1
    ranked = client.get("/api/rankings?" + query).json()
    exported = client.get("/api/exports?" + query).json()
    assert ranked["observing_total"] == exported["observing_total"] == 1
    assert ranked["observing"][0]["classification"]["method"] == "manual"
    assert client.get("/api/projects?category=ai").json()["total"] == 0


def test_rename_keeps_old_url_history_overrides_and_commit_resource_links(settings):
    app = create_app(settings)
    db = app.state.db
    payload = upstream()
    fetcher = repo_fetcher(db, payload)
    try:
        collect_repo(db, fetcher, "owner/tool")
        edit_repository(db, "owner/tool", category="ai", reason="按用途归类")
        resource = resource_record({"id": 42, "full_name": "owner/tool"}, "SKILL.md", "---\nname: tool\ndescription: Useful agent tool\n---\n", "original-sha")
        db.execute("INSERT INTO resources VALUES(?,?,?,?,?,?)", (resource["id"], 42, resource["path"], resource["kind"], dumps(resource), END.isoformat()))
        payload.update(full_name="new-owner/new-tool", html_url="https://github.com/new-owner/new-tool")
        collect_repo(db, fetcher, "owner/tool")
        client = TestClient(app)
        detail = client.get("/api/projects/OWNER/TOOL").json()
        assert detail["full_name"] == "new-owner/new-tool" and detail["category"] == "ai"
        assert detail["aliases"] == ["owner/tool"]
        assert detail["resources"][0]["url"] == "https://github.com/new-owner/new-tool/blob/original-sha/SKILL.md"
        assert len(client.get("/api/projects/owner/tool/history").json()["items"]) == 1
        assert resolve_repository(db, "owner/tool")["id"] == 42
        assert edit_history(db, "new-owner/new-tool")[0]["data"]["after"]["category"] == "ai"
    finally:
        fetcher.close()


def test_reused_old_name_resolves_to_new_id_without_merging_history(db):
    payload = upstream()
    fetcher = repo_fetcher(db, payload)
    try:
        collect_repo(db, fetcher, "owner/tool")
        payload.update(full_name="owner/renamed", html_url="https://github.com/owner/renamed")
        collect_repo(db, fetcher, "owner/tool")
        payload.update(upstream(99))
        collect_repo(db, fetcher, "owner/tool")
        assert resolve_repository(db, "owner/tool")["id"] == 99
        assert resolve_repository(db, "owner/renamed")["id"] == 42
        assert {r["repo_id"] for r in db.rows("SELECT repo_id FROM snapshots")} == {42, 99}
        assert db.rows("SELECT * FROM repository_aliases") == []
    finally:
        fetcher.close()


def test_v2_migration_preserves_existing_snapshots_and_source_preferences(tmp_path):
    path = tmp_path / "v2.sqlite3"
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA)
        con.executescript(MIGRATION_2)
        con.execute("INSERT INTO repositories VALUES(1,'owner/tool','ai','[]','{}','old','old')")
        con.execute("INSERT INTO snapshots VALUES(1,'2026-10-30','2026-10-30T08:00:00+00:00',123,4)")
        con.execute("INSERT INTO sources(id,data) VALUES('lab','{}')")
        con.execute("INSERT INTO source_preferences VALUES('lab',0,'old')")
    db = Database(path)
    assert db.rows("PRAGMA user_version")[0]["user_version"] == 3
    assert db.rows("SELECT stars FROM snapshots") == [{"stars": 123}]
    assert db.rows("SELECT enabled FROM source_preferences") == [{"enabled": 0}]
    assert db.rows("PRAGMA integrity_check")[0]["integrity_check"] == "ok"


def test_cli_clear_types_preserves_exclusion_and_reset_is_audited(settings, monkeypatch, capsys):
    monkeypatch.setattr("github_rank.cli.Settings.from_env", lambda: settings)
    db = Database(settings.db_path)
    add_repo(db)
    commands = [
        ["set", "owner/repo-1", "--exclude", "--reason", "暂停关注"],
        ["set", "owner/repo-1", "--category", "devtools", "--agent-types", "--reason", "核对用途"],
        ["reset", "owner/repo-1", "--reason", "恢复规则"],
    ]
    for command in commands:
        monkeypatch.setattr(sys, "argv", ["github-rank", "projects", *command])
        main()
        result = json.loads(capsys.readouterr().out)
        if command[0] == "reset":
            assert not result["ranking_excluded"] and result["agent_types"] == ["framework"]
        else:
            assert result["ranking_excluded"] is True
            if "--agent-types" in command:
                assert result["agent_types"] == []
    assert len(edit_history(db, "owner/repo-1")) == 3


def test_curation_obeys_collection_lock_and_rejects_empty_reason(db):
    add_repo(db)
    with db.lease("collection"):
        with pytest.raises(RuntimeError, match="running"):
            edit_repository(db, "owner/repo-1", excluded=True, reason="等待采集结束")
    with pytest.raises(ValueError, match="reason"):
        edit_repository(db, "owner/repo-1", excluded=True, reason=" ")
    assert db.rows("SELECT * FROM repository_edits") == []


def test_excluded_project_cannot_supply_the_thirtieth_potential_peer(db):
    for repo_id in range(1, 31):
        add_repo(db, repo_id)
        for i in range(15):
            snapshot(db, repo_id, (END - timedelta(days=14-i)).isoformat(), 500+i*10, i)
    assert all(item["potential_eligible"] for item in compute_rankings(db, 7, END.isoformat())["items"])
    edit_repository(db, "owner/repo-1", excluded=True, reason="排除不相关参照样本")
    result = compute_rankings(db, 7, END.isoformat())
    assert len(result["items"]) == 29 and result["excluded_count"] == 1
    assert all(item["hot_eligible"] and not item["potential_eligible"] for item in result["items"])


def test_malformed_project_address_returns_404_instead_of_server_error(settings):
    client = TestClient(create_app(settings))
    assert client.get("/api/projects/中文/repository").status_code == 404
    assert client.get("/api/projects/中文/repository/history").status_code == 404
