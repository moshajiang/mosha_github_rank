"""Windows scheduler shortcuts; cooperative stop, separate from the Web process."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import desktop
from github_rank.db import Database
from github_rank.scheduler import scheduler_status, request_stop
from github_rank.settings import Settings


STATE = desktop.DATA / "scheduler-process.json"
LOG = desktop.DATA / "scheduler.log"


def settings_for_child(env):
    settings = Settings.from_env(env)
    return replace(settings,
                   db_path=settings.db_path if settings.db_path.is_absolute() else desktop.ROOT/settings.db_path,
                   config_path=settings.config_path if settings.config_path.is_absolute() else desktop.ROOT/settings.config_path)


def read_state():
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        if state["workspace_id"] != desktop.WORKSPACE_ID or int(state["pid"]) <= 0:
            return None
        return state
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_state(state):
    temp = STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(state), encoding="utf-8")
    temp.replace(STATE)


def start():
    if not desktop.PYTHON.exists():
        raise desktop.LauncherError("请先按 README 安装项目运行环境。")
    with desktop.launcher_lock():
        env = desktop.child_environment()
        settings = settings_for_child(env)
        db = Database(settings.db_path)
        status = scheduler_status(db)
        if status["online"]:
            if status.get("stop_requested"):
                raise desktop.LauncherError("调度正在完成当前请求并停止，请稍后再启动。")
            return {"status": "running", "reused": True}
        existing = read_state()
        if existing and desktop.process_birth(existing["pid"]) == existing.get("birth"):
            raise desktop.LauncherError("原调度进程仍存在但心跳异常，请查看 data/scheduler.log；未重复启动。")
        instance = uuid.uuid4().hex
        with LOG.open("ab") as output:
            process = subprocess.Popen(
                [str(desktop.PYTHON), "-m", "github_rank.cli", "schedule", "--instance-id", instance],
                cwd=desktop.ROOT, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        birth = desktop.process_birth(process.pid)
        if not birth:
            raise desktop.LauncherError("调度启动失败，请查看 data/scheduler.log。")
        state = {"pid": process.pid, "birth": birth, "workspace_id": desktop.WORKSPACE_ID,
                 "instance_id": instance, "database": str(settings.db_path.resolve())}
        write_state(state)
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            status = scheduler_status(db)
            if status.get("instance_id") == instance and status["online"]:
                desktop.log("Scheduler started")
                return {"status": "running", "reused": False}
            if process.poll() is not None:
                STATE.unlink(missing_ok=True)
                raise desktop.LauncherError("调度启动失败，请查看 data/scheduler.log。")
            time.sleep(.2)
        # Keep the PID record so this owned process remains stoppable.
        request_stop(db, instance)
        raise desktop.LauncherError("调度尚未就绪，已请求停止；请查看 data/scheduler.log。")


def stop(timeout=10):
    with desktop.launcher_lock():
        state = read_state()
        if not state:
            return {"status": "unmanaged", "message": "没有由此入口启动的调度。命令行调度可用 schedule --stop 停止。"}
        if desktop.process_birth(state["pid"]) != state.get("birth"):
            STATE.unlink(missing_ok=True)
            return {"status": "stopped", "message": "原调度已结束；未处理任何同号进程。"}
        db = Database(Path(state["database"]))
        if not request_stop(db, state["instance_id"]):
            raise desktop.LauncherError("调度身份已变化，未停止其他实例。请查看运行面板或调度日志。")
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if desktop.process_birth(state["pid"]) != state["birth"]:
                STATE.unlink(missing_ok=True)
                return {"status": "stopped", "message": "定时采集已关闭，网页服务继续运行。"}
            time.sleep(.2)
        return {"status": "stopping", "message": "已请求停止，当前网络请求完成后退出。网页服务继续运行。"}


def main():
    parser = argparse.ArgumentParser(description="GitHub Rank scheduler launcher")
    parser.add_argument("action", choices=("start", "stop"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Windows shortcuts require Windows")
    try:
        result = start() if args.action == "start" else stop()
        message = result.get("message") or ("定时采集已在运行。" if result["reused"] else "定时采集已启动，可在网页的数据源与同步状态中查看。")
        if args.quiet:
            if sys.stdout:
                print(json.dumps(result, ensure_ascii=False))
        else:
            desktop.notify(message)
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, desktop.LauncherError) else f"调度操作失败（{type(exc).__name__}），请查看 data/scheduler.log。"
        desktop.notify(message, error=True, quiet=args.quiet)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
