"""Arbiter - run everything with one command.

    python run.py              # set up (first run), build the dashboard if needed, serve on :8000
    python run.py --reset      # reseed the demo data before starting
    python run.py --build      # force a dashboard rebuild
    python run.py --port 9000

First run creates .venv, installs backend requirements and (if npm is available)
builds the React dashboard. Then open http://localhost:8000.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def in_venv() -> bool:
    return Path(sys.prefix).resolve() == VENV.resolve()


def ensure_venv():
    if not VENV_PY.exists():
        print("- creating virtualenv .venv")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    marker = VENV / ".arbiter-deps"
    req = BACKEND / "requirements.txt"
    if not marker.exists() or marker.stat().st_mtime < req.stat().st_mtime:
        print("- installing backend requirements")
        subprocess.check_call([str(VENV_PY), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", str(req)])
        marker.touch()


def ensure_frontend(force: bool):
    dist = FRONTEND / "dist" / "index.html"
    if dist.exists() and not force:
        return
    npm = shutil.which("npm")
    if not npm:
        print("! npm not found - skipping dashboard build (API still available at /docs)")
        return
    if not (FRONTEND / "node_modules").exists():
        print("- installing dashboard dependencies")
        subprocess.check_call([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND)
    print("- building dashboard")
    subprocess.check_call([npm, "run", "build"], cwd=FRONTEND)


def main():
    ap = argparse.ArgumentParser(description="Run Arbiter (API + dashboard)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    ap.add_argument("--reset", action="store_true", help="reseed demo data before starting")
    ap.add_argument("--build", action="store_true", help="force a dashboard rebuild")
    args = ap.parse_args()

    if not in_venv():
        ensure_venv()
        try:
            sys.exit(subprocess.call([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]]))
        except KeyboardInterrupt:
            sys.exit(0)

    ensure_frontend(args.build)
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)
    if args.reset:
        from app.data.seed import main as seed_main
        sys.argv = [sys.argv[0]]
        seed_main()

    import uvicorn
    print(f"\n  Arbiter -> http://{args.host}:{args.port}   (API docs: /docs)\n")
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
