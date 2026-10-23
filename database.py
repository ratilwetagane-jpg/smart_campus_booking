"""
database.py - SQLite persistence layer for the Smart Campus Resource Booking System.

Responsibilities:
  * create the schema (users, campuses, resources, bookings)
  * provide small helper methods for queries and transactions
  * seed the database with default campuses, resources and accounts on first run
"""
import hashlib
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "campus_booking.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS campuses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    policy_key  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name      TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('lecturer','campus_admin','operator')),
    password_hash  TEXT NOT NULL,
    salt           TEXT NOT NULL,
    campus_id      INTEGER REFERENCES campuses(id)
);

CREATE TABLE IF NOT EXISTS resources (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_code  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name           TEXT NOT NULL,
    type           TEXT NOT NULL,
    capacity       INTEGER NOT NULL DEFAULT 0,
    campus_id      INTEGER NOT NULL REFERENCES campuses(id),
    active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bookings (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id      INTEGER NOT NULL REFERENCES resources(id),
    lecturer_id      INTEGER NOT NULL REFERENCES users(id),
    campus_id        INTEGER NOT NULL REFERENCES campuses(id),
    booking_date     TEXT NOT NULL,          -- YYYY-MM-DD
    start_time       TEXT NOT NULL,          -- HH:MM
    end_time         TEXT NOT NULL,          -- HH:MM (24:00 allowed for midnight)
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','cancelled')),
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bookings_resource_date ON bookings(resource_id, booking_date);
CREATE INDEX IF NOT EXISTS idx_bookings_lecturer ON bookings(lecturer_id);
CREATE INDEX IF NOT EXISTS idx_bookings_campus ON bookings(campus_id);
"""


def hash_password(password, salt=None):
    """Return (hash_hex, salt_hex) using PBKDF2-HMAC-SHA256 (never store plain text)."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt), 100_000)
    return digest.hex(), salt


class Database:
    """Thin wrapper around an SQLite connection."""

    def __init__(self, path=DEFAULT_DB_PATH):
        self.path = path
        # isolation_level=None -> autocommit; transactions are handled explicitly.
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    # ---- basic helpers -------------------------------------------------
    def execute(self, sql, params=()):
        return self.conn.execute(sql, params)

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    @contextmanager
    def transaction(self):
        """Atomic block. BEGIN IMMEDIATE locks writers so overlap checks are race-free."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------------------
# Seed data (only inserted when the database is empty)
# ---------------------------------------------------------------------------
SEED_CAMPUSES = [
    ("Centurion Campus", "centurion"),
    ("Durban Campus", "durban"),
    ("Pretoria Campus", "pretoria"),
]

# (code, name, type, capacity, campus name)
SEED_RESOURCES = [
    ("CEN-LAB-01", "Computer Lab A", "Computer Laboratory", 40, "Centurion Campus"),
    ("CEN-LAB-02", "Computer Lab B", "Computer Laboratory", 30, "Centurion Campus"),
    ("CEN-PRJ-01", "Mobile Projector 1", "Multimedia Projector", 0, "Centurion Campus"),
    ("CEN-SEM-01", "Seminar Room 1", "Seminar Room", 25, "Centurion Campus"),
    ("DBN-LAB-01", "Computer Lab 1", "Computer Laboratory", 35, "Durban Campus"),
    ("DBN-PRJ-01", "Projector Kit 1", "Multimedia Projector", 0, "Durban Campus"),
    ("DBN-SEM-01", "Seminar Room Alpha", "Seminar Room", 30, "Durban Campus"),
    ("DBN-PRS-01", "Presentation Kit 1", "Presentation Equipment", 0, "Durban Campus"),
    ("PTA-LAB-01", "Computer Lab North", "Computer Laboratory", 45, "Pretoria Campus"),
    ("PTA-PRJ-01", "Projector Kit A", "Multimedia Projector", 0, "Pretoria Campus"),
    ("PTA-SEM-01", "Seminar Room East", "Seminar Room", 20, "Pretoria Campus"),
]


def _add_user(db, username, full_name, role, password, campus_id=None):
    pw_hash, salt = hash_password(password)
    cur = db.execute(
        "INSERT INTO users (username, full_name, role, password_hash, salt, campus_id) "
        "VALUES (?,?,?,?,?,?)", (username, full_name, role, pw_hash, salt, campus_id))
    return cur.lastrowid


def seed_defaults(db):
    """Populate an empty database with campuses, resources, default accounts and demo data."""
    if db.query_one("SELECT COUNT(*) AS n FROM campuses")["n"] > 0:
        return
    campus_ids = {}
    for name, policy in SEED_CAMPUSES:
        campus_ids[name] = db.execute(
            "INSERT INTO campuses (name, policy_key) VALUES (?,?)", (name, policy)).lastrowid

    resource_ids = {}
    for code, name, rtype, cap, campus in SEED_RESOURCES:
        resource_ids[code] = db.execute(
            "INSERT INTO resources (resource_code, name, type, capacity, campus_id) "
            "VALUES (?,?,?,?,?)", (code, name, rtype, cap, campus_ids[campus])).lastrowid

    # Default accounts (documented in README.md)
    _add_user(db, "operator", "System Operator", "operator", "Operator@123")
    _add_user(db, "admin_cen", "Centurion Administrator", "campus_admin",
              "Admin@123", campus_ids["Centurion Campus"])
    _add_user(db, "admin_dbn", "Durban Administrator", "campus_admin",
              "Admin@123", campus_ids["Durban Campus"])
    _add_user(db, "admin_pta", "Pretoria Administrator", "campus_admin",
              "Admin@123", campus_ids["Pretoria Campus"])
    lecturer_id = _add_user(db, "lecturer1", "Demo Lecturer", "lecturer", "Lecturer@123")

    # A handful of historical bookings so that reports are not empty on first run.
    today = datetime.now().date()
    demo = [  # (resource code, days ago, start, duration)
        ("CEN-LAB-01", 14, "09:00", 120), ("CEN-LAB-01", 7, "10:00", 60),
        ("CEN-PRJ-01", 5, "13:00", 45),   ("CEN-SEM-01", 3, "14:00", 90),
        ("DBN-LAB-01", 12, "08:00", 150), ("DBN-SEM-01", 9, "11:00", 120),
        ("DBN-SEM-01", 2, "09:30", 60),   ("DBN-PRJ-01", 6, "15:00", 30),
        ("PTA-LAB-01", 10, "09:00", 60),  ("PTA-LAB-01", 4, "11:00", 45),
        ("PTA-PRJ-01", 8, "12:00", 60),   ("PTA-SEM-01", 1, "10:00", 90),
    ]
    rid_to_campus = {resource_ids[c[0]]: campus_ids[c[4]] for c in SEED_RESOURCES}
    for code, days_ago, start, dur in demo:
        rid = resource_ids[code]
        d = (today - timedelta(days=days_ago)).isoformat()
        sh, sm = map(int, start.split(":"))
        end_total = sh * 60 + sm + dur
        end = f"{end_total // 60:02d}:{end_total % 60:02d}"
        db.execute(
            "INSERT INTO bookings (resource_id, lecturer_id, campus_id, booking_date, "
            "start_time, end_time, duration_minutes, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,'active',?)",
            (rid, lecturer_id, rid_to_campus[rid], d, start, end, dur,
             datetime.now().isoformat(timespec="seconds")))
