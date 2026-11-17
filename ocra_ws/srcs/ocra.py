#!/usr/bin/env python3
"""Install configuration and manage only Orca processes started by this component."""
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlsplit
import base64

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIG = DATA / "ocra.conf"
STATE = DATA / "server.json"
LOG = DATA / "server.log"
CLI = DATA / "orca-server/bin/orca-ide"


def cli_env():
    # A terminal opened from a paired Orca can carry a remote target. Always
    # manage this machine's runtime, including when querying readiness/pairing.
    env = os.environ.copy()
    for key in ("ORCA_ENVIRONMENT", "ORCA_PAIRING_CODE"):
        env.pop(key, None)
    return env


def write_json(path, value):
    """Atomically replace a private file; never leave a partial pairing code."""
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def load_config():
    config = json.loads(CONFIG.read_text())
    if not isinstance(config, dict):
        raise ValueError("配置必须为 JSON 对象。")
    ip = ipaddress.IPv4Address(config.get("ip", ""))
    if ip.is_unspecified or ip.is_multicast or ip.is_loopback:
        raise ValueError("ip 必须是客户端可访问的主机 IPv4 地址。")
    port = config.get("port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port 必须是 1–65535 的整数。")
    return config


def initialize():
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Exclusive creation preserves existing settings, including concurrent installs.
    try:
        with CONFIG.open("x", encoding="utf-8") as stream:
            stream.write((ROOT / "ocra.conf.example").read_text())
    except FileExistsError:
        pass
    return load_config()


def process_identity(pid):
    """Linux start time prevents sending a signal to a recycled PID."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return fields[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def managed_state():
    if not STATE.exists():
        return None
    state = json.loads(STATE.read_text())
    pid = state.get("pid")
    if type(pid) is not int or pid <= 1 or not isinstance(state.get("startTime"), str):
        raise ValueError("进程记录无效，拒绝操作。")
    return state if process_identity(pid) == state["startTime"] else None


def port_busy(port):
    with socket.socket() as sock:
        # Match Node's listener behavior: closed connections in TIME_WAIT do
        # not prevent restarting, while a live listener still blocks bind.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return True
    return False


def runtime_ready(state):
    result = subprocess.run([str(state["cli"]), "status", "--json"],
                            capture_output=True, text=True, timeout=5, env=cli_env())
    if result.returncode:
        return False
    response = json.loads(result.stdout)
    data = response.get("result", {})
    if not response.get("ok") or data.get("runtime", {}).get("state") != "ready":
        return False
    # The ready runtime must belong to our launcher, not another profile/server.
    pid = data.get("app", {}).get("pid")
    for _ in range(16):
        if pid == state["pid"]:
            return True
        if type(pid) is not int or pid <= 1:
            break
        try:
            stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            pid = int(stat[1])
        except (FileNotFoundError, ProcessLookupError):
            break
    return False


def save_pairing(config, state):
    result = subprocess.run([state["cli"], "pair", "--address", config["ip"], "--json"],
                            capture_output=True, text=True, timeout=15, env=cli_env())
    if result.returncode:
        raise RuntimeError("生成配对链接失败；服务仍在运行，可再次执行 ocra_web_run.sh start 重试。")
    response = json.loads(result.stdout)
    result = response.get("result", {})
    expected = f"ws://{config['ip']}:{config['port']}"
    url = result.get("pairingUrl", "")
    if not response.get("ok") or not result.get("available") or result.get("endpoint") != expected:
        raise RuntimeError("配对服务地址与配置不一致，未写入配对链接。")
    try:
        parsed = urlsplit(url)
        code = parse_qs(parsed.query)["code"][0]
        payload = json.loads(base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)))
        valid = parsed.scheme == "orca" and parsed.netloc == "pair" and payload["endpoint"] == expected
    except (ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise RuntimeError("配对链接未包含配置中的主机地址，拒绝写入。")
    config["pairingUrl"] = url
    write_json(CONFIG, config)
    print(f"配对链接已写入 {CONFIG} 的 pairingUrl 字段。")


def start(config):
    state = managed_state()
    if state:
        if (state["ip"], state["port"]) != (config["ip"], config["port"]):
            raise RuntimeError("运行参数与配置不同；请在允许中断会话时先 stop，再 start。")
        if not runtime_ready(state):
            raise RuntimeError("托管进程仍存在但尚未就绪；请检查 data/server.log。")
        save_pairing(config, state)
        print(f"Orca 已运行，PID {state['pid']}。")
        return
    if port_busy(config["port"]):
        raise RuntimeError(f"端口 {config['port']} 已被占用，未启动或接管现有进程。")
    if not CLI.is_file():
        raise RuntimeError("尚未安装，请先执行 bash ocra_ws/install.sh。")
    executable = CLI.resolve()
    # No pairing credentials in logs: generate the offer through `pair --json` later.
    with LOG.open("ab", buffering=0) as log:
        proc = subprocess.Popen([str(executable), "serve", "--bind", "0.0.0.0",
                                 "--port", str(config["port"]), "--pairing-address", config["ip"],
                                 "--refuse-public", "--no-pairing"], cwd=ROOT,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                start_new_session=True, close_fds=True, env=cli_env())
    state = {"pid": proc.pid, "startTime": process_identity(proc.pid),
             "cli": str(executable), "ip": config["ip"], "port": config["port"]}
    write_json(STATE, state)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            STATE.unlink(missing_ok=True)
            raise RuntimeError("Orca 启动失败，请检查 data/server.log。")
        try:
            if runtime_ready(state):
                save_pairing(config, state)
                print(f"Orca 已就绪：{config['ip']}:{config['port']}，PID {proc.pid}。")
                return
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    raise RuntimeError("等待就绪超时；保留进程记录，请用 ocra_web_run.sh status 检查或 ocra_web_run.sh stop 停止。")


def stop():
    state = managed_state()
    if not state:
        STATE.unlink(missing_ok=True)
        print("没有由本目录脚本启动的运行中进程；未操作其他 Orca 实例。")
        return
    print(f"正在停止 Orca（PID {state['pid']}），该服务中的连接会中断。", flush=True)
    try:
        os.kill(state["pid"], signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process_identity(state["pid"]) != state["startTime"]:
            if port_busy(state["port"]):
                raise RuntimeError("启动进程已退出，但端口仍被占用；请检查残留进程。")
            STATE.unlink(missing_ok=True)
            print("Orca 已停止。")
            return
        time.sleep(0.2)
    raise RuntimeError("停止超时；保留进程记录，未强制杀进程。")


def status(config):
    state = managed_state()
    if state:
        ready = runtime_ready(state)
        print(f"PID {state['pid']}，{state['ip']}:{state['port']}，" + ("已就绪" if ready else "未就绪"))
        return 0 if ready else 1
    if port_busy(config["port"]):
        print(f"端口 {config['port']} 被其他进程占用，本目录没有托管该进程。")
    else:
        print("Orca 未运行。")
    return 1


def main():
    os.umask(0o077)
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    if action not in {"init", "start", "stop", "status"}:
        raise ValueError("用法：ocra.py init|start|stop|status")
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (DATA / "manage.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Stopping uses the saved process record even if the config was edited.
        if action == "stop":
            stop()
            return 0
        config = initialize()
        if action == "start":
            start(config)
        elif action == "status":
            return status(config)
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
