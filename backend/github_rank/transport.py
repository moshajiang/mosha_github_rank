"""Bounded reads, conditional requests and explicit rate-limit failures."""
import time
from urllib.parse import urlsplit
import httpx
from .db import utcnow


class FetchError(RuntimeError):
    pass


class RateLimited(FetchError):
    pass


class Fetcher:
    def __init__(self, db, token="", transport=None, sleeper=time.sleep):
        self.db, self.token, self.sleep = db, token, sleeper
        self.github_requests = 0
        self.github_blocked = set()
        self.client = httpx.Client(timeout=20, follow_redirects=True, transport=transport,
                                   headers={"User-Agent": "GitHubRank/0.1 (+local research reader)"})

    def close(self):
        self.client.close()

    def get(self, url):
        if urlsplit(url).scheme != "https":
            raise FetchError("Only HTTPS sources are supported")
        cache = self.db.rows("SELECT * FROM http_cache WHERE url=?", (url,))
        headers = {}
        if cache:
            if cache[0]["etag"]:
                headers["If-None-Match"] = cache[0]["etag"]
            if cache[0]["modified"]:
                headers["If-Modified-Since"] = cache[0]["modified"]
        if urlsplit(url).hostname == "api.github.com":
            headers["Accept"] = "application/vnd.github+json"
            if self.token:
                headers["Authorization"] = "Bearer " + self.token
        for attempt in range(3):
            try:
                if urlsplit(url).hostname == "api.github.com":
                    bucket = "search" if urlsplit(url).path.startswith("/search/") else "core"
                    if bucket in self.github_blocked:
                        raise RateLimited(f"GitHub {bucket} rate limit active for this batch")
                    if not self.token and self.github_requests >= 45:
                        raise RateLimited("Unauthenticated batch budget reached (45 requests); configure a server token for larger collections")
                    self.github_requests += 1
                with self.client.stream("GET", url, headers=headers) as response:
                    if response.status_code == 304:
                        if not cache:
                            raise FetchError("304 without a cached representation")
                        return cache[0]["body"]
                    limited = response.status_code == 429 or (
                        response.status_code == 403 and (
                            response.headers.get("X-RateLimit-Remaining") == "0"
                            or response.headers.get("Retry-After")
                        )
                    )
                    if limited:
                        if urlsplit(url).hostname == "api.github.com":
                            if response.headers.get("X-RateLimit-Remaining") == "0":
                                self.github_blocked.add(response.headers.get("X-RateLimit-Resource", bucket))
                            else:
                                self.github_blocked.update(("core", "search"))
                        reset = response.headers.get("Retry-After") or response.headers.get("X-RateLimit-Reset", "unknown")
                        raise RateLimited(f"Rate limit reached; retry/reset: {reset}")
                    if response.status_code >= 500 and attempt < 2:
                        self.sleep(2 ** attempt)
                        continue
                    if response.status_code >= 400:
                        raise FetchError(f"Upstream HTTP {response.status_code}")
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > 5_000_000:
                            raise FetchError("Source exceeds the 5 MB response limit")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    self.db.execute(
                        "INSERT INTO http_cache VALUES(?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET "
                        "etag=excluded.etag,modified=excluded.modified,body=excluded.body,updated_at=excluded.updated_at",
                        (url, response.headers.get("etag"), response.headers.get("last-modified"), body, utcnow()),
                    )
                    return body
            except httpx.TransportError as exc:
                if attempt == 2:
                    # Exception text can include URLs; avoid outputting credentials or full request details.
                    raise FetchError(type(exc).__name__) from exc
                self.sleep(2 ** attempt)
        raise FetchError("Request did not complete")
