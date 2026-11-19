from datetime import datetime, timedelta, timezone
import json
import sys
import pytest
from fastapi.testclient import TestClient
from conftest import add_repo, snapshot
from test_agent_resources import SKILL, store
from github_rank.agent_resources import resource_record
from github_rank.api import create_app
from github_rank.cli import main
from github_rank.coverage import coverage_report, coverage_markdown
from github_rank.db import dumps
from github_rank.ranking import compute_rankings
from github_rank.repositories import edit_repository
from github_rank.settings import Settings
from github_rank.sources import set_enabled


NOW = datetime(2026,11,19,8,tzinfo=timezone.utc)


def test_current_audit_does_not_use_stale_last_snapshot_as_endpoint(db):
    add_repo(db)
    for days,stars in ((27,100),(20,200)):
        snapshot(db,1,(NOW-timedelta(days=days)).isoformat(),stars)
    assert compute_rankings(db,7)["items"][0]["hot_eligible"]
    report=coverage_report(db,now=NOW)
    weekly=report["rankings"][0]
    assert weekly["hot_eligible"]==0
    assert weekly["blockers"]["hot"]=={"missing_end":1,"missing_start":1}
    assert report["history"]["observed_days"]==2
    assert report["history"]["days_without_observation"]==26
    assert report["history"]["stale"] is True


def test_empty_audit_is_safe_and_does_not_fabricate_observations(db):
    report=coverage_report(db,now=NOW)
    assert report["history"]["observed_days"]==report["history"]["days_without_observation"]==0
    assert report["history"]["last_observation"] is None
    assert report["refresh_candidates"]==[]
    assert report["scheduler"]["online"] is False
    assert all(window["included"]==0 for window in report["rankings"])


def test_fresh_daily_snapshot_uses_actual_anchor_and_does_not_hide_other_stale_repos(db):
    add_repo(db,1,pushed_at=NOW.isoformat())
    add_repo(db,2)
    latest=NOW-timedelta(hours=8)
    snapshot(db,1,latest.isoformat(),200)
    snapshot(db,1,(latest-timedelta(days=7)).isoformat(),100)
    db.execute("UPDATE repositories SET updated_at=? WHERE id=1",(latest.isoformat(),))
    report=coverage_report(db,now=NOW)
    assert report["rankings"][0]["hot_eligible"]==1
    assert report["rankings"][0]["as_of"]==latest.isoformat(timespec="seconds")
    assert report["history"]["current_endpoint_count"]==1
    assert report["repositories"]["metadata_fresh"]==report["repositories"]["metadata_stale"]==1


def test_report_excludes_curated_projects_and_their_resources(db):
    a=add_repo(db,1,data_source="github_api")
    b=add_repo(db,2)
    store(db,resource_record(a,"skills/tool/SKILL.md",SKILL,"commit"))
    store(db,resource_record(b,"skills/tool/SKILL.md",SKILL,"commit"))
    edit_repository(db,b["full_name"],excluded=True,reason="排除样本")
    report=coverage_report(db,now=NOW)
    assert report["repositories"]["tracked"]==2 and report["repositories"]["excluded"]==1
    assert report["resources"]["included_records"]==report["resources"]["excluded_records"]==1
    assert report["resources"]["with_file_hash"]==1
    assert all(window["included"]==1 and window["excluded"]==1 for window in report["rankings"])
    assert {r["id"] for r in report["refresh_candidates"]}=={1}


def test_priority_uses_staleness_and_gaps_and_respects_limit(db):
    add_repo(db,1,data_source="github_api",resource_scan="complete",
             resource_scan_report={"status":"complete","observed_at":NOW.isoformat()})
    add_repo(db,2,data_source="github_public_page",resource_scan="partial")
    add_repo(db,3,archived=True)
    db.execute("UPDATE repositories SET updated_at=? WHERE id=1",(NOW.isoformat(),))
    report=coverage_report(db,limit=1,now=NOW)
    assert report["refresh_candidate_total"]==1 and report["refresh_candidates"][0]["id"]==2
    assert "resource_incomplete" in report["refresh_candidates"][0]["reasons"]
    assert report["resources"]["scan_repositories"]=={"complete":1,"partial":1,"not_scanned":1}
    assert coverage_report(db,limit=0,now=NOW)["refresh_candidates"]==[]
    assert report["resources"]["stale_or_undated_scans"]==2


@pytest.mark.parametrize("overrides,days,stars,expected",[
    ({"archived":True},range(15),100,"inactive_repository"),
    ({},[0],100,"missing_start"),
    ({},[7],100,"missing_end"),
    ({},[0,7],100,"non_positive_growth"),
    ({"pushed_at":None},range(15),100,"missing_push_time"),
    ({"pushed_at":(NOW-timedelta(days=31)).isoformat()},range(15),100,"push_too_old"),
    ({},[0,7,14],100,"insufficient_coverage"),
    ({},range(15),30000,"size_outside_range"),
])
def test_machine_reasons_agree_with_ranking_qualification(db,overrides,days,stars,expected):
    add_repo(db,pushed_at=NOW.isoformat(),**{k:v for k,v in overrides.items() if k!="pushed_at"})
    if "pushed_at" in overrides:
        repo=json.loads(db.rows("SELECT data FROM repositories")[0]["data"])
        db.execute("UPDATE repositories SET data=?",(dumps({**repo,"pushed_at":overrides["pushed_at"]}),))
    for index,day in enumerate(days):
        # Constant values in the endpoint-only case exercise non-positive growth.
        value=stars if len(days)==2 else stars+100-index*5
        snapshot(db,1,(NOW-timedelta(days=day)).isoformat(),value)
    item=compute_rankings(db,7,NOW.isoformat())["items"][0]
    assert expected in item["eligibility_reasons"]["potential"]
    assert item["hot_eligible"] == (not item["eligibility_reasons"]["hot"])
    assert item["potential_eligible"] == (not item["eligibility_reasons"]["potential"])


def test_full_history_has_only_peer_blocker_until_thirty_peers(db):
    for repo_id in range(1,31):
        add_repo(db,repo_id,pushed_at=NOW.isoformat())
        for day in range(15):
            snapshot(db,repo_id,(NOW-timedelta(days=day)).isoformat(),1000-day*10)
        if repo_id==1:
            item=compute_rankings(db,7,NOW.isoformat())["items"][0]
            assert item["eligibility_reasons"]["potential"]==["insufficient_peers"]
    items=compute_rankings(db,7,NOW.isoformat())["items"]
    assert all(item["potential_eligible"] and item["eligibility_reasons"]["potential"]==[] for item in items)


def test_report_separates_paused_stale_and_failed_source_state(db):
    for source_id,status in (("paused","ok"),("failed","error")):
        data={"id":source_id,"name":source_id,"interval_minutes":30}
        db.execute("INSERT INTO sources(id,data,last_success_at,status) VALUES(?,?,?,?)",
                   (source_id,dumps(data),(NOW-timedelta(days=2)).isoformat(),status))
    set_enabled(db,"paused",False)
    report=coverage_report(db,now=NOW)
    assert report["news_sources"]["freshness"]=={"stale":1,"paused":1}
    failed=next(s for s in report["news_sources"]["items"] if s["id"]=="failed")
    assert failed["status"]=="error" and failed["freshness"]=="stale"


def test_read_transaction_keeps_all_report_sections_consistent(db,monkeypatch):
    add_repo(db)
    import github_rank.coverage as module
    original=module.compute_rankings
    calls=[]
    def concurrent_write(view,window,stamp):
        calls.append(window)
        if len(calls)==1:
            add_repo(db,2)
        return original(view,window,stamp)
    monkeypatch.setattr(module,"compute_rankings",concurrent_write)
    report=coverage_report(db,now=NOW)
    assert report["repositories"]["tracked"]==1
    assert all(window["included"]==1 for window in report["rankings"])
    assert len(db.rows("SELECT id FROM repositories"))==2


def test_api_validates_budget_and_reports_without_personal_writes(settings):
    app=create_app(settings)
    add_repo(app.state.db)
    before=app.state.db.rows("SELECT * FROM repositories")
    client=TestClient(app)
    for limit in (-1,101):
        assert client.get("/api/coverage",params={"limit":limit}).status_code==422
    assert client.get("/api/coverage?limit=0").json()["refresh_candidates"]==[]
    assert app.state.db.rows("SELECT * FROM repositories")==before
    assert client.post("/api/coverage").status_code==405


def test_cli_exports_utf8_and_preserves_existing_reports(settings,monkeypatch,capsys,tmp_path):
    monkeypatch.setattr(Settings,"from_env",lambda:settings)
    settings.config_path.write_text("invalid: [",encoding="utf-8")
    output=tmp_path/"coverage.md"
    args=["github-rank","coverage","--format","markdown","--output",str(output)]
    monkeypatch.setattr(sys,"argv",args)
    main()
    assert "数据覆盖体检" in output.read_text(encoding="utf-8")
    previous=output.read_bytes()
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code==2
    assert output.read_bytes()==previous
    assert "coverage.md" in capsys.readouterr().err


def test_markdown_renders_counts_and_escapes_repository_names(db):
    add_repo(db,full_name="owner/<unsafe|name>")
    rendered=coverage_markdown(coverage_report(db,now=NOW))
    assert "&lt;unsafe\\|name&gt;" in rendered
    assert "刷新只能补当前观测" in rendered
    for limit in (-1,101,True):
        with pytest.raises(ValueError): coverage_report(db,limit,now=NOW)
    with pytest.raises(ValueError): coverage_report(db,now=NOW.replace(tzinfo=None))
