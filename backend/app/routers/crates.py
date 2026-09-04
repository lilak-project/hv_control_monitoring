"""The configured crates, and what is known about each one."""

from __future__ import annotations

from fastapi import APIRouter

from .. import snaplog
from ..schemas import CrateStatus
from ..store import load_crates

router = APIRouter(prefix="/api/crates", tags=["crates"])


@router.get("", response_model=list[CrateStatus], summary="List the configured crates")
def list_crates() -> list[dict]:
    """Every crate in ``data/crates.json``, each with its most recent snapshot.

    Nothing here touches the hardware -- it is the list of what *could* be
    read, so the page can draw itself before anyone presses Snapshot.
    """
    return [{**crate.public(), "latest": snaplog.latest(crate.id)} for crate in load_crates()]
