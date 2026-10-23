"""
test_system.py - Automated tests for the non-GUI logic.  Run:  python test_system.py
Uses a temporary database so your real data is never touched.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from database import Database, seed_defaults
from services import (AuthService, BookingService, CampusService, ReportService,
                      ResourceService, ValidationError, PermissionDenied)
from booking_rules import register_policy, BookingPolicy, MaxDurationRule


def next_weekday(days_ahead=2):
    d = datetime.now() + timedelta(days=days_ahead)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.strftime("%Y-%m-%d")


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "t.db")
        self.db = Database(self.path)
        seed_defaults(self.db)
        self.auth = AuthService(self.db)
        self.campuses = CampusService(self.db)
        self.resources = ResourceService(self.db)
        self.bookings = BookingService(self.db, self.campuses, self.resources)
        self.reports = ReportService(self.db, self.campuses, self.resources)
        self.cmap = {c.name: c.id for c in self.campuses.all_campuses().values()}
        self.lect = self.auth.login("lecturer1", "Lecturer@123")
        self.admin = self.auth.login("admin_cen", "Admin@123")
        self.op = self.auth.login("operator", "Operator@123")
        self.cen = self.cmap["Centurion Campus"]
        self.dbn = self.cmap["Durban Campus"]
        self.pta = self.cmap["Pretoria Campus"]
        self.lab = self.resources.list_for_campus(self.cen)[0]

    def tearDown(self):
        self.db.close()

    # --- authentication ---------------------------------------------------
    def test_login_and_roles(self):
        self.assertEqual(self.lect.role, "lecturer")
        self.assertEqual(self.admin.role, "campus_admin")
        self.assertEqual(self.op.role, "operator")
        self.assertTrue(self.lect.can("book_resource"))
        self.assertFalse(self.admin.can("book_resource"))
        self.assertTrue(self.op.can("compare_campuses"))

    def test_bad_login(self):
        with self.assertRaises(ValidationError):
            self.auth.login("lecturer1", "wrong")
        with self.assertRaises(ValidationError):
            self.auth.login("nobody", "Lecturer@123")

    def test_register(self):
        self.auth.register_lecturer("newlect", "New Lecturer", "Passw0rdX", "Passw0rdX")
        self.assertEqual(self.auth.login("newlect", "Passw0rdX").role, "lecturer")
        with self.assertRaises(ValidationError):
            self.auth.register_lecturer("newlect", "Dup", "Passw0rdX", "Passw0rdX")
        with self.assertRaises(ValidationError):
            self.auth.register_lecturer("abc", "Weak", "short", "short")
        with self.assertRaises(ValidationError):
            self.auth.register_lecturer("abc", "Mismatch", "Passw0rdX", "Other1234")

    def test_passwords_not_stored_in_plain_text(self):
        row = self.db.query_one("SELECT password_hash FROM users WHERE username='lecturer1'")
        self.assertNotIn("Lecturer@123", row["password_hash"])

    # --- resources --------------------------------------------------------
    def test_duplicate_resources_rejected(self):
        with self.assertRaises(ValidationError):
            self.resources.add(self.admin, self.cen, "cen-lab-01", "Other Name",
                               "Seminar Room", 10)
        with self.assertRaises(ValidationError):
            self.resources.add(self.admin, self.cen, "CEN-NEW-01", "Computer Lab A",
                               "Computer Laboratory", 10)
        rid = self.resources.add(self.admin, self.cen, "CEN-NEW-01", "New Room",
                                 "Seminar Room", 12)
        self.assertIsNotNone(self.resources.get(rid))

    def test_admin_scope(self):
        with self.assertRaises(PermissionDenied):
            self.resources.add(self.admin, self.dbn, "DBN-X-01", "X Room", "Seminar Room", 5)
        with self.assertRaises(PermissionDenied):
            self.resources.add(self.lect, self.cen, "CEN-X-01", "X Room", "Seminar Room", 5)

    def test_update_and_remove(self):
        rid = self.resources.add(self.admin, self.cen, "CEN-TMP-01", "Temp Room", "Seminar Room", 5)
        self.resources.update(self.admin, rid, "CEN-TMP-01", "Temp Room 2", "Seminar Room", 8)
        self.assertEqual(self.resources.get(rid).name, "Temp Room 2")
        self.resources.remove(self.admin, rid)
        self.assertNotIn(rid, [r.id for r in self.resources.list_for_campus(self.cen)])
        # code can be re-used after removal
        self.resources.add(self.admin, self.cen, "CEN-TMP-01", "Temp Room", "Seminar Room", 5)

    def test_cannot_remove_resource_with_future_booking(self):
        self.bookings.create_booking(self.lect, self.cen, self.lab.id, next_weekday(), "10:00", 60)
        with self.assertRaises(ValidationError):
            self.resources.remove(self.admin, self.lab.id)

    # --- bookings ---------------------------------------------------------
    def test_create_booking_and_history(self):
        bid = self.bookings.create_booking(self.lect, self.cen, self.lab.id,
                                           next_weekday(), "10:00", 90)
        active, history = self.bookings.lecturer_bookings(self.lect)
        self.assertIn(bid, [b.id for b in active])
        self.assertTrue(len(history) >= 1)  # seeded past bookings
        b = [b for b in active if b.id == bid][0]
        self.assertEqual((b.start_time, b.end_time, b.duration), ("10:00", "11:30", 90))

    def test_overlap_prevented(self):
        d = next_weekday()
        self.bookings.create_booking(self.lect, self.cen, self.lab.id, d, "10:00", 60)
        for start, dur in [("10:00", 30), ("10:30", 60), ("09:30", 60), ("09:00", 120)]:
            with self.assertRaises(ValidationError, msg=f"{start}+{dur}"):
                self.bookings.create_booking(self.lect, self.cen, self.lab.id, d, start, dur)
        # back-to-back is fine
        self.bookings.create_booking(self.lect, self.cen, self.lab.id, d, "11:00", 60)
        self.bookings.create_booking(self.lect, self.cen, self.lab.id, d, "09:00", 60)

    def test_cancel_then_rebook(self):
        d = next_weekday()
        bid = self.bookings.create_booking(self.lect, self.cen, self.lab.id, d, "14:00", 60)
        self.bookings.cancel_booking(self.lect, bid)
        with self.assertRaises(ValidationError):
            self.bookings.cancel_booking(self.lect, bid)
        self.bookings.create_booking(self.lect, self.cen, self.lab.id, d, "14:00", 60)

    def test_cannot_cancel_past_or_others(self):
        other = self.auth.register_lecturer("other1", "Other One", "Passw0rdX", "Passw0rdX")
        other_user = self.auth.login("other1", "Passw0rdX")
        bid = self.bookings.create_booking(self.lect, self.cen, self.lab.id,
                                           next_weekday(), "15:00", 30)
        with self.assertRaises(PermissionDenied):
            self.bookings.cancel_booking(other_user, bid)
        past = self.db.query_one("SELECT id FROM bookings WHERE booking_date < ? LIMIT 1",
                                 (datetime.now().strftime("%Y-%m-%d"),))["id"]
        with self.assertRaises(ValidationError):
            self.bookings.cancel_booking(self.lect, past)

    def test_input_validation(self):
        bad = [("2026-13-40", "10:00", 60), (next_weekday(), "25:99", 60),
               (next_weekday(), "10:00", "abc"), (next_weekday(), "10:00", 0),
               ("2020-01-01", "10:00", 60)]
        for d, t, dur in bad:
            with self.assertRaises(ValidationError, msg=str((d, t, dur))):
                self.bookings.create_booking(self.lect, self.cen, self.lab.id, d, t, dur)

    def test_resource_must_match_campus(self):
        dbn_res = self.resources.list_for_campus(self.dbn)[0]
        with self.assertRaises(ValidationError):
            self.bookings.create_booking(self.lect, self.cen, dbn_res.id, next_weekday(), "10:00", 30)

    def test_admin_cannot_book(self):
        with self.assertRaises(PermissionDenied):
            self.bookings.create_booking(self.admin, self.cen, self.lab.id, next_weekday(), "10:00", 30)

    # --- campus-specific policies ----------------------------------------
    def test_policies_differ_by_campus(self):
        d = next_weekday()
        # Centurion max 120
        with self.assertRaises(ValidationError):
            self.bookings.create_booking(self.lect, self.cen, self.lab.id, d, "09:00", 121)
        # Durban allows 180 but only 08:00-17:00
        dbn_sem = [r for r in self.resources.list_for_campus(self.dbn) if "Seminar" in r.type][0]
        self.bookings.create_booking(self.lect, self.dbn, dbn_sem.id, d, "09:00", 180)
        with self.assertRaises(ValidationError):
            self.bookings.create_booking(self.lect, self.dbn, dbn_sem.id, d, "16:30", 60)
        # Durban no weekends
        d_dt = datetime.now() + timedelta(days=1)
        while d_dt.weekday() != 5:
            d_dt += timedelta(days=1)
        with self.assertRaises(ValidationError):
            self.bookings.create_booking(self.lect, self.dbn, dbn_sem.id,
                                         d_dt.strftime("%Y-%m-%d"), "09:00", 60)
        # Pretoria labs capped at 60 (priority rule) though max is 90
        pta_lab = [r for r in self.resources.list_for_campus(self.pta) if "Computer" in r.type][0]
        with self.assertRaises(ValidationError):
            self.bookings.create_booking(self.lect, self.pta, pta_lab.id, d, "09:00", 75)
        self.bookings.create_booking(self.lect, self.pta, pta_lab.id, d, "09:00", 60)

    def test_max_active_bookings_rule(self):
        pta_prj = [r for r in self.resources.list_for_campus(self.pta) if "Projector" in r.type][0]
        d = next_weekday()
        for i in range(3):
            self.bookings.create_booking(self.lect, self.pta, pta_prj.id, d, f"{9+i}:00".zfill(5), 30)
        with self.assertRaises(ValidationError):
            self.bookings.create_booking(self.lect, self.pta, pta_prj.id, d, "14:00", 30)

    def test_new_policy_can_be_added_without_code_changes(self):
        register_policy("test_policy", lambda: BookingPolicy("Test", [MaxDurationRule(30)]))
        cid = self.campuses.add_campus(self.op, "Cape Town Campus", "test_policy")
        rid = self.resources.add(  # operators cannot manage resources; make an admin
            self._make_admin(cid), cid, "CPT-ROOM-1", "Room 1", "Seminar Room", 10)
        with self.assertRaises(ValidationError):
            self.bookings.create_booking(self.lect, cid, rid, next_weekday(), "10:00", 31)
        self.bookings.create_booking(self.lect, cid, rid, next_weekday(), "10:00", 30)

    def _make_admin(self, cid):
        from database import hash_password
        h, s = hash_password("Admin@123")
        self.db.execute("INSERT INTO users (username, full_name, role, password_hash, salt, campus_id)"
                        " VALUES ('cptadmin','CPT Admin','campus_admin',?,?,?)", (h, s, cid))
        return self.auth.login("cptadmin", "Admin@123")

    # --- availability -----------------------------------------------------
    def test_availability(self):
        now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        today = now.strftime("%Y-%m-%d")
        self.db.execute(
            "INSERT INTO bookings (resource_id, lecturer_id, campus_id, booking_date, start_time,"
            " end_time, duration_minutes, status, created_at) VALUES (?,?,?,?,?,?,?,'active','x')",
            (self.lab.id, self.lect.id, self.cen, today, "11:30", "12:30", 60))
        avail = {a["resource"].id: a for a in self.resources.availability(self.cen, now=now)}
        self.assertEqual(avail[self.lab.id]["status"], "In use")
        other = [r for r in avail if r != self.lab.id][0]
        self.assertEqual(avail[other]["status"], "Available")
        slot = self.resources.availability(self.cen, now=now, slot=(today, "12:00", "13:00"))
        self.assertFalse([a for a in slot if a["resource"].id == self.lab.id][0]["slot_free"])

    # --- reports ----------------------------------------------------------
    def test_reports(self):
        rep = self.reports.campus_report(self.admin, self.cen)
        self.assertEqual(rep["total_bookings"], 4)
        self.assertEqual(rep["most_used"][0][0], "Computer Lab A")
        self.assertAlmostEqual(rep["avg_duration"], (120 + 60 + 45 + 90) / 4, places=1)
        with self.assertRaises(PermissionDenied):
            self.reports.campus_report(self.admin, self.dbn)
        cmp_ = self.reports.compare_campuses(self.op)
        self.assertEqual(len(cmp_["rows"]), 3)
        self.assertTrue(cmp_["insights"])
        with self.assertRaises(PermissionDenied):
            self.reports.compare_campuses(self.admin)

    # --- persistence ------------------------------------------------------
    def test_persistence_between_runs(self):
        bid = self.bookings.create_booking(self.lect, self.cen, self.lab.id, next_weekday(), "13:00", 45)
        self.db.close()
        db2 = Database(self.path)          # simulates restarting the program
        seed_defaults(db2)                 # must not duplicate data
        self.assertEqual(db2.query_one("SELECT COUNT(*) n FROM campuses")["n"], 3)
        self.assertIsNotNone(db2.query_one("SELECT id FROM bookings WHERE id=?", (bid,)))
        self.db = db2


if __name__ == "__main__":
    unittest.main(verbosity=2)
