"""Verify launcher lifecycle on an isolated local port and state directory."""
import json
import os
from pathlib import Path
import socket
import desktop


def main():
    if os.name != "nt":
        raise SystemExit("Windows launcher verification requires Windows")
    directory = desktop.ROOT / ".cache/launcher-check"
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "state.json").exists():
        raise SystemExit("A previous validation state exists; inspect it before running again")
    desktop.DATA = directory
    desktop.STATE = directory / "state.json"
    desktop.SERVER_LOG = directory / "server.log"
    desktop.LAUNCH_LOG = directory / "launcher.log"
    original = None
    try:
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(10)
            occupied_port = busy.getsockname()[1]
            first = desktop.start(occupied_port, open_browser=False)
            original = desktop.read_state()
            assert not first["reused"] and original["port"] != occupied_port
            second = desktop.start(occupied_port, open_browser=False)
            assert second["reused"] and desktop.read_state()["pid"] == original["pid"]
            assert desktop.health(original["port"])["instance_id"] == original["instance_id"]
            desktop.write_state({**original, "birth": "0"})
            desktop.stop()
            assert desktop.process_birth(original["pid"]) == original["birth"], "Mismatched process identity must never be stopped"
            desktop.write_state(original)
            desktop.stop()
            assert desktop.process_birth(original["pid"]) != original["birth"]
            assert not desktop.STATE.exists()
            print(json.dumps({"port_collision": "passed", "duplicate_launch": "passed", "ready_identity": "passed", "pid_reuse_guard": "passed", "stop_owned_process": "passed"}))
    finally:
        if original and desktop.process_birth(original["pid"]) == original["birth"]:
            desktop.write_state(original)
            desktop.stop()


if __name__ == "__main__":
    main()
