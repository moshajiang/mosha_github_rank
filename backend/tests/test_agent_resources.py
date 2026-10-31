import base64
import json
import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from github_rank.agent_resources import resource_record, scan_resources
from github_rank.api import create_app
from github_rank.collectors import collect_repo
from github_rank.db import dumps, utcnow
from github_rank.repositories import edit_repository
from github_rank.transport import Fetcher, CollectionCancelled
from conftest import add_repo


SKILL = "---\nname: tool\ndescription: A useful tool\ncompatibility: Requires Python and network access\n---\nRead original instructions.\n"
REPO = {"id": 1, "full_name": "owner/tools", "html_url": "https://github.com/owner/tools", "description": "Agent framework tools", "default_branch": "main", "stargazers_count": 100, "forks_count": 3}


def tree_file(path, **extra):
    return {"path": path, "type": "blob", "mode": "100644", "size": 100, **extra}


def scanner(db, trees, files, calls=None):
    def handler(request):
        path = request.url.path
        if calls is not None:
            calls.append(str(request.url))
        if request.url.host == "raw.githubusercontent.com":
            relative = path.split("/commit-123/", 1)[1]
            content = files.get(relative)
            return httpx.Response(404) if content is None else httpx.Response(200, content=content.encode())
        if path.endswith("/readme"):
            return httpx.Response(200, json={"encoding":"base64","content":base64.b64encode(b"# Tools").decode()})
        if "/branches/" in path:
            return httpx.Response(200, json={"commit":{"sha":"commit-123","commit":{"tree":{"sha":"root-tree"}}}})
        if "/git/trees/" in path:
            key = path.rsplit("/",1)[-1]+("?recursive=1" if request.url.params.get("recursive") else "")
            value = trees[key]
            return httpx.Response(503) if value is None else httpx.Response(200, json=value)
        return httpx.Response(200, json=REPO)
    return Fetcher(db, transport=httpx.MockTransport(handler), sleeper=lambda _:None)


def store(db, item):
    db.execute("INSERT INTO resources VALUES(?,?,?,?,?,?)",(item["id"],item["repo_id"],item["path"],item["kind"],dumps(item),utcnow()))


def test_truncated_tree_walks_subdirectories_with_commit_pinned_evidence(db):
    calls = []
    trees = {"root-tree?recursive=1":{"tree":[],"truncated":True},
             "root-tree":{"tree":[{"path":"skills","type":"tree","sha":"subtree"}],"truncated":False},
             "subtree":{"tree":[tree_file("tool/SKILL.md")],"truncated":False}}
    fetcher = scanner(db, trees, {"skills/tool/SKILL.md":SKILL}, calls)
    try:
        repo = collect_repo(db, fetcher, "owner/tools")
        report = repo["resource_scan_report"]
        assert report["status"] == "complete" and report["tree_requests"] == 3
        item = json.loads(db.rows("SELECT data FROM resources")[0]["data"])
        assert item["url"] == "https://github.com/owner/tools/blob/commit-123/skills/tool/SKILL.md"
        assert item["compatibility_evidence"][0]["quote"] == "Requires Python and network access"
        assert item["content_hash"] and not any("recursive=0" in url for url in calls)
    finally:
        fetcher.close()


def test_tree_budget_is_explicit_and_known_files_still_get_read(db):
    trees = {"root-tree?recursive=1":{"tree":[tree_file("SKILL.md")],"truncated":True},
             "root-tree":{"tree":[tree_file("SKILL.md"),{"path":"more","type":"tree","sha":"more-tree"}],"truncated":False}}
    fetcher = scanner(db, trees, {"SKILL.md":SKILL})
    try:
        records, report = scan_resources(REPO, fetcher, tree_limit=2)
        assert len(records)==1 and report["status"]=="partial"
        assert "tree_request_limit" in report["reasons"] and report["tree_requests"]==2
    finally:
        fetcher.close()


def test_partial_scan_retains_old_resources_and_marks_them_as_previous(settings):
    app = create_app(settings)
    db = app.state.db
    add_repo(db, full_name="owner/tools")
    old = resource_record(REPO,"skills/old/SKILL.md",SKILL,"old-commit")
    store(db,old)
    trees={"root-tree?recursive=1":{"tree":[tree_file("skills/tool/SKILL.md"),tree_file("skills/z/SKILL.md")],"truncated":False}}
    fetcher=scanner(db,trees,{"skills/tool/SKILL.md":SKILL})
    try:
        repo=collect_repo(db,fetcher,"owner/tools",resource_limit=1)
        assert repo["resource_scan"]=="partial" and "resource_file_limit" in repo["resource_scan_report"]["reasons"]
        assert len(db.rows("SELECT * FROM resources"))==2
        output=TestClient(app).get("/api/agent-resources/"+old["id"]).json()
        assert output["verification_status"]=="previous" and output["commit"]=="old-commit"
    finally:
        fetcher.close()


def test_complete_scan_removes_deleted_resource_but_never_daily_history(db):
    fetcher=scanner(db,{"root-tree?recursive=1":{"tree":[tree_file("SKILL.md")],"truncated":False}},{"SKILL.md":SKILL})
    try:
        collect_repo(db,fetcher,"owner/tools")
    finally:
        fetcher.close()
    fetcher=scanner(db,{"root-tree?recursive=1":{"tree":[],"truncated":False}}, {})
    try:
        assert collect_repo(db,fetcher,"owner/tools")["resource_scan"]=="complete"
        assert db.rows("SELECT * FROM resources")==[]
        assert len(db.rows("SELECT * FROM snapshots"))==1
    finally:
        fetcher.close()


def test_symlink_and_oversize_file_are_not_fetched(db):
    calls=[]
    trees={"root-tree?recursive=1":{"tree":[tree_file("SKILL.md",mode="120000"),tree_file("big/SKILL.md",size=200001)],"truncated":False}}
    fetcher=scanner(db,trees,{},calls)
    try:
        records,report=scan_resources(REPO,fetcher)
        assert not records and "file_size_limit" in report["reasons"]
        assert not any("raw.githubusercontent.com" in url for url in calls)
    finally:
        fetcher.close()


def test_mcp_manifest_requires_recognized_schema_and_does_not_copy_secrets():
    metadata={"$schema":"https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json","name":"io.example/server","description":"Example server","version":"1.0",
              "packages":[{"transport":{"type":"stdio"},"environmentVariables":[{"name":"TOKEN","value":"do-not-publish"}]}]}
    item=resource_record(REPO,"server.json",json.dumps(metadata),"sha")
    assert item["kind"]=="mcp" and item["compatibility_evidence"][0]["field"]=="packages[0].transport.type"
    assert "do-not-publish" not in json.dumps(item)
    metadata["$schema"]="https://unrelated.example/server.schema.json"
    assert resource_record(REPO,"server.json",json.dumps(metadata),"sha") is None


def test_missing_compatibility_is_not_reported_as_a_declared_integration():
    item=resource_record(REPO,".claude-plugin/plugin.json",'{"name":"tool","description":"A plugin"}',"sha")
    assert item["ecosystem"]=="claude-code"
    assert item["compatibility"]=="未声明" and item["compatibility_evidence"]==[]
    assert item["compatibility_status"]=="未声明兼容要求"


def test_hash_covers_instructions_not_just_name_and_description():
    first=resource_record(REPO,"SKILL.md",SKILL,"sha1")
    second=resource_record(REPO,"SKILL.md",SKILL+"Different instruction", "sha2")
    assert first["id"]==second["id"] and first["content_hash"]!=second["content_hash"]


def test_duplicate_group_search_details_and_excluded_sources_are_consistent(settings):
    app=create_app(settings)
    db=app.state.db
    for repo_id in (1,2):
        add_repo(db,repo_id)
        store(db,resource_record({"id":repo_id,"full_name":f"owner/repo-{repo_id}"},"skills/tool/SKILL.md",SKILL,"sha"))
    client=TestClient(app)
    result=client.get("/api/agent-resources").json()
    assert result["total"]==1 and result["matching_source_total"]==2
    assert result["items"][0]["duplicate_count"]==2
    assert client.get("/api/agent-resources?group_duplicates=false").json()["total"]==2
    searched=client.get("/api/agent-resources?q=owner/repo-2").json()
    assert searched["items"][0]["repo_id"]==2
    item_id=result["items"][0]["id"]
    assert client.get("/api/agent-resources/"+item_id).json()["duplicate_count"]==2
    edit_repository(db,"owner/repo-2",excluded=True,reason="排除重复来源")
    assert client.get("/api/agent-resources").json()["items"][0]["duplicate_count"]==1
    assert client.get("/api/agent-resources?kind=unrecognized").status_code==422


def test_legacy_records_without_hash_are_not_assumed_to_be_identical(settings):
    app=create_app(settings)
    for repo_id in (1,2):
        add_repo(app.state.db,repo_id)
        item=resource_record({"id":repo_id,"full_name":f"owner/repo-{repo_id}"},"SKILL.md",SKILL,"sha")
        item.pop("content_hash")
        item.pop("compatibility_evidence")
        store(app.state.db,item)
    items=TestClient(app).get("/api/agent-resources").json()["items"]
    assert len(items)==2
    assert all(r["verification_status"]=="unknown" and r["compatibility_status"]=="未保留兼容声明证据" for r in items)


def test_resource_pagination_is_after_duplicate_grouping(settings):
    app=create_app(settings)
    for repo_id in (1,2,3):
        add_repo(app.state.db,repo_id)
        content=SKILL if repo_id<3 else SKILL+"Different instructions"
        store(app.state.db,resource_record({"id":repo_id,"full_name":f"owner/repo-{repo_id}"},"SKILL.md",content,"sha"))
    client=TestClient(app)
    first=client.get("/api/agent-resources?limit=1").json()
    second=client.get("/api/agent-resources?limit=1&offset=1").json()
    assert first["total"]==second["total"]==2
    assert first["items"][0]["duplicate_count"]==2
    assert second["items"][0]["repo_id"]==3 and second["offset"]==1
    assert client.get("/api/agent-resources?offset=-1").status_code==422


def test_malformed_tree_response_cannot_clear_existing_resources(db):
    add_repo(db,full_name="owner/tools")
    store(db,resource_record(REPO,"SKILL.md",SKILL,"old-sha"))
    fetcher=scanner(db,{"root-tree?recursive=1":{},"root-tree":{}},{})
    try:
        assert collect_repo(db,fetcher,"owner/tools")["resource_scan"]=="failed"
        assert len(db.rows("SELECT * FROM resources"))==1
    finally:
        fetcher.close()


def test_collection_stop_propagates_out_of_resource_scan(db):
    fetcher=Fetcher(db,cancelled=lambda:True)
    try:
        with pytest.raises(CollectionCancelled):
            scan_resources(REPO,fetcher)
    finally:
        fetcher.close()


def test_shared_resource_budget_does_not_consume_metadata_requests(db):
    calls=[]
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200,json={"commit":{"sha":"sha"}})
    fetcher=Fetcher(db,transport=httpx.MockTransport(handler),resource_budget=1)
    try:
        records,report=scan_resources(REPO,fetcher)
        assert records==[] and "batch_resource_budget" in report["reasons"]
        assert fetcher.resource_requests==1
        assert fetcher.get("https://api.github.com/repos/owner/tools")
        assert len(calls)==2
    finally:
        fetcher.close()


def test_public_directory_fallback_verifies_commit_and_never_claims_full_coverage(db):
    repo={**REPO,"_data_source":"github_public_page","_sha":"commit-123",
          "_tree":[{"name":"skills","path":"skills","contentType":"directory"}],"_soup":BeautifulSoup("", "html.parser")}
    payload={"payload":{"codeViewTreeRoute":{"refInfo":{"currentOid":"commit-123"},"tree":{"items":[{"path":"skills/SKILL.md","contentType":"file"}]}}}}
    def handler(request):
        if request.url.host=="raw.githubusercontent.com":
            return httpx.Response(200,text=SKILL)
        return httpx.Response(200,text='<script data-target="react-app.embeddedData">'+json.dumps(payload)+'</script>')
    fetcher=Fetcher(db,transport=httpx.MockTransport(handler))
    try:
        records,report=scan_resources(repo,fetcher)
        assert len(records)==1 and report["status"]=="partial"
        assert not report["tree_complete"] and "page_is_partial" in report["reasons"]
        payload["payload"]["codeViewTreeRoute"]["refInfo"]["currentOid"]="other-commit"
        records,report=scan_resources(repo,fetcher)
        assert records==[] and "page_directory_unavailable" in report["reasons"]
    finally:
        fetcher.close()
