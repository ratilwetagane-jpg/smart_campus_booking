"""
services.py - Business logic (no GUI code here, so it can be tested on its own).

  AuthService      - registration and login
  CampusService    - campuses (dictionary of Campus objects)
  ResourceService  - resource registration, update, removal, availability
  BookingService   - creating / cancelling / listing bookings
  ReportService    - campus reports and cross-campus comparison
"""
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from booking_rules import BookingRequest, POLICY_REGISTRY
from database import hash_password
from models import Booking, Campus, Resource, user_from_row


class ValidationError(Exception):
    """Raised for any user-correctable problem; the message is shown in the GUI."""


class PermissionDenied(ValidationError):
    pass


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def parse_date(text):
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        raise ValidationError("Date must be in the format YYYY-MM-DD (e.g. 2026-11-05).")


def parse_time(text):
    try:
        return datetime.strptime(text.strip(), "%H:%M").time()
    except (ValueError, AttributeError):
        raise ValidationError("Time must be in 24-hour format HH:MM (e.g. 14:30).")


def parse_duration(value):
    try:
        minutes = int(str(value).strip())
    except ValueError:
        raise ValidationError("Duration must be a whole number of minutes.")
    if minutes <= 0:
        raise ValidationError("Duration must be greater than zero.")
    if minutes > 24 * 60:
        raise ValidationError("Duration cannot exceed 24 hours.")
    return minutes


def _fmt(minutes_total):
    return f"{minutes_total // 60:02d}:{minutes_total % 60:02d}"


# ---------------------------------------------------------------------------
class AuthService:
    USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{3,30}$")

    def __init__(self, db):
        self.db = db

    def register_lecturer(self, username, full_name, password, confirm):
        username, full_name = (username or "").strip(), (full_name or "").strip()
        if not self.USERNAME_RE.match(username):
            raise ValidationError("Username must be 3-30 characters (letters, digits, _ or .).")
        if len(full_name) < 2:
            raise ValidationError("Please enter your full name.")
        if len(password or "") < 8 or not re.search(r"[A-Za-z]", password) \
                or not re.search(r"\d", password):
            raise ValidationError("Password must be at least 8 characters and contain "
                                  "both letters and digits.")
        if password != confirm:
            raise ValidationError("Passwords do not match.")
        pw_hash, salt = hash_password(password)
        try:
            cur = self.db.execute(
                "INSERT INTO users (username, full_name, role, password_hash, salt) "
                "VALUES (?,?,'lecturer',?,?)", (username, full_name, pw_hash, salt))
        except sqlite3.IntegrityError:
            raise ValidationError("That username is already taken.")
        return cur.lastrowid

    def login(self, username, password):
        row = self.db.query_one("SELECT * FROM users WHERE username = ?",
                                ((username or "").strip(),))
        if row is None or not password:
            raise ValidationError("Invalid username or password.")
        candidate, _ = hash_password(password, row["salt"])
        if candidate != row["password_hash"]:
            raise ValidationError("Invalid username or password.")
        return user_from_row(row)


# ---------------------------------------------------------------------------
class CampusService:
    def __init__(self, db):
        self.db = db

    def all_campuses(self):
        """Return a dictionary {campus_id: Campus}."""
        return {r["id"]: Campus(r["id"], r["name"], r["policy_key"])
                for r in self.db.query("SELECT * FROM campuses ORDER BY name")}

    def get(self, campus_id):
        row = self.db.query_one("SELECT * FROM campuses WHERE id = ?", (campus_id,))
        if row is None:
            raise ValidationError("Campus not found.")
        return Campus(row["id"], row["name"], row["policy_key"])

    def campuses_for(self, user):
        campuses = self.all_campuses()
        return {cid: c for cid, c in campuses.items() if user.can_access_campus(cid)}

    def add_campus(self, user, name, policy_key):
        if not user.can("manage_campuses"):
            raise PermissionDenied("Only a system operator can add campuses.")
        name = (name or "").strip()
        if len(name) < 3:
            raise ValidationError("Campus name must be at least 3 characters.")
        if policy_key not in POLICY_REGISTRY:
            raise ValidationError("Please choose a valid booking policy.")
        try:
            cur = self.db.execute("INSERT INTO campuses (name, policy_key) VALUES (?,?)",
                                  (name, policy_key))
        except sqlite3.IntegrityError:
            raise ValidationError("A campus with that name already exists.")
        return cur.lastrowid


# ---------------------------------------------------------------------------
class ResourceService:
    RESOURCE_TYPES = ["Computer Laboratory", "Multimedia Projector", "Seminar Room",
                      "Presentation Equipment"]

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _to_resource(r):
        return Resource(r["id"], r["resource_code"], r["name"], r["type"], r["capacity"],
                        r["campus_id"], bool(r["active"]))

    def get(self, resource_id):
        row = self.db.query_one("SELECT * FROM resources WHERE id = ?", (resource_id,))
        return self._to_resource(row) if row else None

    def list_for_campus(self, campus_id, include_inactive=False):
        sql = "SELECT * FROM resources WHERE campus_id = ?"
        if not include_inactive:
            sql += " AND active = 1"
        return [self._to_resource(r) for r in self.db.query(sql + " ORDER BY name", (campus_id,))]

    # -- validation ---------------------------------------------------------
    def _validate_fields(self, code, name, rtype, capacity):
        code, name, rtype = (code or "").strip().upper(), (name or "").strip(), (rtype or "").strip()
        if not re.match(r"^[A-Z0-9][A-Z0-9_-]{2,19}$", code):
            raise ValidationError("Resource ID must be 3-20 characters (letters, digits, - or _).")
        if len(name) < 2:
            raise ValidationError("Please enter a resource name.")
        if not rtype:
            raise ValidationError("Please choose a resource type.")
        try:
            capacity = int(str(capacity).strip() or 0)
        except ValueError:
            raise ValidationError("Capacity must be a whole number (use 0 for equipment).")
        if capacity < 0:
            raise ValidationError("Capacity cannot be negative.")
        return code, name, rtype, capacity

    def _check_duplicates(self, code, name, campus_id, exclude_id=None):
        """Uses sets of existing codes / names to detect duplicate entries."""
        rows = self.db.query("SELECT id, resource_code, name, campus_id, active FROM resources")
        codes = {r["resource_code"].upper() for r in rows if r["id"] != exclude_id}
        names = {r["name"].lower() for r in rows
                 if r["active"] and r["campus_id"] == campus_id and r["id"] != exclude_id}
        if code in codes:
            raise ValidationError(f"Duplicate resource: ID '{code}' already exists.")
        if name.lower() in names:
            raise ValidationError(f"Duplicate resource: '{name}' already exists on this campus.")

    def add(self, user, campus_id, code, name, rtype, capacity):
        self._require_admin(user, campus_id)
        code, name, rtype, capacity = self._validate_fields(code, name, rtype, capacity)
        self._check_duplicates(code, name, campus_id)
        try:
            cur = self.db.execute(
                "INSERT INTO resources (resource_code, name, type, capacity, campus_id) "
                "VALUES (?,?,?,?,?)", (code, name, rtype, capacity, campus_id))
        except sqlite3.IntegrityError:
            raise ValidationError(f"Duplicate resource: ID '{code}' already exists.")
        return cur.lastrowid

    def update(self, user, resource_id, code, name, rtype, capacity):
        res = self.get(resource_id)
        if res is None or not res.active:
            raise ValidationError("Resource not found.")
        self._require_admin(user, res.campus_id)
        code, name, rtype, capacity = self._validate_fields(code, name, rtype, capacity)
        self._check_duplicates(code, name, res.campus_id, exclude_id=resource_id)
        self.db.execute("UPDATE resources SET resource_code=?, name=?, type=?, capacity=? "
                        "WHERE id=?", (code, name, rtype, capacity, resource_id))

    def remove(self, user, resource_id, now=None):
        res = self.get(resource_id)
        if res is None or not res.active:
            raise ValidationError("Resource not found.")
        self._require_admin(user, res.campus_id)
        now = now or datetime.now()
        future = self.db.query_one(
            "SELECT COUNT(*) AS n FROM bookings WHERE resource_id=? AND status='active' "
            "AND (booking_date || ' ' || end_time) > ?",
            (resource_id, now.strftime("%Y-%m-%d %H:%M")))["n"]
        if future:
            raise ValidationError(f"Cannot remove: {future} upcoming booking(s) exist for this "
                                  f"resource. Cancel them first.")
        # Soft delete keeps booking history intact for reporting. The code is renamed so
        # that it can be reused for a new resource later.
        self.db.execute("UPDATE resources SET active=0, resource_code = resource_code || '~' || id "
                        "WHERE id=?", (resource_id,))

    @staticmethod
    def _require_admin(user, campus_id):
        if not user.can("manage_resources"):
            raise PermissionDenied("You do not have permission to manage resources.")
        if user.campus_id != campus_id:
            raise PermissionDenied("You can only manage resources on your own campus.")

    # -- availability -------------------------------------------------------
    def availability(self, campus_id, now=None, slot=None):
        """
        Return one dict per resource:
          {'resource': Resource, 'status': 'Available'|'In use', 'detail': str,
           'slot_free': bool|None}
        `slot` = (date_str, start 'HH:MM', end 'HH:MM') also checks a chosen slot.
        """
        now = now or datetime.now()
        today, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
        result = []
        for res in self.list_for_campus(campus_id):
            current = self.db.query_one(
                "SELECT end_time FROM bookings WHERE resource_id=? AND status='active' "
                "AND booking_date=? AND start_time<=? AND end_time>? ", (res.id, today, hhmm, hhmm))
            if current:
                status, detail = "In use", f"Free from {current['end_time']}"
            else:
                nxt = self.db.query_one(
                    "SELECT start_time FROM bookings WHERE resource_id=? AND status='active' "
                    "AND booking_date=? AND start_time>? ORDER BY start_time LIMIT 1",
                    (res.id, today, hhmm))
                status = "Available"
                detail = f"Next booking today at {nxt['start_time']}" if nxt else "Free for the rest of today"
            slot_free = None
            if slot:
                slot_free = not self._overlaps(res.id, *slot)
            result.append({"resource": res, "status": status, "detail": detail,
                           "slot_free": slot_free})
        return result

    def _overlaps(self, resource_id, date_str, start, end):
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM bookings WHERE resource_id=? AND status='active' "
            "AND booking_date=? AND start_time < ? AND end_time > ?",
            (resource_id, date_str, end, start))
        return row["n"] > 0


# ---------------------------------------------------------------------------
class BookingService:
    SELECT = """
        SELECT b.*, r.name AS resource_name, u.full_name AS lecturer_name, c.name AS campus_name
        FROM bookings b
        JOIN resources r ON r.id = b.resource_id
        JOIN users u ON u.id = b.lecturer_id
        JOIN campuses c ON c.id = b.campus_id
    """

    def __init__(self, db, campus_service, resource_service):
        self.db = db
        self.campuses = campus_service
        self.resources = resource_service

    @staticmethod
    def _to_booking(r):
        return Booking(r["id"], r["resource_id"], r["resource_name"], r["lecturer_id"],
                       r["lecturer_name"], r["campus_id"], r["campus_name"], r["booking_date"],
                       r["start_time"], r["end_time"], r["duration_minutes"], r["status"])

    def _fetch(self, where="", params=(), order="b.booking_date, b.start_time"):
        sql = self.SELECT + (f" WHERE {where}" if where else "") + f" ORDER BY {order}"
        return [self._to_booking(r) for r in self.db.query(sql, params)]

    # -- create -------------------------------------------------------------
    def create_booking(self, user, campus_id, resource_id, date_str, time_str, duration,
                       now=None):
        if not user.can("book_resource"):
            raise PermissionDenied("Only lecturers can create bookings.")
        now = now or datetime.now()
        campus = self.campuses.get(campus_id)
        resource = self.resources.get(resource_id)
        if resource is None or not resource.active:
            raise ValidationError("Please select a resource first.")
        if resource.campus_id != campus_id:
            raise ValidationError("That resource does not belong to the selected campus.")

        day, tm = parse_date(date_str), parse_time(time_str)
        minutes = parse_duration(duration)
        start = datetime.combine(day, tm)
        start_min = tm.hour * 60 + tm.minute
        if start < now:
            raise ValidationError("Bookings must start in the future.")
        if start_min + minutes > 24 * 60:
            raise ValidationError("A booking cannot run past midnight.")

        active_count = self.db.query_one(
            "SELECT COUNT(*) AS n FROM bookings WHERE lecturer_id=? AND campus_id=? "
            "AND status='active' AND (booking_date || ' ' || end_time) > ?",
            (user.id, campus_id, now.strftime("%Y-%m-%d %H:%M")))["n"]
        request = BookingRequest(resource.type, start, minutes, now, active_count)
        problems = campus.policy.validate(request)
        if problems:
            raise ValidationError("\n".join(problems))

        end_str = _fmt(start_min + minutes)
        start_str = _fmt(start_min)
        with self.db.transaction():
            if self.resources._overlaps(resource_id, day.isoformat(), start_str, end_str):
                raise ValidationError("This resource is already booked during that time. "
                                      "Please choose another time.")
            cur = self.db.execute(
                "INSERT INTO bookings (resource_id, lecturer_id, campus_id, booking_date, "
                "start_time, end_time, duration_minutes, status, created_at) "
                "VALUES (?,?,?,?,?,?,?,'active',?)",
                (resource_id, user.id, campus_id, day.isoformat(), start_str, end_str, minutes,
                 now.isoformat(timespec="seconds")))
        return cur.lastrowid

    # -- cancel -------------------------------------------------------------
    def cancel_booking(self, user, booking_id, now=None):
        if not user.can("cancel_own_booking"):
            raise PermissionDenied("You do not have permission to cancel bookings.")
        now = now or datetime.now()
        rows = self._fetch("b.id = ?", (booking_id,))
        if not rows:
            raise ValidationError("Booking not found.")
        booking = rows[0]
        if booking.lecturer_id != user.id:
            raise PermissionDenied("You can only cancel your own bookings.")
        if booking.status == "cancelled":
            raise ValidationError("This booking is already cancelled.")
        if booking.start_dt <= now:
            raise ValidationError("Only future bookings can be cancelled.")
        self.db.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))

    # -- listings -----------------------------------------------------------
    def lecturer_bookings(self, user, now=None):
        """Return (active_bookings, history) for a lecturer, from the database."""
        if not user.can("view_own_bookings"):
            raise PermissionDenied("You do not have permission to view personal bookings.")
        now = now or datetime.now()
        mine = self._fetch("b.lecturer_id = ?", (user.id,))
        active = [b for b in mine if b.state(now) in ("Upcoming", "In progress")]
        history = [b for b in mine if b.state(now) in ("Completed", "Cancelled")]
        history.sort(key=lambda b: (b.date, b.start_time), reverse=True)
        return active, history

    def campus_bookings(self, user, campus_id):
        if not user.can("view_campus_bookings"):
            raise PermissionDenied("You do not have permission to view campus bookings.")
        if not user.can_access_campus(campus_id):
            raise PermissionDenied("You can only view bookings for your own campus.")
        return self._fetch("b.campus_id = ?", (campus_id,),
                           order="b.booking_date DESC, b.start_time DESC")

    def all_bookings(self, user):
        if not user.can("view_all_campuses"):
            raise PermissionDenied("Only a system operator can view all campuses.")
        return self._fetch(order="b.booking_date DESC, b.start_time DESC")


# ---------------------------------------------------------------------------
class ReportService:
    WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    def __init__(self, db, campus_service, resource_service):
        self.db = db
        self.campuses = campus_service
        self.resources = resource_service

    def campus_report(self, user, campus_id):
        """Report for one campus: totals, most used resources, average duration, trends."""
        if not user.can("view_campus_reports"):
            raise PermissionDenied("You do not have permission to view reports.")
        if not user.can_access_campus(campus_id):
            raise PermissionDenied("You can only view reports for your own campus.")
        campus = self.campuses.get(campus_id)
        rows = self.db.query(
            "SELECT b.*, r.name AS resource_name FROM bookings b "
            "JOIN resources r ON r.id = b.resource_id WHERE b.campus_id = ?", (campus_id,))
        active = [r for r in rows if r["status"] == "active"]
        cancelled = len(rows) - len(active)

        per_resource = Counter(r["resource_name"] for r in active)          # name -> count
        minutes_by_res = defaultdict(int)                                    # name -> minutes
        weekday, hour = Counter(), Counter()
        for r in active:
            minutes_by_res[r["resource_name"]] += r["duration_minutes"]
            d = datetime.strptime(r["booking_date"], "%Y-%m-%d")
            weekday[self.WEEKDAYS[d.weekday()]] += 1
            hour[int(r["start_time"][:2])] += 1
        total_minutes = sum(r["duration_minutes"] for r in active)
        return {
            "campus": campus,
            "policy": campus.policy.describe(),
            "total_bookings": len(active),
            "cancelled_bookings": cancelled,
            "avg_duration": round(total_minutes / len(active), 1) if active else 0.0,
            "total_hours": round(total_minutes / 60, 1),
            "most_used": per_resource.most_common(5),
            "minutes_by_resource": dict(minutes_by_res),
            "by_weekday": {d: weekday.get(d, 0) for d in self.WEEKDAYS},
            "by_hour": dict(sorted(hour.items())),
            "resource_count": len(self.resources.list_for_campus(campus_id)),
        }

    def compare_campuses(self, user):
        """Cross-campus comparison table plus plain-language insights."""
        if not user.can("compare_campuses"):
            raise PermissionDenied("Only a system operator can compare campuses.")
        rows = []
        for cid, campus in self.campuses.all_campuses().items():
            rep = self.campus_report(user, cid)
            denom = rep["total_bookings"] + rep["cancelled_bookings"]
            rows.append({
                "campus": campus.name,
                "policy": rep["policy"],
                "resources": rep["resource_count"],
                "bookings": rep["total_bookings"],
                "bookings_per_resource": round(rep["total_bookings"] / rep["resource_count"], 2)
                if rep["resource_count"] else 0.0,
                "avg_duration": rep["avg_duration"],
                "total_hours": rep["total_hours"],
                "cancel_rate": round(100 * rep["cancelled_bookings"] / denom, 1) if denom else 0.0,
                "top_resource": rep["most_used"][0][0] if rep["most_used"] else "-",
            })
        insights = []
        if rows and any(r["bookings"] for r in rows):
            busiest = max(rows, key=lambda r: r["bookings"])
            longest = max(rows, key=lambda r: r["avg_duration"])
            densest = max(rows, key=lambda r: r["bookings_per_resource"])
            insights.append(f"Most bookings: {busiest['campus']} ({busiest['bookings']}).")
            insights.append(f"Longest average session: {longest['campus']} "
                            f"({longest['avg_duration']} min) - compare with its maximum-duration rule.")
            insights.append(f"Highest resource usage per resource: {densest['campus']} "
                            f"({densest['bookings_per_resource']} bookings each).")
            strict = [r for r in rows if r["cancel_rate"] > 0]
            if strict:
                hi = max(strict, key=lambda r: r["cancel_rate"])
                insights.append(f"Highest cancellation rate: {hi['campus']} ({hi['cancel_rate']}%).")
        else:
            insights.append("No bookings recorded yet - trends will appear once bookings exist.")
        return {"rows": rows, "insights": insights}
