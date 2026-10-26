"""Start/stop this project's local API with a checked PID file and detached process."""

import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request

from backend import config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop", "status"])
    command = parser.parse_args().command
    runtime = config.ROOT / "runtime"
    runtime.mkdir(exist_ok=True)
    pid_path = runtime / "server.pid"
    host, port = os.getenv("HOST", "127.0.0.1"), int(os.getenv("PORT", "8000"))

    def process():
        try:
            pid = int(pid_path.read_text())
            cmd = open(f"/proc/{pid}/cmdline", "rb").read()
            cwd = os.readlink(f"/proc/{pid}/cwd")
            if b"backend.main:app" in cmd and cwd == str(config.ROOT):
                return pid
        except (OSError, ValueError):
            pass
        return None

    pid = process()
    if command == "status":
        print(f"Running (PID {pid}) at http://{host}:{port}" if pid else "Stopped")
    elif command == "stop":
        if pid:
            os.kill(pid, signal.SIGTERM)
            for _ in range(50):
                if not process():
                    break
                time.sleep(0.1)
            print("Stop requested")
        else:
            print("Already stopped")
    elif pid:
        print(f"Already running (PID {pid}) at http://{host}:{port}")
    else:
        import socket

        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError:
                parser.error(
                    f"Port {port} is already occupied; this project did not start or stop another service."
                )
        with (runtime / "server.log").open("ab") as output:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "backend.main:app",
                    "--host",
                    host,
                    "--port",
                    str(port),
                ],
                cwd=config.ROOT,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=output,
                start_new_session=True,
            )
        pid_path.write_text(str(child.pid))
        for _ in range(100):
            if child.poll() is not None:
                parser.error("Server exited; inspect runtime/server.log")
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(f"http://{host}:{port}/api/health", timeout=1) as response:
                    if response.status == 200:
                        print(f"Retail Desk ready: http://{host}:{port} (PID {child.pid})")
                        return
            except OSError:
                time.sleep(0.2)
        parser.error("Startup timed out; inspect runtime/server.log")


if __name__ == "__main__":
    main()
