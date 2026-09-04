"""Filesystem locations and tunables shared by the whole backend."""

from __future__ import annotations

import os
from pathlib import Path

#: backend/
BACKEND_ROOT = Path(__file__).resolve().parent.parent

#: Where this service's STATE lives -- kept apart from its code so the service is
#: movable as one folder (LILAK SERVICE_CONTRACT §9). Standalone this is
#: ``backend/``, exactly as before. Started by the LILAK portal it is the portal's
#: own data dir for this service, handed over as PORTAL_DATA_ROOT + PORTAL_SERVICE.
#: Deriving it here rather than spelling it out in the service manifest is what
#: keeps absolute paths out of that manifest: the portal substitutes {data_root}
#: style placeholders for multi-project services only, never for a single one.
_portal_root = os.environ.get("PORTAL_DATA_ROOT")
_portal_service = os.environ.get("PORTAL_SERVICE")
STATE_ROOT = (Path(_portal_root) / _portal_service
              if _portal_root and _portal_service else BACKEND_ROOT)

#: Where crates.json lives.  Override with HV_DATA_DIR.
DATA_DIR = Path(os.environ.get("HV_DATA_DIR", STATE_ROOT / "data")).resolve()

#: The crates this service knows how to reach.
CRATE_FILE = DATA_DIR / "crates.json"

#: Root of the snapshot archive.  One JSON file per snapshot, filed under
#: ``<SNAPSHOT_ROOT>/<crate>/<YYYY-MM-DD>/``.
SNAPSHOT_ROOT = Path(os.environ.get("HV_LOG_DIR", STATE_ROOT / "log")).resolve() / "snapshots"

#: Built frontend (``frontend/dist``).  Served at / when present.
STATIC_DIR = Path(
    os.environ.get("HV_STATIC_DIR", BACKEND_ROOT.parent / "frontend" / "dist")
).resolve()

#: The CAEN library is not thread-safe, so snapshots take a process-wide lock.
#: A sweep of a reachable crate holds it for ~0.15 s and a login to an
#: unreachable one for ~5 s; past this the caller is told the crate is busy
#: rather than left hanging on a request that will not return.
BUSY_TIMEOUT = float(os.environ.get("HV_BUSY_TIMEOUT", "30"))

#: Newest snapshots offered in the history list before the caller has to ask
#: for a specific day.
HISTORY_PAGE = int(os.environ.get("HV_HISTORY_PAGE", "200"))

#: Parameters worth seeing first.  Everything the board reports is kept in the
#: snapshot; this only decides column order, and which columns the table opens
#: with.  Anything not named here is appended in the order the board lists it.
PARAM_ORDER = (
    "VMon",
    "IMon",
    "V0Set",
    "I0Set",
    "Pw",
    "Status",
    "V1Set",
    "I1Set",
    "RUp",
    "RDWn",
    "Trip",
    "SVMax",
    "POn",
    "PDwn",
    "ImRange",
    "TripInt",
    "TripExt",
)

#: The columns the table shows until you ask for the rest.  What you check
#: when you walk past the rack: is it on, where is it, is it drawing current.
CORE_PARAMS = ("VMon", "IMon", "V0Set", "I0Set", "Pw", "Status")
