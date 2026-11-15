"""Check the control gate (app/access.py) against a throwaway portal.

    cd backend && python tools/check_access.py

Needs the portal's venv (lilak_portal_auth, python-jose). Builds a fake portal
data root in a temp folder: a secret key and a portal.db holding a plain user, a
service admin and a member of an admin group, then asks /api/me and tries a
write as each of them, as nobody, and as a portal manager.
"""
import os, sqlite3, sys, tempfile
root = tempfile.mkdtemp()
os.makedirs(root + "/_portal")
open(root + "/_portal/secret.key", "w").write("test-secret")
os.environ.update(PORTAL_DATA_ROOT=root, PORTAL_SERVICE="hv", HV_DATA_DIR=root + "/data", HV_LOG_DIR=root + "/log")
db = sqlite3.connect(root + "/_portal/portal.db")
db.executescript("""
DROP TABLE IF EXISTS users; DROP TABLE IF EXISTS portal_permissions;
DROP TABLE IF EXISTS portal_group_permissions; DROP TABLE IF EXISTS portal_group_members;
CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT, is_active INT, username TEXT, display_name TEXT);
CREATE TABLE portal_permissions(user_id INT, service_name TEXT, project TEXT, is_admin INT);
CREATE TABLE portal_group_permissions(group_id INT, service_name TEXT, project TEXT, is_admin INT);
CREATE TABLE portal_group_members(user_id INT, group_id INT);
INSERT INTO users VALUES (1,'user@x',1,'u','u'),(2,'svcadmin@x',1,'a','a'),(3,'grp@x',1,'g','g');
INSERT INTO portal_permissions VALUES (1,'hv','',0),(2,'hv','',1);
INSERT INTO portal_group_members VALUES (3,7); INSERT INTO portal_group_permissions VALUES (7,'hv','',1);
"""); db.commit()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jose import jwt
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
tok = lambda email, role="user": jwt.encode({"email": email, "role": role, "sub": email}, "test-secret", algorithm="HS256")
def check(label, headers):
    me = c.get("/api/me", headers=headers).json()
    w = c.put("/api/crates/none/live-channels", headers=headers, json={"summary": True})
    r = c.get("/api/crates", headers=headers)
    print(f"{label:12} control={me['control']!s:5} write={w.status_code} read={r.status_code}")
    # Past the gate is what is being checked; what the endpoint then says is its own business.
    return me["control"], 403 if w.status_code == 403 else 200
assert check("anonymous", {}) == (False, 403)
assert check("user", {"authorization": "Bearer " + tok("user@x")}) == (False, 403)
assert check("svc admin", {"authorization": "Bearer " + tok("svcadmin@x")}) == (True, 200)
assert check("group admin", {"authorization": "Bearer " + tok("grp@x")}) == (True, 200)
assert check("manager", {"authorization": "Bearer " + tok("user@x", "manager")}) == (True, 200)
print("ok")
