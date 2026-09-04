"""Take one reading of a whole crate, on request.

A snapshot is a single pass: log in, walk every populated slot, read every
parameter the board reports across all of its channels in one call each, log
out. Against a reachable crate that is a fraction of a second, which is why
this service has no polling loop -- you press the button, it goes and looks.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from .caen import Board, CaenError, CaenSession, ParamSpec, decode_status, status_is_fault
from .config import BUSY_TIMEOUT, PARAM_ORDER
from .store import CrateConfig

#: Parameter descriptions keyed by the board they belong to.  Asking a board
#: what its parameters are costs ~70 round trips and the answer only changes
#: when the card in the slot does, so it is remembered across snapshots.
_spec_cache: dict[tuple[str, int, str, int, str], list[ParamSpec]] = {}
_spec_lock = threading.Lock()


def _spec_key(host: str, board: Board) -> tuple[str, int, str, int, str]:
    return (host, board.slot, board.model, board.serial, board.firmware)


def forget_specs() -> None:
    """Drop the cache, so the next snapshot re-reads what the boards are."""
    with _spec_lock:
        _spec_cache.clear()


def _ordered(specs: list[ParamSpec]) -> list[ParamSpec]:
    """Useful parameters first; anything unrecognised keeps the board's order."""
    rank = {name: index for index, name in enumerate(PARAM_ORDER)}
    return sorted(specs, key=lambda spec: (rank.get(spec.name, len(rank)), spec.name))


def _read_board(session: CaenSession, host: str, board: Board) -> dict[str, Any]:
    key = _spec_key(host, board)
    with _spec_lock:
        specs = _spec_cache.get(key)
    if specs is None:
        specs = _ordered(session.param_specs(board.slot))
        with _spec_lock:
            _spec_cache[key] = specs

    names = session.channel_names(board.slot, board.channels)

    columns: dict[str, list[Any]] = {}
    unreadable: list[str] = []
    for spec in specs:
        values = session.read_param(board.slot, spec, board.channels)
        if values is None:
            unreadable.append(spec.name)
            continue
        columns[spec.name] = values

    rows: list[dict[str, Any]] = []
    for channel in range(board.channels):
        values = {name: column[channel] for name, column in columns.items()}
        row: dict[str, Any] = {
            "channel": channel,
            "name": names[channel] if channel < len(names) else "",
            "values": values,
        }
        raw_status = values.get("Status")
        # The bit names are the HV boards' map. A low-voltage card such as the
        # A2551A numbers its status word differently, so the raw word travels
        # with the flags and the UI shows it on hover.
        if isinstance(raw_status, int):
            row["status"] = {
                "raw": raw_status,
                "flags": decode_status(raw_status),
                "fault": status_is_fault(raw_status),
            }
        rows.append(row)

    powered = sum(1 for row in rows if row["values"].get("Pw") == 1)
    faults = sum(1 for row in rows if row.get("status", {}).get("fault"))

    return {
        "slot": board.slot,
        "model": board.model,
        "description": board.description,
        "serial": board.serial,
        "firmware": board.firmware,
        "channels": board.channels,
        "params": [spec.as_dict() for spec in specs if spec.name in columns],
        "rows": rows,
        "powered": powered,
        "faults": faults,
        "unreadable_params": unreadable,
    }


def take(crate: CrateConfig, busy_timeout: float | None = None) -> dict[str, Any]:
    """Read the whole crate now.  Raises ``CaenError`` if the login fails.

    A board that fails mid-sweep is reported in ``errors`` and the rest of the
    crate still comes back: one dead card should not blank the page.

    ``busy_timeout`` is how long to wait for the CAEN library when another read
    already holds it. The default is generous because a person who pressed the
    button wants the reading. A caller working to someone else's deadline --
    the elog webhook has five seconds for the whole round trip -- passes a short
    one and handles ``CaenBusy`` by falling back to what it already has.
    """
    with CaenSession(
        crate.host,
        crate.username,
        crate.password,
        crate.system_type,
        busy_timeout=BUSY_TIMEOUT if busy_timeout is None else busy_timeout,
    ) as session:
        # Stamped inside the session, not before it: a request that queued
        # behind another crate read should report when the crate was actually
        # looked at, and how long that look took -- not how long it waited.
        started = time.monotonic()
        taken_at = datetime.now(timezone.utc)
        boards_meta = session.crate_map()
        boards: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for board in boards_meta:
            try:
                boards.append(_read_board(session, crate.host, board))
            except CaenError as err:
                errors.append({"slot": str(board.slot), "error": str(err)})
        elapsed_ms = round((time.monotonic() - started) * 1000)

    return {
        "crate": crate.id,
        "label": crate.label,
        "host": crate.host,
        "system_type": crate.system_type,
        "taken_at": taken_at.isoformat().replace("+00:00", "Z"),
        "elapsed_ms": elapsed_ms,
        "boards": boards,
        "errors": errors,
    }
