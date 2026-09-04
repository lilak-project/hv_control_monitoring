"""The snapshot archive: every reading ever taken, kept and browsable.

One JSON file per snapshot, filed by the crate and the local calendar day it
was taken on::

    log/snapshots/stark/2026-08-29/20260829T202233.json

Local, not UTC, because "show me yesterday afternoon" is a question about the
operator's day. The payload still carries an unambiguous UTC timestamp.

Snapshots are written indented, with each channel on its own line, so the file
can be read and grepped without a JSON tool -- see ``_dump_readable``.

Each day directory also has an ``index.jsonl`` -- one summary line per
snapshot, appended as it is written -- so listing a day never opens the
snapshots themselves. It is a cache, not the record: delete it and it is
rebuilt from the files on the next listing.
"""

from __future__ import annotations

import csv
import io
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import SNAPSHOT_ROOT

#: ``20260829T202233`` -- local date and time, seconds resolution, with a
#: ``-2`` style suffix on the rare second that gets two snapshots.
SNAPSHOT_ID = re.compile(r"^\d{8}T\d{6}(-\d+)?$")
CRATE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_write_lock = threading.Lock()

#: Placeholder for a value held back to be written on one line. Longer than
#: MAX_CH_NAME, so no channel name can ever collide with one.
_ONE_LINE_TOKEN = "@@snaplog-one-line-{}@@"


class _OneLine:
    """A value to write on a single line inside an otherwise indented document."""

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value


class _OneLineEncoder(json.JSONEncoder):
    """Writes a placeholder for each ``_OneLine`` and remembers what it stood for."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.held: dict[str, str] = {}

    def default(self, o: Any) -> Any:
        if isinstance(o, _OneLine):
            token = _ONE_LINE_TOKEN.format(len(self.held))
            self.held[token] = json.dumps(o.value, ensure_ascii=False, separators=(", ", ": "))
            return token
        return super().default(o)


def _dump_readable(snapshot: dict[str, Any]) -> str:
    """Serialise a snapshot so a person can read it.

    Indented throughout, except that each channel and each parameter
    description stays on one line. Fully indenting a channel would spread
    seventeen readings over twenty lines and put the file past a thousand
    screens; leaving the whole thing on one line, as this used to, means no
    line editor or ``grep`` is any use on it. One line per channel is the
    shape that answers "what was channel 7 doing" by eye.
    """
    document = {
        **snapshot,
        "boards": [
            {
                **board,
                "params": [_OneLine(spec) for spec in board.get("params", [])],
                "rows": [_OneLine(row) for row in board.get("rows", [])],
            }
            for board in snapshot.get("boards", [])
        ],
    }
    encoder = _OneLineEncoder(indent=2, ensure_ascii=False)
    text = encoder.encode(document)
    for token, compact in encoder.held.items():
        text = text.replace(f'"{token}"', compact)
    return text + "\n"


class NotFound(LookupError):
    """No snapshot with that id."""


def _crate_dir(crate_id: str) -> Path:
    if not CRATE_ID.match(crate_id):
        raise NotFound(f"bad crate id {crate_id!r}")
    return SNAPSHOT_ROOT / crate_id


def _day_of(snapshot_id: str) -> str:
    return f"{snapshot_id[0:4]}-{snapshot_id[4:6]}-{snapshot_id[6:8]}"


def _path(crate_id: str, snapshot_id: str) -> Path:
    if not SNAPSHOT_ID.match(snapshot_id):
        raise NotFound(f"bad snapshot id {snapshot_id!r}")
    return _crate_dir(crate_id) / _day_of(snapshot_id) / f"{snapshot_id}.json"


def summarize(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The one line the history list shows, without opening the whole file."""
    boards = snapshot.get("boards", [])
    return {
        "id": snapshot["id"],
        "crate": snapshot["crate"],
        "taken_at": snapshot["taken_at"],
        "taken_at_local": snapshot.get("taken_at_local", ""),
        "elapsed_ms": snapshot.get("elapsed_ms", 0),
        "boards": len(boards),
        "channels": sum(board.get("channels", 0) for board in boards),
        "powered": sum(board.get("powered", 0) for board in boards),
        "faults": sum(board.get("faults", 0) for board in boards),
        "errors": len(snapshot.get("errors", [])),
        "note": snapshot.get("note", ""),
    }


def save(snapshot: dict[str, Any], note: str = "") -> dict[str, Any]:
    """Write a snapshot to the archive, stamping it with an id and local time.

    Returns the snapshot with those fields filled in -- the same object the
    caller then hands to the browser, so what is shown is what was stored.
    """
    taken = datetime.fromisoformat(snapshot["taken_at"].replace("Z", "+00:00")).astimezone()
    directory = _crate_dir(snapshot["crate"]) / taken.strftime("%Y-%m-%d")

    with _write_lock:
        directory.mkdir(parents=True, exist_ok=True)
        base = taken.strftime("%Y%m%dT%H%M%S")
        snapshot_id, suffix = base, 1
        # Two snapshots in the same second is unusual but must not overwrite.
        while (directory / f"{snapshot_id}.json").exists():
            suffix += 1
            snapshot_id = f"{base}-{suffix}"

        snapshot["id"] = snapshot_id
        snapshot["taken_at_local"] = taken.isoformat(timespec="seconds")
        if note:
            snapshot["note"] = note

        path = directory / f"{snapshot_id}.json"
        # Write beside the target and rename, so a reader never sees half a file.
        temporary = path.with_suffix(".json.part")
        temporary.write_text(_dump_readable(snapshot), encoding="utf-8")
        temporary.replace(path)

        with (directory / "index.jsonl").open("a", encoding="utf-8") as index:
            index.write(json.dumps(summarize(snapshot), ensure_ascii=False) + "\n")

    return snapshot


def load(crate_id: str, snapshot_id: str) -> dict[str, Any]:
    path = _path(crate_id, snapshot_id)
    if not path.is_file():
        raise NotFound(f"no snapshot {snapshot_id} for crate {crate_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def delete(crate_id: str, snapshot_id: str) -> None:
    path = _path(crate_id, snapshot_id)
    if not path.is_file():
        raise NotFound(f"no snapshot {snapshot_id} for crate {crate_id}")
    path.unlink()
    # The index still names it; drop the stale line rather than rebuild.
    index = path.parent / "index.jsonl"
    if index.is_file():
        kept = [
            line
            for line in index.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("id") != snapshot_id
        ]
        index.write_text("".join(line + "\n" for line in kept), encoding="utf-8")


def days(crate_id: str) -> list[dict[str, Any]]:
    """Every day this crate has snapshots for, newest first, with counts."""
    directory = _crate_dir(crate_id)
    if not directory.is_dir():
        return []
    found = []
    for entry in directory.iterdir():
        if not entry.is_dir() or not _DAY.match(entry.name):
            continue
        count = sum(1 for path in entry.glob("*.json") if SNAPSHOT_ID.match(path.stem))
        if count:
            found.append({"day": entry.name, "count": count})
    return sorted(found, key=lambda item: item["day"], reverse=True)


def _read_day(crate_id: str, day: str) -> list[dict[str, Any]]:
    """Summaries for one day, from the index when it is complete."""
    directory = _crate_dir(crate_id) / day
    if not directory.is_dir():
        return []

    files = sorted(path.stem for path in directory.glob("*.json") if SNAPSHOT_ID.match(path.stem))
    if not files:
        return []

    index = directory / "index.jsonl"
    summaries: dict[str, dict[str, Any]] = {}
    if index.is_file():
        for line in index.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn line from an interrupted write
            summaries[entry.get("id", "")] = entry

    # Anything the index missed is read from the snapshot itself, so a lost or
    # partial index costs speed rather than history.
    for snapshot_id in files:
        if snapshot_id not in summaries:
            try:
                summaries[snapshot_id] = summarize(load(crate_id, snapshot_id))
            except (OSError, json.JSONDecodeError, KeyError):
                continue

    return [summaries[snapshot_id] for snapshot_id in files if snapshot_id in summaries]


def history(
    crate_id: str, day: str | None = None, limit: int = 200, before: str | None = None
) -> list[dict[str, Any]]:
    """Snapshot summaries, newest first.

    With ``day`` it is that calendar day. Without, it walks back from the most
    recent day until ``limit`` is filled, so the list opens on what just
    happened without reading years of archive.
    """
    if day is not None:
        entries = _read_day(crate_id, day)
    else:
        entries = []
        for item in days(crate_id):
            entries.extend(_read_day(crate_id, item["day"]))
            if len(entries) >= limit + (1 if before else 0):
                break

    entries.sort(key=lambda entry: entry["id"], reverse=True)
    if before:
        entries = [entry for entry in entries if entry["id"] < before]
    return entries[:limit]


def latest(crate_id: str) -> dict[str, Any] | None:
    found = history(crate_id, limit=1)
    return found[0] if found else None


def to_csv(snapshot: dict[str, Any]) -> str:
    """One row per channel, one column per parameter -- for a spreadsheet.

    Boards report different parameters, so the header is the union of them and
    a channel is blank where its board has no such parameter.
    """
    parameters: list[str] = []
    for board in snapshot.get("boards", []):
        for spec in board.get("params", []):
            if spec["name"] not in parameters:
                parameters.append(spec["name"])

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["taken_at", "crate", "slot", "model", "channel", "channel_name", *parameters, "status_flags"]
    )
    for board in snapshot.get("boards", []):
        for row in board.get("rows", []):
            values = row.get("values", {})
            writer.writerow(
                [
                    snapshot.get("taken_at_local") or snapshot.get("taken_at", ""),
                    snapshot.get("crate", ""),
                    board.get("slot", ""),
                    board.get("model", ""),
                    row.get("channel", ""),
                    row.get("name", ""),
                    *(values.get(name, "") for name in parameters),
                    " | ".join(row.get("status", {}).get("flags", [])),
                ]
            )
    return buffer.getvalue()
