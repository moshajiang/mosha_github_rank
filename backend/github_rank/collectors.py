from datetime import datetime, timezone
from urllib.parse import quote
import base64
import json
import re
from bs4 import BeautifulSoup
from .classify import classify_repo, CATEGORIES
from .db import dumps, utcnow
from .transport import FetchError, RateLimited
from .repositories import normalize_name, apply_override, record_aliases
from .agent_resources import resource_record, scan_resources


REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def discover_from_list(fetcher, url, limit=150):
    body = fetcher.get(url).decode("utf-8", errors="replace")
    names = []
    for match in re.finditer(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", body):
        name = match.group(1).rstrip(".")
        if name.endswith(".git"):
            name = name[:-4]
        if name.split("/")[0] in {"sponsors", "topics", "orgs", "features", "settings"}:
            continue
        if name.lower() not in {n.lower() for n in names} and REPO_NAME.fullmatch(name):
            names.append(name)
    return names[:limit], {"url": url, "candidate_count": len(names), "bounded": len(names) > limit}


def github_json(fetcher, path):
    return json.loads(fetcher.get("https://api.github.com" + path))


def discover(fetcher, query, limit=10):
    data = github_json(fetcher, "/search/repositories?q=" + quote(query) + f"&sort=stars&per_page={min(limit, 100)}")
    return [r["full_name"] for r in data.get("items", [])], {
        "query": query, "total_count": data.get("total_count", 0),
        "incomplete": data.get("incomplete_results", False),
        "bounded": data.get("total_count", 0) > limit,
    }


def decode_content(data):
    if data.get("encoding") != "base64" or data.get("size", 0) > 200_000:
        return ""
    return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")


def page_payload(body):
    soup = BeautifulSoup(body, "html.parser")
    for script in soup.select('script[data-target="react-app.embeddedData"]'):
        data = json.loads(script.get_text()).get("payload", {})
        if "codeViewRepoRoute" in data:
            return soup, data
    raise FetchError("Public repository page has no recognized structured data")


def github_page_data(fetcher, name):
    soup, payload = page_payload(fetcher.get("https://github.com/" + name))
    layout = payload.get("codeViewLayoutRoute", {}).get("repo", {})
    route = payload["codeViewRepoRoute"]
    about = payload.get("sidebarAbout") or route.get("overview", {}).get("sidebarAboutData", {})
    if not isinstance(layout.get("id"), int) or not all(isinstance(about.get(key), int) for key in ("stargazerCount", "forksCount")):
        raise FetchError("Exact public counters unavailable; abbreviated values are not recorded")
    full_name = f"{layout['ownerLogin']}/{layout['name']}"
    readme = soup.select_one(".markdown-body")
    return {
        "id": layout["id"], "full_name": full_name, "html_url": "https://github.com/" + full_name,
        "description": about.get("description"), "topics": [t["name"] for t in about.get("topics", [])],
        "stargazers_count": about["stargazerCount"], "forks_count": about["forksCount"],
        "language": None, "license": None, "homepage": None,
        "created_at": layout.get("createdAt"), "pushed_at": None,
        "archived": layout.get("isArchived", False), "fork": layout.get("isFork", False),
        "default_branch": layout.get("defaultBranch", "main"),
        "_sha": route.get("refInfo", {}).get("currentOid"),
        "_soup": soup, "_tree": route.get("tree", {}).get("items", []),
        "_readme": readme.get_text(" ", strip=True) if readme else "",
        "_data_source": "github_public_page",
    }


def collect_repo(db, fetcher, name, resource_limit=30, tree_limit=20, depth_limit=12, force_resources=False):
    name = normalize_name(name)
    fallback_reason = None
    try:
        repo = github_json(fetcher, f"/repos/{name}")
    except RateLimited as exc:
        fallback_reason = str(exc)
        repo = github_page_data(fetcher, name)
    if repo.get("private") or repo.get("visibility", "public") != "public":
        raise FetchError("Only public repositories can be tracked")
    now = utcnow()
    category, agent_types = classify_repo(repo)
    # Retain a good previous README when content is temporarily unavailable.
    previous = db.rows("SELECT data FROM repositories WHERE id=?", (repo["id"],))
    old = json.loads(previous[0]["data"]) if previous else {}
    overrides = db.rows("SELECT * FROM repository_overrides WHERE repo_id=?", (repo["id"],))
    override = overrides[0] if overrides else None
    scan_agent_types = apply_override({"category": category, "agent_types": agent_types}, override)["agent_types"]
    warnings = []
    if fallback_reason:
        warnings.append("API 限流，使用公开页面中的精确计数；缺失字段不推测")
    readme = old.get("readme_excerpt", "")
    if repo.get("_data_source"):
        readme = repo["_readme"]
    else:
        try:
            readme = decode_content(github_json(fetcher, f"/repos/{repo['full_name']}/readme"))
        except FetchError as exc:
            warnings.append(f"README: {exc}")
    license_info = repo.get("license") or {}
    data = {
        "id": repo["id"], "full_name": repo["full_name"], "url": repo["html_url"],
        "description": repo.get("description") or "暂无项目描述", "language": repo.get("language"),
        "stars": repo["stargazers_count"], "forks": repo["forks_count"],
        "topics": repo.get("topics", []), "homepage": repo.get("homepage"),
        "license": license_info.get("spdx_id") or "未声明", "created_at": repo.get("created_at"),
        "pushed_at": repo.get("pushed_at"), "archived": repo.get("archived", False),
        "disabled": repo.get("disabled", False), "is_fork": repo.get("fork", False),
        "category": category, "agent_types": agent_types, "readme_excerpt": readme[:8000],
        "has_readme": bool(readme.strip()),
        "has_docs": bool(repo.get("homepage") or re.search(r"\[[^\]]*(?:docs|documentation|demo|文档|演示)[^\]]*\]\(https?://", readme, re.I)),
        "summary": f"一个{CATEGORIES[category]}项目。" + (f"主要使用 {repo['language']} 开发。" if repo.get("language") else "") + "具体功能见作者原始介绍。",
        "summary_method": "template", "warnings": warnings, "observed_at": now,
        "resource_scan": old.get("resource_scan", "not_scanned"),
        "data_source": repo.get("_data_source", "github_api"),
    }
    resources = []
    if scan_agent_types or force_resources:
        resources, report = scan_resources(repo, fetcher, resource_limit, tree_limit, depth_limit)
        data["resource_scan"] = report["status"]
        data["resource_scan_report"] = report
        warnings.extend(report["warnings"][:20])
    elif old.get("resource_scan_report"):
        data["resource_scan_report"] = old["resource_scan_report"]
    with db.connect() as con:
        con.execute(
            "INSERT INTO repositories VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "full_name=excluded.full_name,category=excluded.category,agent_types=excluded.agent_types,data=excluded.data,updated_at=excluded.updated_at",
            (repo["id"], repo["full_name"], category, dumps(agent_types), dumps(data), now, now),
        )
        record_aliases(con, repo["id"], repo["full_name"], [name, old.get("full_name")], now)
        # First successful observation per UTC day is immutable; reruns never fabricate growth.
        con.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?,?)", (repo["id"], now[:10], now, repo["stargazers_count"], repo["forks_count"]))
        if data["resource_scan"] == "complete":
            con.execute("DELETE FROM resources WHERE repo_id=?", (repo["id"],))
        for record in resources:
            con.execute("INSERT INTO resources VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                        (record["id"], repo["id"], record["path"], record["kind"], dumps(record), now))
    return apply_override(data, override)
