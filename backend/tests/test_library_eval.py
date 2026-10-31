from copy import deepcopy
from dataclasses import replace
import json
import pytest
from fastapi.testclient import TestClient
from conftest import add_repo
from test_agent_resources import SKILL, store
from test_news_events import article
from test_summaries_sources import FakeProvider
from github_rank.agent_resources import resource_record
from github_rank.api import create_app
from github_rank.db import dumps
from github_rank.library import resolve_library
from github_rank.repositories import edit_repository
from github_rank.summaries import summarize
from github_rank.summary_eval import prepare_evaluation, evaluation_report, write_json


def test_library_keeps_stable_identity_after_rename_and_name_reuse(db):
    original=add_repo(db)
    renamed={**original,"full_name":"new-owner/renamed","url":"https://github.com/new-owner/renamed"}
    db.execute("UPDATE repositories SET full_name=?,data=? WHERE id=1",(renamed["full_name"],dumps(renamed)))
    add_repo(db,2,full_name=original["full_name"])
    result=resolve_library(db,projects="1,2,1,99")["items"]
    assert [r["id"] for r in result]==["1","2","99"]
    assert result[0]["data"]["full_name"]=="new-owner/renamed"
    assert result[1]["data"]["full_name"]==original["full_name"]
    assert result[2]=={"type":"project","id":"99","state":"missing","data":None}


def test_library_excluded_resources_and_news_keep_source_identity(db):
    repo=add_repo(db)
    resource=resource_record(repo,"skills/tool/SKILL.md",SKILL,"abc123")
    store(db,resource)
    a,b=article(db,"a"),article(db,"b")
    edit_repository(db,repo["full_name"],excluded=True,reason="本机排除")
    result=resolve_library(db,projects="1",resources=resource["id"]+",ffffffffffffffffffffffffffffffff",news=a["id"]+","+b["id"])["items"]
    assert result[0]["state"]==result[1]["state"]=="excluded"
    assert result[2]["state"]=="missing"
    assert result[3]["data"]["id"]==a["id"] and result[4]["data"]["id"]==b["id"]
    assert result[3]["data"]["report_count"]==2
    assert len(db.rows("SELECT * FROM repository_edits"))==1


def test_library_api_rejects_invalid_or_oversized_references(settings):
    client=TestClient(create_app(settings))
    for params in ({"projects":"-1"},{"projects":"9007199254740992"},{"resources":"../file"},{"news":"wrong"},{"projects":",".join(map(str,range(1,202)))}):
        assert client.get("/api/library",params=params).status_code==422
    assert client.get("/api/library").json()["items"]==[]
    assert client.post("/api/library",json={"reading":{}}).status_code==405


def test_eval_balances_categories_and_never_invents_outputs(db):
    for i in range(1,5): add_repo(db,i,category="ai" if i<4 else "devtools")
    article(db,"news")
    repo=json.loads(db.rows("SELECT data FROM repositories WHERE id=1")[0]["data"])
    store(db,resource_record(repo,"skills/tool/SKILL.md",SKILL,"abc123"))
    before=db.rows("SELECT * FROM summary_attempts")
    packet=prepare_evaluation(db,2,1,1)
    assert packet["selected"]=={"project":2,"news":1,"resource":1}
    assert [s["entity_id"] for s in packet["samples"] if s["entity_kind"]=="project"]==["1","4"]
    report=evaluation_report(packet)
    assert report["counts"]["missing_outputs"]==4
    assert report["human_pass_rate"] is report["automatic_validity_rate"] is None
    assert db.rows("SELECT * FROM summary_attempts")==before
    assert [s["sample_id"] for s in prepare_evaluation(db,2,1,1)["samples"]]==[s["sample_id"] for s in packet["samples"]]


def test_eval_cached_output_requires_manual_review_and_current_input(settings,db):
    repo=add_repo(db)
    provider=FakeProvider()
    assert summarize(replace(settings,summary_model="test"),db,"project",provider=provider)["generated"]==1
    packet=prepare_evaluation(db,1,0,0,model="test")
    report=evaluation_report(packet)
    assert report["counts"]["awaiting_review"]==1 and report["human_pass_rate"] is None
    assert packet["samples"][0]["candidate_meta"]["model"]=="test" and provider.calls==1
    packet["samples"][0]["review"]={"facts_supported":True,"chinese_clear":True,"useful":False}
    report=evaluation_report(packet)
    assert report["counts"]["human_rejected"]==1 and report["human_pass_rate"]==0
    packet["samples"][0]["review"]["useful"]=True
    assert evaluation_report(packet)["human_pass_rate"]==1
    assert prepare_evaluation(db,1,0,0,model="different")["samples"][0]["candidate"] is None
    db.execute("UPDATE repositories SET data=? WHERE id=1",(dumps({**repo,"description":"Changed source description"}),))
    assert prepare_evaluation(db,1,0,0)["samples"][0]["candidate"] is None


@pytest.mark.parametrize("field,value",[("quote","This quotation does not occur in the input"),("url","https://incorrect.example/source")])
def test_eval_checks_quote_and_citation_url(settings,db,field,value):
    add_repo(db)
    summarize(replace(settings,summary_model="test"),db,"project",provider=FakeProvider())
    packet=prepare_evaluation(db,1,0,0)
    packet["samples"][0]["candidate"]["evidence"][0][field]=value
    report=evaluation_report(packet)
    assert report["counts"]["invalid_output"]==1 and report["automatic_validity_rate"]==0
    assert report["human_pass_rate"] is None


def test_eval_changed_and_malformed_inputs_are_reported_without_crashing(db):
    add_repo(db)
    packet=prepare_evaluation(db,1,0,0)
    changed=deepcopy(packet["samples"][0])
    changed["input"]["name"]="Changed"
    packet["samples"]=[changed,None,{"sample_id":[],"input":None}]
    assert evaluation_report(packet)["counts"]["invalid_input"]==3
    for sample in ({"sample_id":"x","input":{}}, {"sample_id":"x","input":{"kind":"project","sources":[None]}}):
        packet["samples"]=[sample]
        assert evaluation_report(packet)["counts"]["invalid_input"]==1


def test_eval_exclusions_limits_and_output_file_preservation(db,tmp_path):
    repo=add_repo(db)
    add_repo(db,2,archived=True)
    store(db,resource_record(repo,"skills/tool/SKILL.md",SKILL,"abc123"))
    edit_repository(db,repo["full_name"],excluded=True,reason="排除")
    packet=prepare_evaluation(db)
    assert packet["selected"]=={"project":0,"news":0,"resource":0}
    for counts in ((0,0,0),(-1,1,0),(101,0,0),(True,0,0)):
        with pytest.raises(ValueError): prepare_evaluation(db,*counts)
    path=tmp_path/"evaluation.json"
    write_json(path,packet)
    with pytest.raises(FileExistsError): write_json(path,{"changed":True})
    assert json.loads(path.read_text(encoding="utf-8"))==packet
    with pytest.raises(ValueError): write_json(tmp_path/"packet.txt",packet)


def test_library_shows_only_current_cached_summary(settings,db):
    repo=add_repo(db)
    summarize(replace(settings,summary_model="test"),db,"project",provider=FakeProvider())
    assert resolve_library(db,projects="1")["items"][0]["data"]["summary_zh"]
    db.execute("UPDATE repositories SET data=? WHERE id=1",(dumps({**repo,"description":"A new source description"}),))
    assert "summary_zh" not in resolve_library(db,projects="1")["items"][0]["data"]
