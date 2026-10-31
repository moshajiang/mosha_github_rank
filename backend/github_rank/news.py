from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
import calendar
import hashlib
import json
import re
import html
import unicodedata
import feedparser
from bs4 import BeautifulSoup
from .classify import news_topic
from .db import dumps, utcnow


def text(value, limit=1500):
    value = value or ""
    plain = BeautifulSoup(value, "html.parser").get_text(" ", strip=True) if "<" in value else html.unescape(value)
    return re.sub(r"\s+", " ", plain).strip()[:limit]


def canonical_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Invalid source URL")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


def iso_date(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # A date-only source must not be silently converted into an exact midnight timestamp.
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (ValueError, TypeError):
        return None


def parse_source_date(raw):
    exact = iso_date(raw)
    if exact:
        return exact, "timestamp"
    for pattern in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%d %B %Y"):
        try:
            day = datetime.strptime((raw or "").strip(), pattern).replace(tzinfo=timezone.utc)
            return day.isoformat(timespec="seconds"), "day"
        except ValueError:
            pass
    return None, "unknown"


def event_key(title, url, published_at, kind="official"):
    parts = urlsplit(url)
    arxiv = re.fullmatch(r"/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?", parts.path) if parts.hostname in ("arxiv.org", "www.arxiv.org", "export.arxiv.org") else None
    if arxiv:
        return "arxiv:" + arxiv.group(1)
    # Keep dot/hyphen-delimited version tokens: 5.1 must never become 51.
    normalized = " ".join(re.findall(r"\w+(?:[.-]\w+)*", unicodedata.normalize("NFKC", title).casefold()))
    stamp = iso_date(published_at)
    if stamp and len(normalized) >= 16 and kind != "paper":
        return "title-v2:" + hashlib.sha256(f"{normalized}:{stamp[:10]}".encode()).hexdigest()
    return "url:" + hashlib.sha256(url.encode()).hexdigest()


def build_item(source, title, url, summary="", published_at=None, raw_date=None):
    url = canonical_url(url)
    title = text(title, 400)
    if not title:
        raise ValueError("Missing article title")
    summary = text(summary)
    topic = news_topic(title + " " + summary, source.get("kind", "official"))
    repo_links = sorted({u.rstrip(".,;:") for u in re.findall(r"https://github\.com/[\w.-]+/[\w.-]+", summary)})
    return {
        "id": hashlib.sha256(url.encode()).hexdigest()[:32], "source_id": source["id"],
        "source_name": source["name"], "source_kind": source.get("kind", "official"),
        "title": title, "url": url, "summary": summary, "summary_method": "original",
        "topic": topic, "published_at": published_at, "raw_published_at": raw_date,
        "event_key": event_key(title, url, published_at, source.get("kind", "official")), "related_repositories": repo_links,
        "importance": 3 if topic in ("agents", "models") else 2 if topic in ("research", "multimodal") else 1,
        "importance_reason": "按主题优先级展示，非全网热度", "is_preprint": source.get("kind") == "paper",
    }


def parse_feed(source, body):
    parsed = feedparser.parse(body)
    if not parsed.get("version"):
        raise ValueError("Response is not a recognized RSS/Atom feed")
    result = []
    for entry in parsed.entries:
        if not entry.get("link"):
            continue
        published = entry.get("published_parsed") if "published_parsed" in entry.keys() else None
        timestamp = datetime.fromtimestamp(calendar.timegm(published), timezone.utc).isoformat(timespec="seconds") if published else None
        try:
            item = build_item(source, entry.get("title", ""), urljoin(source["url"], entry.link),
                              entry.get("summary", ""), timestamp, entry.get("published"))
            item["published_precision"] = "timestamp" if timestamp else "unknown"
            # FeedParserDict can alias missing updated_parsed to published_parsed.
            # Only an actual parsed updated field is evidence of a source update time.
            updated = entry.get("updated_parsed") if "updated_parsed" in entry.keys() else None
            item["source_updated_at"] = datetime.fromtimestamp(calendar.timegm(updated), timezone.utc).isoformat(timespec="seconds") if updated else None
            # Preserve verified href targets before stripping HTML.
            soup = BeautifulSoup(entry.get("summary", ""), "html.parser")
            item["related_repositories"] = sorted(set(
                re.sub(r"^(https://github\.com/[\w.-]+/[\w.-]+).*$", r"\1", a["href"])
                for a in soup.select('a[href]') if re.match(r"^https://github\.com/[\w.-]+/[\w.-]+(?:/|$)", a["href"])
            ) | set(item["related_repositories"]))
            result.append(item)
        except ValueError:
            continue
    return result


def parse_html(source, body):
    soup = BeautifulSoup(body, "html.parser")
    pattern = re.compile(source["article_pattern"])
    result, seen = [], set()
    scope = soup.find("main") or soup
    for anchor in scope.select("a[href]"):
        if anchor.find_parent(["nav", "footer"]):
            continue
        url = urljoin(source["url"], anchor["href"])
        if urlsplit(url).hostname != urlsplit(source["url"]).hostname or not pattern.match(urlsplit(url).path):
            continue
        title_node = anchor.select_one("h1,h2,h3,h4")
        container = anchor.find_parent("article") or anchor
        if not title_node and container is anchor:
            continue
        title = text(str(title_node) if title_node else anchor.get_text(" ", strip=True), 400)
        if len(title) < 12 or url in seen:
            continue
        date_node = container.find("time")
        raw_date = (date_node.get("datetime") or date_node.get_text(strip=True)) if date_node else None
        published_at, precision = parse_source_date(raw_date)
        summary_node = anchor.find("p")
        item = build_item(source, title, url, summary_node.get_text(" ", strip=True) if summary_node else "", published_at=published_at, raw_date=raw_date)
        item["published_precision"] = precision
        item["date_sort_timezone"] = "UTC 日期边界，仅用于排序" if precision == "day" else None
        result.append(item)
        seen.add(url)
    if not result:
        raise ValueError("No articles matched; source parser needs review")
    return result


def store_item(db, item):
    item = {k:v for k,v in item.items() if k != "content_updated"}
    now = utcnow()
    body_hash = hashlib.sha256(dumps(item).encode()).hexdigest()
    existing = db.rows("SELECT first_seen_at,content_hash FROM news WHERE url=?", (item["url"],))
    item["content_updated"] = bool(existing and existing[0]["content_hash"] != body_hash)
    with db.connect() as con:
        con.execute(
            "INSERT INTO news VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET "
            "event_key=excluded.event_key,title=excluded.title,topic=excluded.topic,published_at=excluded.published_at,"
            "fetched_at=excluded.fetched_at,content_hash=excluded.content_hash,data=excluded.data",
            (item["id"], item["event_key"], item["source_id"], item["url"], item["title"], item["topic"],
             item["published_at"], existing[0]["first_seen_at"] if existing else now, now, body_hash, dumps(item)),
        )
        con.execute("INSERT OR IGNORE INTO news_versions VALUES(?,?,?,?)", (item["id"], body_hash, dumps(item), now))


def collect_source(db, fetcher, source, limit=25):
    body = fetcher.get(source["url"])
    parser = parse_feed if source["adapter"] == "feed" else parse_html
    items = parser(source, body)
    for item in items[:limit]:
        store_item(db, item)
    return min(len(items), limit)
