#!/usr/bin/env python3
"""Start the HV monitoring server.

    python run.py                     # listen on the LAN, port 8003
    python run.py --port 8004
    python run.py --host 127.0.0.1    # this machine only
    python run.py --reload            # development
"""

from __future__ import annotations

import argparse
import errno
import sys

import uvicorn

from app.caen import library_release
from app.config import SNAPSHOT_ROOT, STATIC_DIR
from app.net import browser_url, lan_addresses
from app.store import load_crates


def main() -> int:
    parser = argparse.ArgumentParser(description="CAEN HV monitoring server")
    parser.add_argument("--host", default="0.0.0.0", help="0.0.0.0 lets other PCs on the LAN connect")
    parser.add_argument("--port", type=int, default=8003)
    parser.add_argument("--reload", action="store_true", help="restart on code changes")
    args = parser.parse_args()

    primary = browser_url(args.host, args.port)
    print(f"UI:        {primary}", flush=True)
    print(f"API docs:  {primary}/docs", flush=True)

    release = library_release()
    if release:
        print(f"CAEN lib:  {release}", flush=True)
    else:
        print(
            "CAEN lib:  NOT FOUND - install libcaenhvwrapper.so; snapshots will fail.",
            file=sys.stderr,
            flush=True,
        )

    try:
        crates = load_crates()
    except (OSError, ValueError) as err:
        print(f"crates.json: {err}", file=sys.stderr)
        return 1
    if crates:
        print("Crates:    " + ", ".join(f"{crate.id} ({crate.host})" for crate in crates), flush=True)
    else:
        print("Crates:    none configured - see backend/data/crates.json", flush=True)
    print(f"Archive:   {SNAPSHOT_ROOT}", flush=True)

    if args.host in ("127.0.0.1", "localhost"):
        print("Bound to loopback only - other machines cannot reach this.", flush=True)
    else:
        # This host is on the instrument subnet, the lab LAN and a VPN at once,
        # so list every address rather than guessing which one you came in on.
        others = [ip for ip in lan_addresses() if f"http://{ip}:{args.port}" != primary]
        if others:
            print("Also reachable at:", flush=True)
            for ip in others:
                print(f"  http://{ip}:{args.port}", flush=True)

    if not STATIC_DIR.is_dir():
        print(f"note: no frontend build at {STATIC_DIR}; run `npm run build` in frontend/", flush=True)

    try:
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, log_level="info")
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                f"Port {args.port} is already in use. "
                f"Either the server is already running, or retry with --port {args.port + 1}.",
                file=sys.stderr,
            )
            return 1
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
