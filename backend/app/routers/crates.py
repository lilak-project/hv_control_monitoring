"""The configured crates, and what is known about each one."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import snaplog
from ..schemas import CrateStatus
from ..store import find_crate, load_crates, set_live

router = APIRouter(prefix="/api/crates", tags=["crates"])


@router.get("", response_model=list[CrateStatus], summary="List the configured crates")
def list_crates() -> list[dict]:
    """Every crate in ``data/crates.json``, each with its most recent snapshot.

    Nothing here touches the hardware -- it is the list of what *could* be
    read, so the page can draw itself before anyone presses Snapshot.
    """
    return [{**crate.public(), "latest": snaplog.latest(crate.id)} for crate in load_crates()]


class LivePick(BaseModel):
    """One channel on the portal's live wall."""

    slot: int = Field(..., ge=0, description="Board slot.")
    channel: int = Field(..., ge=0, description="Channel on that board.")
    name: str = Field("", max_length=60, description="What to call it on the wall; blank = the channel's own name.")


class LiveSettings(BaseModel):
    channels: list[LivePick] | None = Field(None, description="Omit to leave the channel picks alone.")
    summary: bool | None = Field(None, description="Whether the wall shows this crate's on/trip/alarm counts.")


def _live_view(crate) -> dict:
    return {"crate": crate.id, "channels": [dict(pick) for pick in crate.live_channels],
            "summary": crate.live_summary}


@router.get("/{crate_id}/live-channels", summary="What this crate shows on the portal's live wall")
def get_live_channels(crate_id: str) -> dict:
    crate = find_crate(crate_id)
    if crate is None:
        raise HTTPException(404, f"no crate '{crate_id}'")
    return _live_view(crate)


@router.put("/{crate_id}/live-channels", summary="Choose what this crate shows on the portal's live wall")
def put_live_channels(crate_id: str, body: LiveSettings) -> dict:
    """Nothing is read from the crate here -- this only records what the live
    wall should show: the channel picks, and whether the summary counts appear."""
    try:
        crate = set_live(crate_id,
                         picks=None if body.channels is None else [pick.model_dump() for pick in body.channels],
                         summary=body.summary)
    except KeyError:
        raise HTTPException(404, f"no crate '{crate_id}'") from None
    except (OSError, ValueError) as err:
        raise HTTPException(500, f"could not save: {err}") from None
    return _live_view(crate)
