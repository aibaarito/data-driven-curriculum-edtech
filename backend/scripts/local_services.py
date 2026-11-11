"""Start/stop only this checkout's services; never shell-evaluate the private .env."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".local-services.json"


def runtime_env(root: Path = ROOT) -> dict[str, str]:
    # Same precedence as backend Settings: process environment overrides backend/.env.
    return {**{k: v for k, v in dotenv_values(root / "backend/.env").items() if v is not None}, **os.environ}


def frontend_env(env: dict[str, str], backend_port: int) -> dict[str, str]:
    result = {k: v for k, v in env.items()
              if not k.startswith(("LLM_", "DATABASE_", "TEST_DATABASE_", "ADMIN_", "POSTGRES_"))}
    result["API_URL"] = f"http://127.0.0.1:{backend_port}"
    return result


def identity(pid: int) -> str:
    # Next.js changes its process title after boot. PID + start time + owner remain stable.
    p = subprocess.run(["ps", "-p", str(pid), "-o", "lstart=", "-o", "uid="],
                       capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def stop_owned(records: list[dict]) -> None:
    for r in reversed(records):
        if r["identity"] and identity(r["pid"]) == r["identity"]:
            try:
                os.kill(r["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass


def wait_ready(url: str, process: subprocess.Popen, token: str = "") -> None:
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError("Service exited; see this checkout's service log.")
        try:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=2) as r:
                if r.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.25)
    raise RuntimeError("Service did not become ready; see this checkout's service log.")


def start(backend_port: int, frontend_port: int) -> None:
    if STATE.exists():
        raise RuntimeError("Service state exists. Run ./dev.sh stop for this checkout first.")
    for port in (backend_port, frontend_port):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"Port {port} is already in use; no services were changed.") from exc
    env = runtime_env()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend", env=env, check=True)
    subprocess.run([sys.executable, "scripts/integrity_check.py"], cwd=ROOT / "backend", env=env, check=True)
    front = frontend_env(env, backend_port)
    subprocess.run(["npm", "run", "build"], cwd=ROOT / "frontend", env=front, check=True)
    records: list[dict] = []
    try:
        def launch(cmd: list[str], cwd: Path, child_env: dict, logfile: str) -> subprocess.Popen:
            with (ROOT / logfile).open("ab") as out:
                p = subprocess.Popen(cmd, cwd=cwd, env=child_env, stdout=out, stderr=out, start_new_session=True)
            # Store only identity metadata; never persist command environments or credentials.
            records.append({"pid": p.pid, "identity": identity(p.pid)})
            STATE.write_text(json.dumps(records))
            STATE.chmod(0o600)
            return p
        backend = launch([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                          "--port", str(backend_port)], ROOT / "backend", env, "backend.log")
        wait_ready(f"http://127.0.0.1:{backend_port}/api/meta", backend, env.get("API_TOKEN", ""))
        frontend = launch(["node", "node_modules/next/dist/bin/next", "start", "-p", str(frontend_port),
                           "-H", "127.0.0.1"], ROOT / "frontend", front, "frontend.log")
        # Basic auth also protects /api/health on the frontend.
        import base64
        auth = ""
        if front.get("DEMO_BASIC_AUTH_USER") and front.get("DEMO_BASIC_AUTH_PASSWORD"):
            auth = base64.b64encode(f"{front['DEMO_BASIC_AUTH_USER']}:{front['DEMO_BASIC_AUTH_PASSWORD']}".encode()).decode()
        if auth:
            # Verify directly with Basic credentials without printing them.
            for _ in range(120):
                if frontend.poll() is not None:
                    raise RuntimeError("Frontend exited; see frontend.log.")
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{frontend_port}/api/meta",
                                                 headers={"Authorization": "Basic " + auth})
                    with urllib.request.urlopen(req, timeout=2) as r:
                        if r.status == 200:
                            break
                except OSError:
                    time.sleep(0.25)
            else:
                raise RuntimeError("Frontend authentication/proxy readiness failed.")
        else:
            wait_ready(f"http://127.0.0.1:{frontend_port}/api/meta", frontend)
    except BaseException:
        stop_owned(records)
        STATE.unlink(missing_ok=True)
        raise
    print(f"Ready: http://127.0.0.1:{frontend_port}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop"])
    args = parser.parse_args()
    if args.action == "stop":
        if STATE.exists():
            records = json.loads(STATE.read_text())
            stop_owned(records)
            deadline = time.monotonic() + 10
            while any(r["identity"] and identity(r["pid"]) == r["identity"] for r in records):
                if time.monotonic() > deadline:
                    raise RuntimeError("Services are still stopping; state preserved. Retry stop shortly.")
                time.sleep(0.1)
            STATE.unlink()
        print("Stopped services recorded by this checkout. PostgreSQL was left running.")
    else:
        start(int(os.environ.get("BACKEND_PORT", "8010")), int(os.environ.get("FRONTEND_PORT", "3010")))


if __name__ == "__main__":
    main()
