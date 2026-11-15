"""Who may read the crates on demand and change what is kept: control or monitoring.

One service, two modes. Anyone the portal lets in can watch; only a portal
manager, or an admin of THIS service (a portal grant with "admin" ticked, given
to the person or to one of their groups), can take or delete a snapshot, or change the live wall and the archive timer. The check is
here, on the server, for every request that is not a read -- the page hiding
its buttons is a convenience, not the gate.

Run on its own, with no portal around (a bench, the simulator), there is nobody
to ask, so everything is allowed -- as it always was.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import Request

try:
    from lilak_portal_auth import identity as _identity, is_manager
except ImportError:  # a bench install without the portal's venv
    _identity = None

_ROOT = os.environ.get("PORTAL_DATA_ROOT")
_SERVICE = os.environ.get("PORTAL_SERVICE", "")
UNDER_PORTAL = bool(_ROOT and _SERVICE)

#: Reads, and the calls that only ask: they never need control.
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
#: elog's endpoint answers a POST but only reads (it is the portal's machine calling).
OPEN_PATHS = {"/api/elog"}


def _service_admin(email: str | None) -> bool:
    """A grant with admin ticked on this service, direct or through a group.
    Read-only on the portal's own database; any failure means no."""
    if not email or not _ROOT:
        return False
    db = Path(_ROOT) / "_portal" / "portal.db"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            row = con.execute("SELECT id FROM users WHERE email=? AND is_active=1", (email,)).fetchone()
            if not row:
                return False
            uid = row[0]
            direct = con.execute(
                "SELECT 1 FROM portal_permissions WHERE user_id=? AND service_name=? AND is_admin=1",
                (uid, _SERVICE),
            ).fetchone()
            group = con.execute(
                "SELECT 1 FROM portal_group_permissions g JOIN portal_group_members m ON m.group_id=g.group_id "
                "WHERE m.user_id=? AND g.service_name=? AND g.is_admin=1",
                (uid, _SERVICE),
            ).fetchone()
            return bool(direct or group)
        finally:
            con.close()
    except sqlite3.Error:
        return False


def who(request: Request) -> dict:
    """The caller's name and whether they may control. Blocking (it may ask the
    portal and read its database): call it off the event loop."""
    if not UNDER_PORTAL or _identity is None:
        return {"name": None, "control": True, "standalone": True}
    me = _identity(request, request.headers.get("authorization"))
    control = bool(me.get("authenticated")) and (is_manager(me) or _service_admin(me.get("email")))
    return {"name": me.get("name"), "control": control, "standalone": False}


def needs_control(request: Request) -> bool:
    path = request.url.path
    return request.method not in SAFE_METHODS and path.startswith("/api/") and path not in OPEN_PATHS
