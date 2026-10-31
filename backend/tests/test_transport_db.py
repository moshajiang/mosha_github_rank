import httpx
import pytest
from github_rank.db import Database
from github_rank.transport import Fetcher, RateLimited


def test_etag_304_reuses_verified_body(db):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"verified", headers={"etag": '"abc"'}) if len(calls) == 1 else httpx.Response(304)
    fetcher = Fetcher(db, transport=httpx.MockTransport(handler))
    try:
        assert fetcher.get("https://example.com/feed") == b"verified"
        assert fetcher.get("https://example.com/feed") == b"verified"
        assert calls[1].headers["if-none-match"] == '"abc"'
    finally:
        fetcher.close()


def test_rate_limit_stops_github_requests_but_other_sources_continue(db):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "60"}) if request.url.host == "api.github.com" else httpx.Response(200, content=b"ok")
    fetcher = Fetcher(db, token="test-secret", transport=httpx.MockTransport(handler))
    with pytest.raises(RateLimited):
        fetcher.get("https://api.github.com/repos/a/b")
    with pytest.raises(RateLimited):
        fetcher.get("https://api.github.com/repos/a/c")
    assert fetcher.get("https://example.com/feed") == b"ok"
    assert len(calls) == 2 and "authorization" not in calls[-1].headers
    fetcher.close()


def test_job_lease_and_backup_are_recoverable(db, tmp_path):
    with db.lease("collection"):
        with pytest.raises(RuntimeError):
            with db.lease("collection"):
                pass
    with db.lease("collection"):
        pass
    target = tmp_path / "backup.sqlite3"
    db.backup(target)
    assert Database(target).rows("SELECT count(*) AS n FROM leases")[0]["n"] == 0
    with pytest.raises(FileExistsError):
        db.backup(target)
