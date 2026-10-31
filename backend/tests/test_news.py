from github_rank.news import build_item, canonical_url, parse_feed, parse_html, store_item, event_key


SOURCE = {"id": "test", "name": "Test Lab", "url": "https://example.com/feed", "kind": "official", "adapter": "feed"}


def test_url_normalization_keeps_content_query():
    assert canonical_url("https://example.com/a?v=2&utm_source=x#heading") == "https://example.com/a?v=2"


def test_unknown_timestamp_does_not_become_fetch_time():
    feed = b'<rss version="2.0"><channel><title>Lab</title><item><title>Model 5 release</title><link>https://example.com/a</link><description>News</description></item></channel></rss>'
    item = parse_feed(SOURCE, feed)[0]
    assert item["published_at"] is None


def test_feed_timestamp_timezone_and_html_are_normalized():
    feed = b'<rss version="2.0"><channel><title>Lab</title><item><title>Model 5 release</title><link>https://example.com/a</link><pubDate>Fri, 30 Oct 2026 10:00:00 +0800</pubDate><description>&lt;b&gt;Hello&lt;/b&gt;</description></item></channel></rss>'
    item = parse_feed(SOURCE, feed)[0]
    assert item["published_at"] == "2026-10-30T02:00:00+00:00"
    assert item["summary"] == "Hello"


def test_same_item_is_idempotent_and_revision_preserves_first_seen(db):
    item = build_item(SOURCE, "Introducing model version 5", "https://example.com/a", "First", "2026-10-29T08:00:00+00:00")
    store_item(db, item.copy())
    first = db.rows("SELECT first_seen_at FROM news")[0]["first_seen_at"]
    store_item(db, item.copy())
    assert len(db.rows("SELECT * FROM news_versions")) == 1
    store_item(db, {**item, "summary": "Corrected"})
    assert len(db.rows("SELECT * FROM news")) == 1
    assert len(db.rows("SELECT * FROM news_versions")) == 2
    assert db.rows("SELECT first_seen_at FROM news")[0]["first_seen_at"] == first


def test_model_versions_are_not_merged():
    stamp = "2026-10-29T08:00:00+00:00"
    assert event_key("Introducing example model 5", "https://example.com/5", stamp) != event_key("Introducing example model 6", "https://example.com/6", stamp)
    assert event_key("Introducing example model 5", "https://example.com/5", stamp) == event_key("Introducing example model 5", "https://other.com/5", stamp)


def test_html_date_without_time_preserves_day_precision():
    source = {**SOURCE, "url": "https://example.com/news", "article_pattern": "^/news/.+$"}
    body = b'<article><a href="/news/model"><h2>Introducing example model 5</h2></a><time datetime="2026-10-30"></time></article>'
    item = parse_html(source, body)[0]
    assert item["published_precision"] == "day"
    assert item["raw_published_at"] == "2026-10-30"


def test_navigation_links_never_become_news_items():
    source = {**SOURCE, "url": "https://example.com/news", "article_pattern": "^/news/.+$"}
    body = b'<nav><a href="/news/nav"><h2>Navigation reference material</h2></a></nav><main><article><a href="/news/real"><h2>Introducing example model 5</h2></a><time>Oct 30, 2026</time></article></main>'
    items = parse_html(source, body)
    assert len(items) == 1 and items[0]["url"].endswith("/real")
