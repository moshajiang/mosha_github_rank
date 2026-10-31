from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from dataclasses import replace
import sqlite3
import sys
import pytest
from fastapi.testclient import TestClient
from github_rank.api import create_app
from github_rank.cli import main
from github_rank.db import Database, SCHEMA, MIGRATION_2, MIGRATION_3, MIGRATION_4
from github_rank.news import build_item, store_item, event_key, parse_feed
from github_rank.news_events import news_catalog, news_items, edit_events, edit_history, news_detail
from github_rank.classify import news_topic
from conftest import add_repo
from github_rank.summaries import summarize
from test_summaries_sources import FakeProvider


NOW = datetime(2026,10,31,8,tzinfo=timezone.utc)
SOURCE = {"id":"lab","name":"Lab","kind":"official","url":"https://lab.example/feed"}


def article(db, path, title="Introducing a reliable agent model", source=SOURCE, published=NOW.isoformat(), **extra):
    item={**build_item(source,title,"https://lab.example/"+path,"Source description",published),**extra}
    store_item(db,item)
    return item


def test_merge_expands_current_groups_and_refresh_does_not_undo_curation(db):
    a=article(db,"a")
    b=article(db,"b",source={**SOURCE,"id":"second","name":"Other Lab"})
    c=article(db,"c",title="Independent announcement in another language")
    assert news_catalog(db,"all",now=NOW)["total"]==2
    before=db.rows("SELECT data,content_hash FROM news ORDER BY id")
    result=edit_events(db,"merge",[a["id"],c["id"]],"人工核对为同一发布")
    assert result["affected_items"]==3
    assert db.rows("SELECT data,content_hash FROM news ORDER BY id")==before
    store_item(db,{**a,"summary":"Updated source description"})
    merged=news_catalog(db,"all",now=NOW)
    assert merged["total"]==1 and merged["items"][0]["report_count"]==3
    assert news_detail(db,b["id"])["grouping"]["method"]=="manual"


def test_split_and_reset_are_reversible_and_keep_audit(db):
    a,b=article(db,"a"),article(db,"b")
    edit_events(db,"split",[a["id"]],"标题相同但事件不同")
    assert news_catalog(db,"all",now=NOW)["total"]==2
    edit_events(db,"reset",[a["id"]],"恢复自动规则")
    assert news_catalog(db,"all",now=NOW)["total"]==1
    assert [r["action"] for r in reversed(edit_history(db,a["id"]))]==["split","reset"]
    assert len(db.rows("SELECT * FROM news_versions"))==2


def test_filters_select_representative_but_preserve_all_related_sources(db):
    a=article(db,"a")
    article(db,"b",source={**SOURCE,"id":"other","name":"Other Lab"})
    result=news_catalog(db,"24h",source="lab",now=NOW)
    assert result["total"]==1 and result["items"][0]["id"]==a["id"]
    item=result["items"][0]
    assert item["source_count"]==2 and item["report_count"]==2 and item["matching_report_count"]==1
    assert item["related_reports"][0]["id"]


def test_unknown_or_date_only_time_cannot_enter_24h_even_after_manual_merge(db):
    exact=article(db,"exact")
    unknown=article(db,"unknown",published=None)
    day=article(db,"day",published=NOW.replace(hour=0).isoformat(),published_precision="day")
    edit_events(db,"merge",[exact["id"],unknown["id"],day["id"]],"核对关联，保留各自时间精度")
    result=news_catalog(db,"24h",now=NOW)
    assert result["total"]==1 and result["items"][0]["id"]==exact["id"]
    assert result["items"][0]["matching_report_count"]==1 and result["unknown_time_total"]==2
    assert unknown["id"] in {r["id"] for r in result["unknown_time"]}


def test_local_version_view_does_not_rewrite_latest_or_show_later_ai_summary(settings):
    app=create_app(settings)
    db=app.state.db
    item=article(db,"versioned")
    old_hash=db.rows("SELECT content_hash FROM news")[0]["content_hash"]
    store_item(db,{**item,"title":"A corrected title for the same source","summary":"Corrected source summary"})
    assert summarize(replace(settings,summary_model="test"),db,"news",provider=FakeProvider())["generated"]==1
    client=TestClient(app)
    live=client.get("/api/news/"+item["id"]).json()
    old=client.get("/api/news/"+item["id"],params={"version_hash":old_hash}).json()
    assert old["title"]==item["title"] and live["title"]!=old["title"]
    assert old["version_view"]["is_current"] is False and len(old["versions"])==2
    assert "summary_zh" in live
    assert "summary_zh" not in old
    assert client.get("/api/news/"+item["id"]+"?version_hash="+"0"*64).status_code==404
    assert client.get("/api/news/"+item["id"]+"?version_hash=invalid").status_code==422


def test_reusing_same_input_object_does_not_fabricate_local_versions(db):
    item=article(db,"same")
    store_item(db,item)
    store_item(db,item)
    assert len(db.rows("SELECT * FROM news_versions"))==1


def test_atom_updated_does_not_become_first_publication_time():
    body=b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Lab</title><id>lab</id><updated>2026-10-31T08:00:00Z</updated><entry><id>post</id><title>A model announcement</title><link href="https://lab.example/item"/><updated>2026-10-31T08:00:00Z</updated></entry></feed>'
    item=parse_feed(SOURCE,body)[0]
    assert item["published_at"] is None and item["source_updated_at"]==NOW.isoformat()


def test_feedparser_publication_alias_is_not_used_as_source_update_time():
    body=b'<rss version="2.0"><channel><title>Lab</title><item><title>A model announcement</title><link>https://lab.example/item</link><pubDate>Sat, 31 Oct 2026 08:00:00 GMT</pubDate></item></channel></rss>'
    item=parse_feed(SOURCE,body)[0]
    assert item["published_at"]==NOW.isoformat()
    assert item["source_updated_at"] is None


def test_supervision_is_not_a_computer_vision_keyword(db):
    item=article(db,"supervision",source={**SOURCE,"kind":"paper"},title="Preference supervision for language alignment")
    assert news_topic(item["title"],"paper")=="research"
    # Legacy stored classifications are re-evaluated without altering source versions.
    db.execute("UPDATE news SET topic='multimodal'")
    assert news_catalog(db,"all",now=NOW)["items"][0]["topic"]=="research"
    assert news_topic("Image synthesis and computer vision","paper")=="multimodal"


def test_associated_project_requires_source_link_and_supports_observed_alias(settings):
    app=create_app(settings)
    db=app.state.db
    add_repo(db)
    item=article(db,"linked",related_repositories=["https://github.com/owner/repo-1","https://evil.example/owner/repo-1"])
    output=TestClient(app).get("/api/news/"+item["id"]).json()
    assert output["related_projects"]==[{"full_name":"owner/repo-1","url":"https://github.com/owner/repo-1","tracked":True}]


def test_invalid_edit_is_atomic_and_collection_lock_is_respected(db):
    a=article(db,"a")
    with pytest.raises(ValueError):
        edit_events(db,"merge",[a["id"],"missing"],"无效项不能部分提交")
    assert db.rows("SELECT * FROM news_event_overrides")==[]
    with db.lease("collection"):
        with pytest.raises(RuntimeError):
            edit_events(db,"split",[a["id"]],"等待采集结束")
    assert db.rows("SELECT * FROM news_event_edits")==[]


def test_cli_accepts_source_urls_and_audits_merge(settings,monkeypatch,capsys):
    db=Database(settings.db_path)
    a=article(db,"a")
    b=article(db,"b",title="同一发布的另一语言报道")
    monkeypatch.setattr("github_rank.cli.Settings.from_env",lambda:settings)
    monkeypatch.setattr(sys,"argv",["github-rank","news","merge",a["url"],b["id"],"--reason","核对原始来源"])
    main()
    assert json.loads(capsys.readouterr().out)["affected_items"]==2
    assert len(edit_history(db,a["id"]))==1


def test_v4_migration_preserves_news_versions_and_scheduler_state(tmp_path):
    path=tmp_path/"v4.sqlite3"
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA+MIGRATION_2+MIGRATION_3+MIGRATION_4)
        con.execute("INSERT INTO news VALUES('item','old-group','source','https://lab.example/item','Title','models',NULL,'old','old','hash','{}')")
        con.execute("INSERT INTO news_versions VALUES('item','hash','{}','old')")
        con.execute("INSERT INTO scheduler_state(id,instance_id,started_at,heartbeat_at,status,interval_seconds) VALUES(1,'worker','old','old','stopped',60)")
    db=Database(path)
    assert db.rows("PRAGMA user_version")[0]["user_version"]==5
    assert db.rows("SELECT content_hash FROM news_versions")==[{"content_hash":"hash"}]
    assert db.rows("SELECT instance_id FROM scheduler_state")==[{"instance_id":"worker"}]
    assert db.rows("PRAGMA integrity_check")[0]["integrity_check"]=="ok"


PAIRS=json.loads((Path(__file__).parent/"fixtures/news_event_pairs.json").read_text(encoding="utf-8"))
@pytest.mark.parametrize("pair",PAIRS,ids=[p["case"] for p in PAIRS])
def test_labeled_grouping_cases(pair):
    left,right=pair["left"],pair["right"]
    same=event_key(**left)==event_key(**right)
    assert same is pair["auto_merge_expected"]
