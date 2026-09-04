"""The LILAK elog endpoint: one POST that answers both of elog's questions.

elog talks to a service through a single URL. Two different bodies arrive on it:

    {"event": "elog_handshake", "elog_url": …}
        -> who we are and what fields we can fill (Discover, once, at registration)

    {"format_id", "format_name", "task_log_id", "run_number", "requested_at", "mode"}
        -> the values themselves (every fill, on a task or on a schedule)

Two rules shape everything below.

**Five seconds.** elog gives up after that (`WEBHOOK_TIMEOUT_SEC`) and turns the
task into a manual one with the error as a comment. `mode` may also be
"realtime", which repeats as often as twice a second. So a reader here must be
cheap and must never block on hardware it does not already hold.

**The field list is fixed.** elog builds a log format from `log_fields` at
registration and matches it later by name *and* field signature: declare a
different set and a second format appears rather than the first one changing.
So `log_fields` must come from configuration, never from what is currently
plugged in, connected or selected -- otherwise unplugging a cable forks the
format and last week's entries stop lining up with this week's.

Copied into each service rather than shared from one place: these services are
each movable as a single folder (SERVICE_CONTRACT §9), and a shared import
would tie them together at runtime for eighty lines.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("elog")

HANDSHAKE = "elog_handshake"

#: A field elog can put on a log format.
#: `type` is one of number_entry | number | text | body | title | tags | level.
#: `metric` (number types only) makes it an Infography variable.
Field = dict[str, Any]


def number(key: str, label: str, unit: str = "", metric: bool = True) -> Field:
    """A numeric field. number_entry is the shape elog normalises to {value,error}."""
    return {"key": key, "label": label, "type": "number_entry", "unit": unit, "metric": metric}


def text(key: str, label: str) -> Field:
    return {"key": key, "label": label, "type": "text"}


def body(label: str = "Summary") -> Field:
    return {"key": "body", "label": label, "type": "body"}


def value(number_value: float | None, error: float = 0.0) -> dict:
    """One number_entry value. None stays None -- a channel that reported
    nothing is not the same as one that reported zero."""
    return {"value": None if number_value is None else float(number_value), "error": error}


def make_router(
    *,
    service_name: str,
    description: str,
    log_fields: list[Field] | Callable[[], Awaitable[list[Field]]],
    read: Callable[[dict], Awaitable[dict]],
    directory: str = "",
    path: str = "/api/elog",
) -> APIRouter:
    """The endpoint. `read(envelope)` returns the `fields` dict for one request.

    `log_fields` is normally a plain list -- a constant, which is what the
    "fixed field list" rule above asks for. It may instead be an async callable
    for a service whose fields come from its own saved configuration (which
    actuators are set up, say). That is still configuration and still stable;
    it just cannot be written down at import time. Such a callable should RAISE
    rather than return a short list when it cannot read that configuration, so
    Discover fails loudly instead of quietly registering half a format.

    Mount this BEFORE any catch-all `/api/{path}` route: FastAPI matches in
    registration order, and the read-only mirrors answer 405 to every POST they
    do not recognise -- including this one.
    """
    router = APIRouter(tags=["elog"])

    @router.post(path, summary="LILAK elog handshake and data request")
    async def elog_endpoint(request: Request):
        try:
            envelope = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "body must be JSON"})
        if not isinstance(envelope, dict):
            return JSONResponse(status_code=400, content={"detail": "body must be a JSON object"})

        event = envelope.get("event")
        if event == HANDSHAKE:
            log.info("elog handshake from %s", envelope.get("elog_url") or "?")
            try:
                fields = log_fields if isinstance(log_fields, list) else await log_fields()
            except Exception as err:
                log.warning("handshake refused: %s", err)
                return JSONResponse(status_code=503, content={"detail": str(err)})
            return {
                "name": service_name,
                "description": description,
                "hostname": socket.gethostname(),
                "directory": directory,
                # A service, not a system: elog asks us, we never push runs at it.
                "is_system": False,
                "log_fields": fields,
            }
        if event:
            # Only the handshake is an event. Anything else is a system-only
            # message (elog_credentials) or a typo, and answering it with
            # readings would be worse than saying so.
            return JSONResponse(
                status_code=400,
                content={"detail": f"unknown event {event!r}; this is a plain service, not a system"},
            )

        fields = await read(envelope)
        return {"fields": fields}

    return router


# ── This service's answer ────────────────────────────────────────────────────

import os                                                          # noqa: E402
import threading                                                   # noqa: E402
import time                                                        # noqa: E402
from datetime import datetime, timezone                            # noqa: E402

from fastapi.concurrency import run_in_threadpool                  # noqa: E402

from . import snaplog, snapshot                                    # noqa: E402
from .caen import CaenError                                        # noqa: E402
from .config import SNAPSHOT_ROOT                                  # noqa: E402
from .store import load_crates                                     # noqa: E402

#: How stale a reading may be before this endpoint goes and takes a new one.
#:
#: The crate is not polled by this service -- a reading is a login, a sweep and
#: a logout -- so without a floor, elog's realtime mode (as often as twice a
#: second) would hold the CAEN library permanently and lock out the operator
#: pressing Snapshot. Thirty seconds is well inside what an HV log entry needs
#: and far outside what would get in anyone's way.
MAX_AGE_SEC = float(os.environ.get("HV_ELOG_MAX_AGE", "30"))

#: How long to wait for the CAEN library before giving up and answering from
#: the last reading. elog's whole round trip has five seconds.
BUSY_WAIT_SEC = float(os.environ.get("HV_ELOG_BUSY_WAIT", "1.5"))

#: Fixed, whatever cards are in the crate.
#:
#: Fifty-six channels times name/VMon/IMon/on-off would be over a hundred and
#: fifty fields, and swapping a card would change the list and fork the format.
#: So the numbers worth plotting are declared as numbers, and the per-channel
#: detail -- which is a table, and reads like one -- goes in the body.
LOG_FIELDS = [
    number("channels_on", "Channels on", "ch"),
    number("channels_total", "Channels total", "ch"),
    number("faults", "Channels in fault", "ch"),
    number("reading_age_s", "Age of this reading", "s", metric=False),
    text("crate", "Crate"),
    text("taken_at", "Reading taken at"),
    body("Every channel"),
]

_lock = threading.Lock()
#: crate id -> (monotonic seconds when taken, the reading)
_cache: dict[str, tuple[float, dict]] = {}


def _cached(crate_id: str) -> tuple[float, dict] | None:
    with _lock:
        return _cache.get(crate_id)


def _remember(crate_id: str, reading: dict) -> None:
    with _lock:
        _cache[crate_id] = (time.monotonic(), reading)


def _reading(crate) -> tuple[dict | None, float | None, str]:
    """The crate's state: the reading, how old it is in seconds, and where it came from.

    Three sources, in order of preference -- a fresh sweep, the last one this
    endpoint took, and the newest archived snapshot. The archive matters: a
    service that has just restarted has no cache, and an hour-old reading
    labelled as an hour old is far better for a logbook than a blank.

    Deliberately does NOT archive what it reads. The archive is the record of
    snapshots somebody chose to take; filling it twice a minute from a webhook
    would bury those.
    """
    held = _cached(crate.id)
    if held is not None and time.monotonic() - held[0] < MAX_AGE_SEC:
        return held[1], time.monotonic() - held[0], "live"

    try:
        fresh = snapshot.take(crate, busy_timeout=BUSY_WAIT_SEC)
    except CaenError as err:
        log.info("%s: %s; answering from the last reading", crate.id, err)
    else:
        _remember(crate.id, fresh)
        return fresh, 0.0, "live"

    if held is not None:
        return held[1], time.monotonic() - held[0], "cached"

    summary = snaplog.latest(crate.id)
    if summary is not None:
        try:
            stored = snaplog.load(crate.id, summary["id"])
        except (OSError, ValueError, KeyError):
            return None, None, "unreachable"
        return stored, _age_of(stored), "archive"

    return None, None, "unreachable"


def _age_of(reading: dict) -> float | None:
    """Seconds since a reading's own timestamp, for one loaded from the archive."""
    try:
        taken = datetime.fromisoformat(str(reading["taken_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None
    return max(0.0, (datetime.now(timezone.utc) - taken).total_seconds())


def _unit(board: dict, param: str) -> str:
    """The unit THIS board reports a parameter in.

    Not a constant: on the same crate an A1542HSN reports IMon in µA and an
    A2551A low-voltage card reports it in A. A hardcoded "uA" would write 1.35 A
    into a logbook as 1.35 µA, and nothing downstream could tell.
    """
    for spec in board.get("params", []):
        if spec.get("name") == param:
            return spec.get("unit") or ""
    return ""


def _rows(reading: dict) -> list[str]:
    """One line per channel: slot, channel, name, VMon, IMon, and on or off."""
    lines = []
    for board in reading.get("boards", []):
        volt_unit = _unit(board, "VMon")
        current_unit = _unit(board, "IMon")
        for row in board.get("rows", []):
            values = row.get("values", {})
            fault = " FAULT" if (row.get("status") or {}).get("fault") else ""
            lines.append(
                f"{board['slot']:>2}.{row['channel']:<3} {row.get('name') or '':<22} "
                f"{_fmt(values.get('VMon')):>10} {volt_unit:<3}"
                f"{_fmt(values.get('IMon')):>10} {current_unit:<3}"
                f"{'on ' if values.get('Pw') == 1 else 'off'}{fault}"
            )
    return lines


def _fmt(number_value) -> str:
    if number_value is None:
        return "—"
    try:
        return f"{float(number_value):,.2f}"
    except (TypeError, ValueError):
        return str(number_value)


def _counts(reading: dict) -> tuple[int, int, int]:
    total = on = faults = 0
    for board in reading.get("boards", []):
        for row in board.get("rows", []):
            total += 1
            if row.get("values", {}).get("Pw") == 1:
                on += 1
            if (row.get("status") or {}).get("fault"):
                faults += 1
    return on, total, faults


async def read(envelope: dict) -> dict:
    """Every channel of the first configured crate.

    One crate, not all of them: a log format has one set of fields, and a
    second crate's channels would have nowhere to go. Which crate is the first
    in crates.json -- and its name is in the log, so a two-crate bench can tell.
    """
    crates = await run_in_threadpool(load_crates)
    if not crates:
        return {
            "channels_on": value(None), "channels_total": value(None),
            "faults": value(None), "reading_age_s": value(None),
            "crate": "", "taken_at": "",
            "body": "No crate is configured in this service.",
        }

    crate = crates[0]
    # A crate read is a blocking C call; off the event loop it goes.
    reading, age, source = await run_in_threadpool(_reading, crate)

    if reading is None:
        return {
            "channels_on": value(None), "channels_total": value(None),
            "faults": value(None), "reading_age_s": value(None),
            "crate": crate.label or crate.id, "taken_at": "",
            "body": (f"{crate.label or crate.id} ({crate.host}) could not be read and "
                     "there is no earlier reading to fall back on."),
        }

    on, total, faults = _counts(reading)
    lines = _rows(reading) or ["The crate reported no channels."]
    if source != "live":
        note = ("from this service's last reading" if source == "cached"
                else "from the newest archived snapshot")
        lines.append("")
        lines.append(f"⚠ the crate did not answer just now; the above is {note}"
                     + (f", {age:,.0f} s old" if age is not None else ""))

    return {
        "channels_on": value(on),
        "channels_total": value(total),
        "faults": value(faults),
        "reading_age_s": value(None if age is None else round(age, 1)),
        "crate": crate.label or crate.id,
        "taken_at": reading.get("taken_at", ""),
        "body": "\n".join(lines),
    }


router = make_router(
    service_name="HV Monitoring",
    description="CAEN crate readout — per-channel name, VMon, IMon and on/off, plus the powered/fault counts.",
    log_fields=LOG_FIELDS,
    read=read,
    directory=str(SNAPSHOT_ROOT),
)
