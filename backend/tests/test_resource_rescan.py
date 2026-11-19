import json

import httpx
import pytest

from conftest import add_repo
from github_rank.agent_resources import resource_record
from github_rank.collectors import collect_repo
from github_rank.coverage import coverage_report
from github_rank.db import dumps, utcnow
from github_rank.repositories import edit_repository
from github_rank.resource_rescan import plan_rescan, rescan_repositories
from github_rank.transport import Fetcher


PATHS = ("skills/alpha/SKILL.md", "skills/beta/SKILL.md")


def manifest(path):
    name = path.split("/")[-2]
    return f"---\nname: {name}\ndescription: A useful sample capability\n---\n"


def tracked(db, repo_id, **fields):
    return add_repo(db, repo_id, resource_scan="partial", **fields)


def mock_upstream(db, override=None, budget=30):
    calls = []

    def handler(request):
        calls.append(request)
        if override and (response := override(request)) is not None:
            return response
        if request.url.host == "raw.githubusercontent.com":
            path = request.url.path.split("/test-commit/", 1)[-1]
            return httpx.Response(200, content=manifest(path).encode())
        assert request.url.host == "api.github.com"
        _, _, owner, repo, *rest = request.url.path.split("/")
        name = f"{owner}/{repo}"
        if rest == ["readme"]:
            return httpx.Response(404)
        if rest == ["branches", "main"]:
            return httpx.Response(200, json={"commit": {"sha": "test-commit"}})
        if rest == ["git", "trees", "test-commit"]:
            tree = [{"path": path, "type": "blob", "mode": "100644", "size": 100} for path in PATHS]
            return httpx.Response(200, json={"tree": tree, "truncated": False})
        assert rest == []
        return httpx.Response(200, json={
            "id": int(repo.split("-")[-1]), "full_name": name, "html_url": f"https://github.com/{name}",
            "description": "An agent framework", "stargazers_count": 500, "forks_count": 10,
            "default_branch": "main",
        })

    return Fetcher(db, transport=httpx.MockTransport(handler), resource_budget=budget), calls


def test_plan_prioritizes_multiresource_candidates_and_respects_curation(db):
    tracked(db, 1)
    rich = tracked(db, 2)
    for path in PATHS:
        resource = resource_record(rich, path, manifest(path), "older-sha")
        db.execute("INSERT INTO resources VALUES(?,?,?,?,?,?)",
                   (resource["id"], 2, path, "skill", dumps(resource), utcnow()))
    tracked(db, 3, archived=True)
    tracked(db, 4)
    edit_repository(db, "owner/repo-4", excluded=True, reason="Local example")
    add_repo(db, 5, resource_scan="complete")
    db.execute("INSERT INTO repository_aliases VALUES(?,?,?)", ("owner/old-name", 2, utcnow()))
    plan = plan_rescan(db, limit=1)
    assert plan["candidate_total"] == 2
    assert [item["id"] for item in plan["candidates"]] == [2]
    assert db.rows("SELECT id FROM job_runs") == []
    explicit = plan_rescan(db, ["owner/old-name", "owner/repo-2", "owner/repo-5"])
    assert [item["id"] for item in explicit["candidates"]] == [2, 5]
    with pytest.raises(ValueError, match="excluded"):
        plan_rescan(db, ["owner/repo-4"])
    with pytest.raises(ValueError, match="not tracked"):
        plan_rescan(db, ["owner/unknown"])


def test_batch_stops_after_successful_response_exhausts_core_quota(settings, db):
    tracked(db, 1)
    tracked(db, 2)

    def last_response(request):
        if "/git/trees/" in request.url.path:
            return httpx.Response(200, headers={"X-RateLimit-Remaining": "0"},
                                  json={"tree": [{"path": p, "type": "blob"} for p in PATHS], "truncated": False})

    fetcher, calls = mock_upstream(db, last_response)
    try:
        report = rescan_repositories(settings, db, ["owner/repo-1", "owner/repo-2"], fetcher=fetcher)
    finally:
        fetcher.close()
    assert report["counts"] == {"complete": 1, "deferred": 1}
    assert report["complete_multiresource"] == 1
    assert report["stop_reason"] == "github_api_limit"
    assert report["github_requests"] == report["resource_requests"] == 4
    assert not any("/repo-2" in request.url.path for request in calls)
    assert db.rows("SELECT repo_id FROM snapshots") == [{"repo_id": 1}]
    assert db.rows("SELECT name FROM leases") == []
    audit = db.rows("SELECT kind,status,report FROM job_runs")[0]
    assert audit["kind"] == "resource_rescan" and audit["status"] == "partial"
    assert json.loads(audit["report"]) == report


@pytest.mark.parametrize("stop", ["github_api_limit", "resource_rate_limit", "batch_resource_budget"])
def test_shared_budgets_defer_remainder_without_page_fallback(settings, db, stop):
    tracked(db, 1)
    tracked(db, 2)

    def throttled(request):
        if stop == "github_api_limit" and request.url.path == "/repos/owner/repo-1":
            return httpx.Response(403, headers={"X-RateLimit-Remaining": "0"})
        if stop == "resource_rate_limit" and request.url.host == "raw.githubusercontent.com":
            return httpx.Response(429, headers={"Retry-After": "60"})

    fetcher, calls = mock_upstream(db, throttled, budget=3 if stop == "batch_resource_budget" else 30)
    try:
        result = rescan_repositories(settings, db, fetcher=fetcher)
    finally:
        fetcher.close()
    assert result["stop_reason"] == stop
    assert result["repositories"][-1]["status"] == "deferred"
    assert all(request.url.host != "github.com" and "/repo-2" not in request.url.path for request in calls)
    if stop == "github_api_limit":
        assert result["counts"] == {"deferred": 2}
        assert db.rows("SELECT repo_id FROM snapshots") == []
    else:
        assert result["counts"] == {"partial": 1, "deferred": 1}
        assert len([request for request in calls if request.url.host == "raw.githubusercontent.com"]) == 1


def test_changed_upstream_id_is_rejected_and_next_candidate_runs(settings, db):
    tracked(db, 1)
    tracked(db, 2)

    def reused_name(request):
        if request.url.path == "/repos/owner/repo-1":
            return httpx.Response(200, json={"id": 99})

    fetcher, _ = mock_upstream(db, reused_name)
    try:
        result = rescan_repositories(settings, db, fetcher=fetcher)
    finally:
        fetcher.close()
    assert result["counts"] == {"failed": 1, "complete": 1}
    assert db.rows("SELECT id FROM repositories ORDER BY id") == [{"id": 1}, {"id": 2}]
    assert db.rows("SELECT repo_id FROM snapshots") == [{"repo_id": 2}]


def test_full_scan_evidence_survives_skipped_and_partial_scans(settings, db):
    tracked(db, 1)
    fetcher, calls = mock_upstream(db)
    try:
        rescan_repositories(settings, db, fetcher=fetcher)
        edit_repository(db, "owner/repo-1", agent_types=[], reason="Pause automatic scans")
        calls.clear()
        repo = collect_repo(db, fetcher, "owner/repo-1")
        assert len(db.rows("SELECT id FROM resources")) == 2
        assert all("/branches/" not in request.url.path for request in calls)
        evidence = repo["last_complete_resource_scan"]
    finally:
        fetcher.close()

    def missing_file(request):
        if request.url.host == "raw.githubusercontent.com":
            return httpx.Response(404)

    fetcher, _ = mock_upstream(db, missing_file)
    try:
        result = rescan_repositories(settings, db, ["owner/repo-1"], fetcher=fetcher)
    finally:
        fetcher.close()
    saved = json.loads(db.rows("SELECT data FROM repositories")[0]["data"])
    assert result["counts"] == {"partial": 1}
    assert saved["resource_scan"] == "partial" and saved["last_complete_resource_scan"] == evidence
    assert len(db.rows("SELECT id FROM resources")) == 2
    coverage = coverage_report(db)["resources"]
    assert coverage["scan_repositories"] == {"partial": 1}
    assert coverage["last_complete_multiresource_repositories"] == 1


def test_rescan_holds_shared_lease_before_using_network(settings, db):
    tracked(db, 1)
    fetcher, calls = mock_upstream(db)
    try:
        with db.lease("collection"):
            with pytest.raises(RuntimeError, match="Another collection task"):
                rescan_repositories(settings, db, fetcher=fetcher)
    finally:
        fetcher.close()
    assert not calls and db.rows("SELECT id FROM job_runs") == []


def test_interrupted_batch_keeps_finished_scans_and_releases_lease(settings, db):
    for repo_id in range(1, 4):
        tracked(db, repo_id)

    def interrupt(request):
        if request.url.path == "/repos/owner/repo-2":
            raise KeyboardInterrupt

    fetcher, _ = mock_upstream(db, interrupt)
    try:
        with pytest.raises(KeyboardInterrupt):
            rescan_repositories(settings, db, fetcher=fetcher)
    finally:
        fetcher.close()
    row = db.rows("SELECT status,report FROM job_runs")[0]
    report = json.loads(row["report"])
    assert row["status"] == "cancelled"
    assert report["counts"] == {"complete": 1, "interrupted": 1, "deferred": 1}
    assert db.rows("SELECT repo_id FROM snapshots") == [{"repo_id": 1}]
    assert db.rows("SELECT name FROM leases") == []
