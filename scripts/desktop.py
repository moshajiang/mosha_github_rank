"""Windows double-click launcher. Owns only processes it created.

Use --no-browser --quiet for lifecycle verification without opening native UI.
"""
import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from github_rank.identity import workspace_id

DATA = ROOT / "data"
STATE = DATA / "desktop-process.json"
SERVER_LOG = DATA / "desktop-server.log"
LAUNCH_LOG = DATA / "desktop-launcher.log"
PYTHON = ROOT / ".venv/Scripts/python.exe"
WORKSPACE_ID = workspace_id(ROOT)


class LauncherError(RuntimeError):
    pass


def log(message):
    DATA.mkdir(parents=True, exist_ok=True)
    with LAUNCH_LOG.open("a", encoding="utf-8") as stream:
        stream.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")


def notify(message, error=False, quiet=False):
    try:
        log(message)
    except OSError:
        pass
    if quiet:
        if sys.stdout:
            print(message)
    else:
        ctypes.windll.user32.MessageBoxW(None, message, "GitHub Rank", 0x10 if error else 0x40)


def kernel():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    api.GetProcessTimes.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    api.TerminateProcess.restype = wintypes.BOOL
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    api.GetExitCodeProcess.restype = wintypes.BOOL
    return api


def birth_for_handle(api, handle):
    values = [wintypes.FILETIME() for _ in range(4)]
    if not api.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)):
        return None
    return str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)


def process_birth(pid):
    api = kernel()
    handle = api.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        exit_code = wintypes.DWORD()
        if not api.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            return None
        return birth_for_handle(api, handle)
    finally:
        api.CloseHandle(handle)


def read_state():
    try:
        value = json.loads(STATE.read_text(encoding="utf-8"))
        if value["workspace_id"] != WORKSPACE_ID or not 1 <= int(value["port"]) <= 65535 or int(value["pid"]) <= 0:
            return None
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_state(value):
    temp = STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temp.replace(STATE)


def health(port):
    try:
        # A local application check must not go through a configured external proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=.7) as response:
            data = json.loads(response.read(4096))
        return data if data.get("app_id") == "github-rank" and data.get("workspace_id") == WORKSPACE_ID else None
    except (OSError, ValueError, TypeError):
        return None


@contextmanager
def launcher_lock():
    import msvcrt
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / "desktop.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise LauncherError("另一个启动或关闭操作正在进行，请稍后再试。") from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def child_environment():
    env = os.environ.copy()
    dotenv = ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key == "GITHUB_TOKEN" or key.startswith("GITHUB_RANK_"):
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                env[key] = value
    env["PYTHONUTF8"] = "1"
    return env


def wait_ready(state, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = health(state["port"])
        if data and data.get("instance_id") == state["instance_id"]:
            return True
        if process_birth(state["pid"]) != state["birth"]:
            return False
        time.sleep(.25)
    return False


def start(port=8000, open_browser=True):
    if not PYTHON.exists():
        raise LauncherError("尚未安装项目运行环境，请先按 README 完成首次安装。")
    if not (ROOT / "frontend/dist/index.html").exists():
        raise LauncherError("尚未构建前端页面，请先在 frontend 目录执行 npm run build。")
    with launcher_lock():
        existing = read_state()
        if existing and process_birth(existing["pid"]) == existing.get("birth"):
            if not wait_ready(existing, timeout=10):
                raise LauncherError("后台进程仍存在但尚未就绪。请双击关闭入口后再启动，或查看 data/desktop-server.log。")
            selected = existing["port"]
            reused = True
        else:
            selected = None
            reused = False
            for candidate in range(port, min(port + 11, 65536)):
                if health(candidate):
                    selected, reused = candidate, True
                    break
                with socket.socket() as probe:
                    probe.settimeout(.25)
                    if probe.connect_ex(("127.0.0.1", candidate)) != 0:
                        selected = candidate
                        break
            if selected is None:
                raise LauncherError("附近端口均已占用，请关闭无关服务后再试。")
            if not reused:
                env = child_environment()
                instance = uuid.uuid4().hex
                env["GITHUB_RANK_DESKTOP_INSTANCE"] = instance
                with SERVER_LOG.open("ab") as output:
                    process = subprocess.Popen(
                        [str(PYTHON), "-m", "uvicorn", "github_rank.api:create_app", "--factory", "--app-dir", str(ROOT / "backend"), "--host", "127.0.0.1", "--port", str(selected)],
                        cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                birth = process_birth(process.pid)
                if not birth:
                    process.terminate()
                    raise LauncherError("无法记录后台进程，请查看 data/desktop-server.log。")
                state = {"pid": process.pid, "birth": birth, "port": selected, "workspace_id": WORKSPACE_ID, "instance_id": instance}
                write_state(state)
                if not wait_ready(state):
                    if process.poll() is None:
                        process.terminate()
                    STATE.unlink(missing_ok=True)
                    raise LauncherError("启动未能完成，请查看 data/desktop-server.log。")
        url = f"http://127.0.0.1:{selected}/"
        if open_browser:
            webbrowser.open(url)
        log(("Reused " if reused else "Started ") + url)
        return {"url": url, "reused": reused}


def stop():
    with launcher_lock():
        state = read_state()
        if not state:
            return "没有由快捷入口启动的后台服务。"
        api = kernel()
        handle = api.OpenProcess(0x1000 | 0x100000 | 0x0001, False, int(state["pid"]))
        if not handle:
            if ctypes.get_last_error() == 5:
                raise LauncherError("没有关闭后台进程所需的权限，请使用启动时的账户关闭。")
            STATE.unlink(missing_ok=True)
            return "后台服务已经关闭。"
        try:
            if birth_for_handle(api, handle) != state.get("birth"):
                STATE.unlink(missing_ok=True)
                return "原后台服务已结束，当前同号进程不属于该次启动，已保留。"
            exit_code = wintypes.DWORD()
            if api.GetExitCodeProcess(handle, ctypes.byref(exit_code)) and exit_code.value != 259:
                STATE.unlink(missing_ok=True)
                return "后台服务已经关闭。"
            if not api.TerminateProcess(handle, 0):
                raise LauncherError("无法关闭后台服务，请检查系统权限。")
            if api.WaitForSingleObject(handle, 5000) != 0:
                raise LauncherError("后台进程尚未退出，请稍后重试。")
        finally:
            api.CloseHandle(handle)
        STATE.unlink(missing_ok=True)
        return "GitHub Rank 后台服务已关闭。"


def main():
    parser = argparse.ArgumentParser(description="GitHub Rank desktop launcher")
    parser.add_argument("action", choices=["launch", "stop"], nargs="?", default="launch")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("The double-click launcher is for Windows")
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    try:
        if args.action == "launch":
            result = start(args.port, not args.no_browser)
            if args.quiet and sys.stdout:
                print(json.dumps(result))
        else:
            notify(stop(), quiet=args.quiet)
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, LauncherError) else f"启动操作失败（{type(exc).__name__}），请查看 data/desktop-launcher.log。"
        notify(message, error=True, quiet=args.quiet)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
