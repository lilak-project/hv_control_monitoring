"""Take a snapshot, and read back every snapshot ever taken."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from .. import snaplog, snapshot
from ..caen import CaenBusy, CaenError
from ..config import HISTORY_PAGE
from ..schemas import Day, SnapshotSummary
from ..store import find_crate

log = logging.getLogger("hv")

router = APIRouter(prefix="/api/crates/{crate_id}", tags=["snapshots"])


def _crate(crate_id: str):
    crate = find_crate(crate_id)
    if crate is None:
        raise HTTPException(404, f"no crate {crate_id!r} in crates.json")
    return crate


# Defined as `def`, not `async def`: reading a crate is a blocking C call, and
# FastAPI runs a sync handler in a worker thread rather than on the event loop.
@router.post("/snapshot", summary="Read the crate now and archive the result")
def take_snapshot(crate_id: str, note: str = Query("", max_length=200)) -> dict:
    """Log in, read every board, log out, and file the result under today.

    The response is the snapshot itself, with the ``id`` it was stored under --
    so what the page draws is exactly what went into the archive.
    """
    crate = _crate(crate_id)
    try:
        reading = snapshot.take(crate)
    except CaenBusy as err:
        raise HTTPException(409, str(err)) from err
    except CaenError as err:
        # An unreachable crate is an expected outcome, not a server fault.
        raise HTTPException(502, str(err)) from err

    stored = snaplog.save(reading, note=note.strip())
    log.info(
        "snapshot %s/%s: %d boards, %d ms",
        crate.id,
        stored["id"],
        len(stored["boards"]),
        stored["elapsed_ms"],
    )
    return stored


@router.get(
    "/snapshots",
    response_model=list[SnapshotSummary],
    summary="List archived snapshots, newest first",
)
def list_snapshots(
    crate_id: str,
    day: str | None = Query(None, description="A local calendar day, YYYY-MM-DD."),
    limit: int = Query(HISTORY_PAGE, ge=1, le=2000),
    before: str | None = Query(None, description="Only snapshots older than this id."),
) -> list[dict]:
    _crate(crate_id)
    return snaplog.history(crate_id, day=day, limit=limit, before=before)


@router.get("/snapshots/days", response_model=list[Day], summary="Days that have snapshots")
def list_days(crate_id: str) -> list[dict]:
    _crate(crate_id)
    return snaplog.days(crate_id)


@router.get("/snapshots/{snapshot_id}", summary="Read one archived snapshot")
def read_snapshot(crate_id: str, snapshot_id: str) -> dict:
    _crate(crate_id)
    try:
        return snaplog.load(crate_id, snapshot_id)
    except snaplog.NotFound as err:
        raise HTTPException(404, str(err)) from err


@router.get(
    "/snapshots/{snapshot_id}/csv",
    response_class=PlainTextResponse,
    summary="One archived snapshot as CSV",
)
def snapshot_csv(crate_id: str, snapshot_id: str) -> PlainTextResponse:
    """A channel per row, for pasting into whatever the analysis lives in."""
    _crate(crate_id)
    try:
        stored = snaplog.load(crate_id, snapshot_id)
    except snaplog.NotFound as err:
        raise HTTPException(404, str(err)) from err
    return PlainTextResponse(
        snaplog.to_csv(stored),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{crate_id}-{snapshot_id}.csv"',
        },
    )


@router.delete("/snapshots/{snapshot_id}", status_code=204, summary="Delete one snapshot")
def delete_snapshot(crate_id: str, snapshot_id: str) -> None:
    _crate(crate_id)
    try:
        snaplog.delete(crate_id, snapshot_id)
    except snaplog.NotFound as err:
        raise HTTPException(404, str(err)) from err
