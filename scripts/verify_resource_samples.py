"""Collect a bounded set of real repositories; no fixtures or third-party code execution."""
from pathlib import Path
import json
from github_rank.db import Database, utcnow
from github_rank.jobs import add_repository
from github_rank.settings import Settings
from github_rank.transport import Fetcher


SAMPLES = [
    "anthropics/skills", "modelcontextprotocol/servers", "github/awesome-copilot",
    "dreammis/social-auto-upload", "krillinai/OpenCreator",
    "Vincentwei1021/video-shotcraft", "AgriciDaniel/claude-obsidian",
    "tigerless-labs/autoharness", "jnMetaCode/superpowers-zh", "vercel-labs/skills",
]


def main():
    settings = Settings.from_env()
    db = Database(settings.db_path)
    fetcher = Fetcher(db, settings.github_token)
    output = {"observed_at": utcnow(), "samples": [], "note": "Real reads; complete/partial/failed are recorded separately."}
    try:
        for name in SAMPLES:
            try:
                result = add_repository(settings, db, name, fetcher=fetcher, force_resources=True)
                item = result["repositories"][0]
                scan = item.get("resource_scan_report") or {}
                row = {"name": item["name"], "status": item["resource_scan"], "candidate_files": scan.get("candidate_files"),
                       "read_files": scan.get("read_files"), "resources": len(scan.get("resource_ids", [])),
                       "tree_complete": scan.get("tree_complete"), "method": scan.get("method"),
                       "reasons": scan.get("reasons", [])}
            except Exception as exc:
                row = {"name": name, "status": "failed", "error": type(exc).__name__}
            output["samples"].append(row)
            print(json.dumps(row, ensure_ascii=True), flush=True)
    finally:
        fetcher.close()
    path = settings.db_path.parent/"resource-sample-report.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Saved " + str(path), flush=True)


if __name__ == "__main__":
    main()
