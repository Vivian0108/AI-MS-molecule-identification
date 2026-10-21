#!/usr/bin/env python
"""Start real HTTP servers and export one complete curated investigation."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(base, path, data=None):
    raw = None if data is None else json.dumps(data).encode()
    req = Request(base + path, data=raw, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=5) as response:
        body = response.read().decode()
        return json.loads(body) if "json" in response.headers.get("Content-Type", "") else body


def wait_ready(base, path, process):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Server exited before readiness")
        try:
            return request(base, path)
        except (URLError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError("Server readiness timed out")


def main():
    api_port, ui_port = free_port(), free_port()
    env = {
        **os.environ,
        "UNKNOWNID_MODE": "demo",
        "PYTHONPATH": str(ROOT / "src"),
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    }
    processes = []
    with tempfile.TemporaryDirectory(prefix="unknownid-demo-rehearsal-") as folder:
        logs = Path(folder)
        try:
            with (logs / "api.log").open("w") as api_log, (logs / "ui.log").open("w") as ui_log:
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "unknownid.api.app:app",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(api_port),
                        ],
                        cwd=ROOT,
                        env=env,
                        stdout=api_log,
                        stderr=api_log,
                    )
                )
                processes.append(
                    subprocess.Popen(
                        ["make", "demo", f"PY={sys.executable}", f"UI_PORT={ui_port}"],
                        cwd=ROOT,
                        env=env,
                        stdout=ui_log,
                        stderr=ui_log,
                        start_new_session=True,
                    )
                )
                base = f"http://127.0.0.1:{api_port}"
                health = wait_ready(base, "/health", processes[0])
                assert health["status"] == "ok" and health["demo_mode"]
                wait_ready(f"http://127.0.0.1:{ui_port}", "/_stcore/health", processes[1])
                cid = "case-127895a5f433"
                state = request(base, "/cases/start", {"case_id": cid})
                assert state["observed_energies"] == [20]
                plan = request(base, f"/cases/{cid}/plan", {})
                energy = plan["recommended"]["energy_ev"]
                measurement = request(base, f"/cases/{cid}/measure", {"energy_ev": energy})
                assert measurement["measurement"]["accession"] is None
                request(base, f"/cases/{cid}/stop", {})
                report = request(base, f"/cases/{cid}/report")
                markdown = request(base, f"/cases/{cid}/report.md")
                assert report["investigation"]["decision"] == "identified"
                assert set(report["provenance"]["observed_accessions"]) == {"20", str(energy)}
                (logs / "evidence.json").write_text(json.dumps(report, indent=2))
                (logs / "evidence.md").write_text(markdown)
                print(
                    "PASS: make demo, Streamlit health, API /health, plan, measurement, stop, JSON and Markdown export"
                )
        except Exception:
            for path in logs.glob("*.log"):
                print(path.name, path.read_text())
            raise
        finally:
            import signal

            for index, process in enumerate(processes):
                if index == 1:
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
            for process in processes:
                process.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
