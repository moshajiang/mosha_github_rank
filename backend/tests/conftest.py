from pathlib import Path
import pytest
from github_rank.db import Database, dumps
from github_rank.settings import Settings


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.sqlite3")


@pytest.fixture
def settings(tmp_path):
    config = tmp_path / "sources.yaml"
    config.write_text("repositories: []\nqueries: []\nnews_sources: []\n", encoding="utf-8")
    return Settings(tmp_path / "api.sqlite3", config)


def add_repo(db, repo_id=1, **overrides):
    data = {
        "id": repo_id, "full_name": f"owner/repo-{repo_id}", "url": f"https://github.com/owner/repo-{repo_id}",
        "description": "An agent framework", "category": "ai", "agent_types": ["framework"],
        "stars": 1000, "forks": 20, "topics": [], "language": "Python", "license": "MIT",
        "pushed_at": "2026-10-29T08:00:00+00:00", "has_readme": True, "has_docs": True,
        "summary": "模板介绍", "archived": False, "is_fork": False,
    }
    data.update(overrides)
    db.execute("INSERT INTO repositories VALUES(?,?,?,?,?,?,?)", (repo_id, data["full_name"], data["category"], dumps(data["agent_types"]), dumps(data), "2026-10-01T08:00:00+00:00", "2026-10-30T08:00:00+00:00"))
    return data


def snapshot(db, repo_id, when, stars, forks=10):
    db.execute("INSERT INTO snapshots VALUES(?,?,?,?,?)", (repo_id, when[:10], when, stars, forks))
