"""Response shapes, for the generated API docs.

The snapshot payload itself stays a plain dict: its columns are whatever the
boards in the crate report, and pinning that down in a model would only
describe today's cards.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LiveChannel(BaseModel):
    """One channel on the LILAK portal's live wall."""

    slot: int
    channel: int
    name: str = ""


class Crate(BaseModel):
    id: str = Field(description="Short name used in URLs, e.g. 'stark'.")
    label: str
    host: str
    system_type: str
    username: str
    note: str = ""
    live_channels: list[LiveChannel] = Field(
        default_factory=list, description="Channels shown on the portal's live wall."
    )
    live_summary: bool = Field(True, description="Whether the wall shows this crate's on/trip/alarm counts.")


class SnapshotSummary(BaseModel):
    """One line of the history list."""

    id: str = Field(description="Local timestamp, e.g. '20260829T202233'.")
    crate: str
    taken_at: str = Field(description="UTC, ISO 8601.")
    taken_at_local: str = Field(description="Server local time, ISO 8601 with offset.")
    elapsed_ms: int
    boards: int
    channels: int
    powered: int = Field(description="Channels with Pw on.")
    faults: int = Field(description="Channels whose Status word has a fault bit set.")
    errors: int
    note: str = ""


class CrateStatus(Crate):
    """A crate plus the last time anyone looked at it."""

    latest: SnapshotSummary | None = None


class Day(BaseModel):
    day: str = Field(description="Local calendar day, YYYY-MM-DD.")
    count: int
