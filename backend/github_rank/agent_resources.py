"""Bounded, commit-pinned resource discovery. Manifest content is data, never executed."""
from collections import deque
import hashlib
import json
from pathlib import PurePosixPath
import re
from urllib.parse import quote, urlsplit
import uuid
import yaml
from bs4 import BeautifulSoup
from .db import utcnow
from .transport import FetchError, RateLimited, ResourceBudgetExceeded
from .repositories import canonical_resource, overrides_by_repo


MAX_FILE_BYTES = 200_000


def resource_path(path):
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or any(p in ("", ".", "..") for p in path.split("/")):
        return False
    return path.endswith("/SKILL.md") or path == "SKILL.md" or path.endswith("/.claude-plugin/plugin.json") or path == ".claude-plugin/plugin.json" or path.rsplit("/", 1)[-1] == "server.json"


def resource_record(repo, path, text, sha, content_hash=None):
    if not resource_path(path) or len(text.encode("utf-8")) > MAX_FILE_BYTES:
        return None
    kind = "skill" if path.rsplit("/", 1)[-1] == "SKILL.md" else "mcp" if path.rsplit("/", 1)[-1] == "server.json" else "plugin"
    evidence, warnings = [], []
    if kind == "skill":
        match = re.match(r"\A\ufeff?---\s*\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
        if not match:
            return None
        metadata = yaml.safe_load(match.group(1))
    else:
        metadata = json.loads(text)
    if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str) or not metadata["name"].strip():
        return None
    name, description = metadata["name"], metadata.get("description", "")
    if not isinstance(description, str) or len(name) > (64 if kind == "skill" else 200) or len(description) > 1200:
        return None
    if kind == "skill":
        if not description.strip() or len(description) > 1024:
            return None
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            warnings.append("名称不符合 Agent Skills 命名约定")
        parent = PurePosixPath(path).parent.name
        if parent and parent != name:
            warnings.append("名称与所在目录名不一致")
    if kind == "mcp":
        schema = metadata.get("$schema")
        if not isinstance(schema, str):
            return None
        parts = urlsplit(schema)
        if parts.scheme != "https" or parts.netloc != "static.modelcontextprotocol.io" or not re.fullmatch(r"/schemas/[A-Za-z0-9._-]+/server\.schema\.json", parts.path) or parts.query or parts.fragment:
            return None
        if "/" not in name or not description.strip() or not isinstance(metadata.get("version"), str) or not metadata["version"].strip():
            return None
    url = f"https://github.com/{repo['full_name']}/blob/{quote(sha, safe='')}/{quote(path)}"
    compatibility = metadata.get("compatibility")
    if isinstance(compatibility, str) and compatibility.strip() and len(compatibility) <= 500:
        evidence.append({"field": "compatibility", "quote": compatibility, "url": url})
    else:
        compatibility = "未声明"
    if kind == "mcp":
        transports = set()
        for field in ("packages", "remotes"):
            entries = metadata.get(field, [])
            if not isinstance(entries, list):
                continue
            for index, entry in enumerate(entries[:20]):
                if not isinstance(entry, dict):
                    continue
                value = entry.get("transport") if field == "packages" else entry
                transport = value.get("type") if isinstance(value, dict) else None
                if transport in ("stdio", "streamable-http", "sse"):
                    transports.add(transport)
                    evidence.append({"field": f"{field}[{index}]." + ("transport.type" if field == "packages" else "type"), "quote": transport, "url": url})
        if transports and compatibility == "未声明":
            compatibility = "声明传输：" + " / ".join(sorted(transports))
    license_value = metadata.get("license")
    version = metadata.get("version") or (metadata.get("metadata", {}).get("version") if isinstance(metadata.get("metadata"), dict) else None)
    return {
        "id": uuid.uuid5(uuid.NAMESPACE_URL, f"github:{repo['id']}:{path}").hex,
        "repo_id": repo["id"], "repo_name": repo["full_name"], "path": path, "kind": kind,
        "name": name, "description": description or "作者未提供用途说明",
        "compatibility": compatibility, "compatibility_status": "作者声明，未测试" if evidence else "未声明兼容要求",
        "compatibility_evidence": evidence, "ecosystem": {"skill": "agent-skills", "plugin": "claude-code", "mcp": "mcp"}[kind],
        "license": license_value[:200] if isinstance(license_value, str) else "未声明",
        "declared_version": version[:100] if isinstance(version, str) else None,
        "url": url, "commit": sha, "content_hash": content_hash or hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "hash_method": "sha256-file-bytes", "format_warnings": warnings,
        "metric_note": "关联仓库指标；无独立安装量", "summary_method": "original",
    }


def scan_resources(repo, fetcher, resource_limit=30, tree_limit=20, depth_limit=12):
    resource_limit, tree_limit, depth_limit = min(max(int(resource_limit), 1), 200), min(max(int(tree_limit), 2), 100), min(max(int(depth_limit), 1), 30)
    report = {"status": "partial", "observed_at": utcnow(), "commit": None, "tree_complete": False,
              "tree_requests": 0, "candidate_files": 0, "read_files": 0, "invalid_files": 0,
              "resource_ids": [], "reasons": [], "warnings": [],
              "limits": {"files": resource_limit, "trees": tree_limit, "depth": depth_limit}}
    records, paths = [], {}

    def get_json(path):
        return json.loads(fetcher.get_resource("https://api.github.com" + path))

    def accept(entry, prefix=""):
        path = prefix + entry.get("path", "")
        if entry.get("type") == "blob" and entry.get("mode") != "120000" and resource_path(path):
            paths[path] = entry.get("size")

    if repo.get("_data_source"):
        report["method"] = "public_page_links"
        sha = repo.get("_sha")
        if not sha:
            report["status"] = "failed"
            report["reasons"].append("missing_commit")
            return records, report
        # Visible page paths are a partial candidate list, never a full directory enumeration.
        for entry in repo.get("_tree", []):
            path = entry.get("path", "")
            if resource_path(path):
                paths[path] = None
        roots = {"skills", "plugins", ".claude-plugin", "src", "servers", ".agents", ".github"}
        queue = deque((entry["path"], 1) for entry in sorted(repo.get("_tree", []), key=lambda e: (e.get("name") != "skills", e.get("name", "")))
                      if entry.get("contentType") == "directory" and entry.get("name") in roots)
        while queue:
            path, depth = queue.popleft()
            if report["tree_requests"] >= tree_limit:
                report["reasons"].append("tree_request_limit")
                break
            report["tree_requests"] += 1
            try:
                body = fetcher.get_resource(f"https://github.com/{repo['full_name']}/tree/{quote(sha, safe='')}/{quote(path)}")
                soup = BeautifulSoup(body, "html.parser")
                route = None
                for script in soup.select('script[data-target="react-app.embeddedData"]'):
                    route = json.loads(script.get_text()).get("payload", {}).get("codeViewTreeRoute")
                    if route:
                        break
                if not route or route.get("refInfo", {}).get("currentOid") != sha:
                    raise FetchError("Public directory commit could not be verified")
                for entry in route.get("tree", {}).get("items", []):
                    child = entry.get("path", "")
                    if not child.startswith(path+"/"):
                        continue
                    if entry.get("contentType") == "file" and resource_path(child):
                        paths[child] = None
                    elif entry.get("contentType") == "directory":
                        if depth >= depth_limit or len(queue) >= 5000:
                            report["reasons"].append("tree_depth_or_queue_limit")
                        else:
                            queue.append((child, depth+1))
            except ResourceBudgetExceeded:
                report["reasons"].append("batch_resource_budget")
                break
            except (FetchError, ValueError, TypeError) as exc:
                report["reasons"].append("page_directory_unavailable")
                report["warnings"].append(f"{path}: {type(exc).__name__}")
        for anchor in repo["_soup"].select('.markdown-body a[href]'):
            parts = urlsplit(anchor["href"])
            if parts.netloc and parts.netloc.lower() != "github.com":
                continue
            prefix = f"/{repo['full_name']}/blob/{repo['default_branch']}/"
            directory = f"/{repo['full_name']}/tree/{repo['default_branch']}/"
            if parts.path.startswith(prefix) and resource_path(parts.path[len(prefix):]):
                paths[parts.path[len(prefix):]] = None
            elif parts.path.startswith(directory+"skills/"):
                path = parts.path[len(directory):].rstrip("/")+"/SKILL.md"
                if resource_path(path):
                    paths[path] = None
        report["reasons"].append("page_is_partial")
    else:
        report["method"] = "github_tree"
        sha = None
        def get_tree(oid, recursive=False):
            tree = get_json(f"/repos/{repo['full_name']}/git/trees/{quote(oid, safe='')}" + ("?recursive=1" if recursive else ""))
            if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
                raise FetchError("Invalid Git tree representation")
            return tree
        try:
            branch = get_json(f"/repos/{repo['full_name']}/branches/{quote(repo.get('default_branch', 'main'), safe='')}")
            sha = branch["commit"]["sha"]
            report["commit"] = sha
            tree_sha = branch["commit"].get("commit", {}).get("tree", {}).get("sha", sha)
            report["tree_requests"] += 1
            try:
                tree = get_tree(tree_sha, True)
                for entry in tree.get("tree", []):
                    accept(entry)
                report["tree_complete"] = not tree.get("truncated", False)
            except (RateLimited, ResourceBudgetExceeded):
                raise
            except FetchError:
                report["warnings"].append("递归目录不可用，尝试有界逐层扫描")
            if not report["tree_complete"]:
                queue = deque([("", tree_sha, 0)])
                cache, limited = {}, False
                while queue:
                    prefix, oid, depth = queue.popleft()
                    if oid not in cache:
                        if report["tree_requests"] >= tree_limit:
                            limited = True
                            report["reasons"].append("tree_request_limit")
                            break
                        report["tree_requests"] += 1
                        cache[oid] = get_tree(oid)
                    tree = cache[oid]
                    if tree.get("truncated"):
                        limited = True
                        report["reasons"].append("nonrecursive_tree_truncated")
                    for entry in tree.get("tree", []):
                        accept(entry, prefix)
                        if entry.get("type") == "tree":
                            child = prefix+entry["path"]+"/"
                            if depth >= depth_limit or len(queue) >= 5000:
                                limited = True
                                report["reasons"].append("tree_depth_or_queue_limit")
                            else:
                                queue.append((child, entry["sha"], depth+1))
                report["tree_complete"] = not limited
        except (FetchError, ValueError, KeyError) as exc:
            report["tree_complete"] = False
            report["reasons"].append("tree_unavailable")
            if isinstance(exc, ResourceBudgetExceeded):
                report["reasons"].append("batch_resource_budget")
            report["warnings"].append(f"目录扫描：{type(exc).__name__}")
            if not sha or not paths:
                report["status"] = "failed"
                return records, report
    report["commit"] = sha
    report["candidate_files"] = len(paths)
    if len(paths) > resource_limit:
        report["reasons"].append("resource_file_limit")
    for path in sorted(paths)[:resource_limit]:
        if isinstance(paths[path], int) and paths[path] > MAX_FILE_BYTES:
            report["reasons"].append("file_size_limit")
            continue
        try:
            raw = fetcher.get_resource(f"https://raw.githubusercontent.com/{repo['full_name']}/{quote(sha, safe='')}/{quote(path)}")
            if len(raw) > MAX_FILE_BYTES:
                report["reasons"].append("file_size_limit")
                continue
            report["read_files"] += 1
            record = resource_record(repo, path, raw.decode("utf-8-sig"), sha, hashlib.sha256(raw).hexdigest())
            if record:
                records.append(record)
            else:
                report["invalid_files"] += 1
        except (ValueError, yaml.YAMLError, RecursionError):
            report["invalid_files"] += 1
        except ResourceBudgetExceeded:
            report["reasons"].append("batch_resource_budget")
            break
        except FetchError as exc:
            report["reasons"].append("file_fetch_failed")
            report["warnings"].append(f"{path}: {type(exc).__name__}")
    report["resource_ids"] = [r["id"] for r in records]
    report["reasons"] = sorted(set(report["reasons"]))
    report["status"] = "complete" if report["tree_complete"] and not report["reasons"] else "partial"
    return records, report


def enrich_resource(item, repo):
    item = canonical_resource(item, repo)
    report = repo.get("resource_scan_report") or {}
    item["scan_status"] = repo.get("resource_scan", "not_scanned")
    item["scan_report"] = report
    item["verification_status"] = "current" if item["id"] in report.get("resource_ids", []) else "previous" if report else "unknown"
    item["compatibility_evidence"] = [{**e, "url": item["url"]} for e in item.get("compatibility_evidence", [])]
    # Legacy records did not keep field evidence; do not invent a compatibility claim.
    if not item["compatibility_evidence"]:
        item["compatibility_status"] = "未声明兼容要求" if item.get("content_hash") else "未保留兼容声明证据"
    item["repository_stars"] = repo["stars"]
    return item


def resource_items(db, include_excluded=False):
    overrides = overrides_by_repo(db)
    result = []
    for row in db.rows("SELECT r.data,p.data AS repo_data FROM resources r JOIN repositories p ON p.id=r.repo_id ORDER BY p.full_name,r.path,r.id"):
        repo = json.loads(row["repo_data"])
        excluded = bool(overrides.get(repo["id"], {}).get("excluded"))
        if excluded and not include_excluded:
            continue
        item = enrich_resource(json.loads(row["data"]), repo)
        item["ranking_excluded"] = excluded
        result.append(item)
    return result


def duplicate_key(item):
    digest = item.get("content_hash")
    return (item["kind"], digest) if isinstance(digest, str) and re.fullmatch("[a-f0-9]{64}", digest) else (item["kind"], item["id"])


def with_duplicates(item, peers):
    return {**item, "duplicate_count": len(peers), "same_content_sources": [
        {k: peer[k] for k in ("id", "repo_name", "path", "url", "commit", "verification_status")} for peer in peers]}


def resource_catalog(db, kind="", q="", group_duplicates=True):
    all_items = [r for r in resource_items(db) if not kind or r["kind"] == kind]
    groups = {}
    for item in all_items:
        groups.setdefault(duplicate_key(item), []).append(item)
    result, matched = [], 0
    for peers in groups.values():
        found = [r for r in peers if q.lower() in (r["name"]+" "+r["description"]+" "+r["repo_name"]).lower()]
        matched += len(found)
        if found:
            found.sort(key=lambda r: (r["verification_status"] != "current", r["repo_name"].lower(), r["path"], r["id"]))
            result.extend(with_duplicates(r, peers) for r in (found[:1] if group_duplicates else found))
    return result, matched
