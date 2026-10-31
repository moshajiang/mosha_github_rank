"""Read-only local API smoke check; writes a non-sensitive validation report."""
from pathlib import Path
import json
import math
import time
import httpx


def main():
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
        paths = ["/api/health", "/api/config", "/api/projects", "/api/rankings?window=7d",
                 "/api/rankings?window=30d&kind=potential", "/api/agent-resources",
                 "/api/news?window=24h", "/api/news?window=7d", "/api/news/sources",
                 "/api/archives", "/api/projects/anthropics/skills", "/api/projects/anthropics/skills/history",
                 "/api/exports?format=json", "/api/exports?format=markdown", "/news", "/agents", "/saved"]
        checks = []
        for path in paths:
            result = client.get(path)
            checks.append({"path": path, "status": result.status_code})
            result.raise_for_status()
        status = client.get("/api/data-status").json()
        sources = client.get("/api/news/sources").json()["items"]
        times = []
        for _ in range(20):
            started = time.perf_counter()
            client.get("/api/rankings?window=7d").raise_for_status()
            times.append((time.perf_counter() - started) * 1000)
        report = {
            "as_of": status["as_of"], "counts": status["counts"], "api_checks": checks,
            "sources": [{k: s[k] for k in ("id", "status", "item_count", "error")} for s in sources],
            "ranking_query_p95_ms": round(sorted(times)[math.ceil(len(times) * .95) - 1], 2),
            "measurement": f"20 sequential local HTTP requests; {status['counts']['repositories']} repositories; warm process; no upstream calls",
        }
    path = Path(__file__).resolve().parents[1] / "data/validation-report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
