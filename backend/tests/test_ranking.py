from datetime import datetime, timedelta, timezone
import json
import pytest
from conftest import add_repo, snapshot
from github_rank.ranking import compute_rankings, percentile, publish_rankings


END = datetime(2026, 10, 30, 8, tzinfo=timezone.utc)


def test_no_history_never_becomes_hot(db):
    add_repo(db)
    snapshot(db, 1, END.isoformat(), 5000)
    item = compute_rankings(db, 7, END.isoformat())["items"][0]
    assert item["delta_stars"] is None
    assert not item["hot_eligible"]
    assert item["potential_score"] is None


def test_net_growth_includes_unstars_and_negative_is_not_hot(db):
    add_repo(db)
    snapshot(db, 1, (END - timedelta(days=7)).isoformat(), 100)
    snapshot(db, 1, END.isoformat(), 90)
    item = compute_rankings(db, 7, END.isoformat())["items"][0]
    assert item["delta_stars"] == -10 and not item["hot_eligible"]


def test_missing_or_distant_endpoint_cannot_be_interpolated(db):
    add_repo(db)
    snapshot(db, 1, (END - timedelta(days=7, hours=7)).isoformat(), 100)
    snapshot(db, 1, END.isoformat(), 500)
    assert compute_rankings(db, 7, END.isoformat())["items"][0]["delta_stars"] is None


def test_full_history_but_small_peer_pool_has_no_formal_score(db):
    add_repo(db)
    for i in range(15):
        snapshot(db, 1, (END - timedelta(days=14 - i)).isoformat(), 500 + i * 10, i)
    item = compute_rankings(db, 7, END.isoformat())["items"][0]
    assert item["hot_eligible"]
    assert not item["potential_eligible"] and item["potential_score"] is None
    assert "30" in item["observation_note"]


def test_score_uses_sufficient_peers_and_average_tied_ranks(db):
    for repo_id in range(1, 31):
        add_repo(db, repo_id)
        for i in range(15):
            snapshot(db, repo_id, (END - timedelta(days=14 - i)).isoformat(), 500 + i * 10, i)
    items = compute_rankings(db, 7, END.isoformat())["items"]
    assert all(item["potential_eligible"] for item in items)
    assert len({item["potential_score"] for item in items}) == 1
    assert items[0]["score_peer_count"] == 30
    assert percentile(10, [10, 10, 10]) == .5


def test_sparse_dual_period_excluded_from_potential(db):
    add_repo(db)
    for days, stars in [(14, 100), (7, 150), (0, 300)]:
        snapshot(db, 1, (END - timedelta(days=days)).isoformat(), stars)
    item = compute_rankings(db, 7, END.isoformat())["items"][0]
    assert item["hot_eligible"] and not item["potential_eligible"]


def test_archive_is_immutable_after_repository_changes(db):
    add_repo(db)
    snapshot(db, 1, END.isoformat(), 100)
    runs = publish_rankings(db)
    before = db.rows("SELECT data FROM ranking_runs WHERE id=?", (runs[0],))[0]["data"]
    db.execute("DELETE FROM snapshots")
    assert db.rows("SELECT data FROM ranking_runs WHERE id=?", (runs[0],))[0]["data"] == before
