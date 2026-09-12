"""CAEN HV monitoring service.

Serves a JSON API and, once the frontend is built, the single-page UI from the
same origin and port.

A crate is read when someone asks -- a snapshot from the UI, a fill from elog,
the portal's live wall -- and on one timer of its own (app/archive.py), which
is what keeps the history from depending on whether anybody happened to look.
Every read is a login, so the timer reuses a recent reading rather than taking
its own wherever it can.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from .caen import library_release
from .config import SNAPSHOT_ROOT, STATIC_DIR
from . import archive, elog
from .routers import crates, snapshots
from .store import load_crates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hv")

app = FastAPI(
    title="HV Monitoring",
    description=(
        "On-demand readout of the CAEN HV crates. A snapshot logs in, reads "
        "every parameter of every channel on every populated board, logs out, "
        "and is archived under the day it was taken."
    ),
    version="1.0.0",
)

# The Vite dev server runs on another port; in production the UI is same-origin
# and these headers are simply unused.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"http://(localhost|127\.0\.0\.1"
        r"|10\.\d+\.\d+\.\d+"
        r"|192\.168\.\d+\.\d+"
        r"|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(crates.router)
app.include_router(snapshots.router)
# The LILAK elog asks this service to fill a task log; see app/elog.py.
app.include_router(elog.router)


@app.on_event("startup")
def _start_archiver() -> None:
    archive.start()


@app.on_event("shutdown")
def _stop_archiver() -> None:
    archive.stop()


@app.get("/api/archive-timer", tags=["meta"], summary="What the archive timer is doing")
def archive_timer() -> list[dict]:
    return archive.status()


@app.get("/api/live", tags=["meta"], summary="Compact numbers for the portal's live mode")
def live() -> dict:
    """What the crate is doing NOW, without archiving anything.

    The reading comes from the same short-lived cache the elog fills use
    (app/elog.live_reading), so the wall polling every few seconds costs at
    most one crate read per HV_LIVE_MAX_AGE seconds and writes no snapshot.
    Each crate contributes its counts unless its summary is switched off in the
    UI; a crate with channels picked ("LIVE" on a channel row) also contributes
    one tile per channel. A crate with neither is not read at all.
    """
    from . import elog as elog_mod

    items = []
    crates = load_crates()
    shown = [crate for crate in crates if crate.live_summary or crate.live_channels]
    for crate in shown:
        prefix = f"{crate.label or crate.id} · " if len(shown) > 1 else ""
        reading, age, source = elog_mod.live_reading(crate)
        if reading is None:
            items.append({"label": crate.label or crate.id, "value": "—", "unit": "", "state": "down",
                          "sub": "unreachable"})
            continue

        rows = {(board["slot"], row["channel"]): (board, row)
                for board in reading.get("boards") or []
                for row in board.get("rows") or []}
        powered = trips = faults = 0
        for _, row in rows.values():
            status = row.get("status") or {}
            flags = [str(f).upper() for f in (status.get("flags") or [])]
            if (row.get("values") or {}).get("Pw") == 1:
                powered += 1
            if status.get("fault"):
                faults += 1
            if any("TRIP" in f for f in flags):
                trips += 1
        # The age is part of the reading: these numbers are minutes old by
        # design (see elog.LIVE_MAX_AGE_SEC), and a wall that hid that would be
        # claiming a liveness it does not have.
        stale = age is not None and age > 90
        sub = "" if not stale else (f"{int(age / 60)} min old" if age >= 120 else f"{int(age)} s old")
        if crate.live_summary:
            items.append({"label": prefix + "on", "value": str(powered), "unit": "ch",
                          "state": "warn" if stale else ("ok" if powered else ""), "sub": sub})
            items.append({"label": prefix + "trip", "value": str(trips), "unit": "", "state": "trip" if trips else ""})
            items.append({"label": prefix + "alarm", "value": str(faults), "unit": "", "state": "alarm" if faults else ""})

        for pick in crate.live_channels:
            found = rows.get((pick["slot"], pick["channel"]))
            label = pick.get("name") or (found and found[1].get("name")) or f"{pick['slot']}.{pick['channel']}"
            if not found:
                items.append({"label": prefix + label, "value": "—", "unit": "", "state": "off",
                              "sub": f"slot {pick['slot']} ch {pick['channel']} not read"})
                continue
            _, row = found
            values = row.get("values") or {}
            status = row.get("status") or {}
            flags = [str(f).upper() for f in (status.get("flags") or [])]
            on = values.get("Pw") == 1
            vmon = values.get("VMon")
            imon = values.get("IMon")
            state = "alarm" if status.get("fault") else ("trip" if any("TRIP" in f for f in flags)
                                                         else ("ok" if on else "off"))
            bits = []
            if imon is not None:
                try:
                    bits.append(f"{float(imon):g} µA")
                except (TypeError, ValueError):
                    pass
            bits.append("on" if on else "off")
            items.append({"label": prefix + label, "value": "—" if vmon is None else f"{float(vmon):g}",
                          "unit": "V" if vmon is not None else "", "state": state,
                          "sub": " · ".join(bits), "title": f"slot {pick['slot']} ch {pick['channel']}"})
    return {"ok": True, "items": items}


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    """Whether the service can do its job, without touching a crate to find out."""
    release = library_release()
    return {
        "ok": bool(release),
        "caen_library": release or "not loaded",
        "crates": [crate.id for crate in load_crates()],
        "archive": str(SNAPSHOT_ROOT),
    }


class UiFiles(StaticFiles):
    """Serve the built UI, revalidating the entry point on every load.

    Vite fingerprints the asset filenames, so those can be cached hard. The
    HTML that points at them must not be, or a browser keeps running the
    previous build after a redeploy and calls endpoints that no longer exist.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if path.endswith(".html") or path in ("", "."):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif response.status_code == 200 and "/assets/" in scope.get("path", ""):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


if STATIC_DIR.is_dir():
    # Mounted last so it never shadows /api.
    app.mount("/", UiFiles(directory=STATIC_DIR, html=True), name="ui")
else:
    log.warning("Frontend build not found at %s - run `npm run build` in frontend/", STATIC_DIR)

    @app.get("/", tags=["meta"])
    def missing_ui() -> dict:
        return {
            "ok": False,
            "error": "Frontend is not built.",
            "hint": "cd frontend && npm install && npm run build",
            "api_docs": "/docs",
        }
