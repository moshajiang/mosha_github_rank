"""Verify real Windows background processes using empty, isolated collection sources."""
import json
import os
from pathlib import Path
import socket
import desktop
import desktop_scheduler
from github_rank.db import Database
from github_rank.scheduler import scheduler_status


def main():
    if os.name != "nt":
        raise SystemExit("Windows lifecycle verification requires Windows")
    directory = desktop.ROOT/".cache/scheduler-check"
    directory.mkdir(parents=True, exist_ok=True)
    if (directory/"scheduler-state.json").exists() or (directory/"web-state.json").exists():
        raise SystemExit("Previous validation state exists; inspect it before running again")
    config = directory/"sources.yaml"
    config.write_text("repositories: []\nqueries: []\nnews_sources: []\n", encoding="utf-8")
    env = {**desktop.child_environment(), "GITHUB_RANK_DB":str(directory/"test.sqlite3"),
           "GITHUB_RANK_CONFIG":str(config), "GITHUB_TOKEN":"", "GITHUB_RANK_SUMMARY_MODEL":"", "GITHUB_RANK_AUTO_SUMMARY":"false"}
    desktop.child_environment = lambda: env.copy()
    desktop.DATA = directory
    desktop.STATE = directory/"web-state.json"
    desktop.LAUNCH_LOG = directory/"launcher.log"
    desktop.SERVER_LOG = directory/"web.log"
    desktop_scheduler.STATE = directory/"scheduler-state.json"
    desktop_scheduler.LOG = directory/"scheduler.log"
    original = None
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        desktop.start(port, open_browser=False)
        web = desktop.read_state()
        assert not desktop_scheduler.start()["reused"]
        original = desktop_scheduler.read_state()
        db = Database(Path(env["GITHUB_RANK_DB"]))
        assert scheduler_status(db)["online"]
        assert desktop_scheduler.start()["reused"]
        assert desktop_scheduler.read_state()["pid"] == original["pid"]
        desktop_scheduler.write_state({**original, "birth":"0"})
        desktop_scheduler.stop()
        assert desktop.process_birth(original["pid"]) == original["birth"]
        assert not scheduler_status(db)["stop_requested"]
        desktop_scheduler.write_state(original)
        assert desktop_scheduler.stop()["status"] == "stopped"
        assert not desktop_scheduler.STATE.exists()
        assert scheduler_status(db)["status"] == "stopped"
        assert desktop.health(web["port"])["instance_id"] == web["instance_id"]
        assert not desktop_scheduler.start()["reused"]
        original = desktop_scheduler.read_state()
        assert desktop_scheduler.stop()["status"] == "stopped"
        print(json.dumps({"background_start":"passed","duplicate_start":"passed","pid_reuse_guard":"passed", "cooperative_stop":"passed","web_independence":"passed","restart":"passed","sources":"isolated empty config; no public collection"}))
    finally:
        if original and desktop.process_birth(original["pid"]) == original["birth"]:
            desktop_scheduler.write_state(original)
            desktop_scheduler.stop(timeout=30)
        if desktop.read_state():
            desktop.stop()


if __name__ == "__main__":
    main()
