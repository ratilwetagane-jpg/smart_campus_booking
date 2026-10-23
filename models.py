"""
models.py - Object-oriented domain model.

  * User is the base class (encapsulation: private attributes + read-only properties).
  * Lecturer, CampusAdministrator and SystemOperator inherit from User and declare
    their own permissions (role-based access control).
  * Campus, Resource and Booking are plain data objects.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from booking_rules import get_policy


class User:
    ROLE = "user"
    ROLE_LABEL = "User"
    PERMISSIONS = frozenset()

    def __init__(self, user_id, username, full_name, campus_id=None):
        self.__id = user_id
        self.__username = username
        self.__full_name = full_name
        self.__campus_id = campus_id

    # --- encapsulated, read-only access -----------------------------------
    @property
    def id(self):
        return self.__id

    @property
    def username(self):
        return self.__username

    @property
    def full_name(self):
        return self.__full_name

    @property
    def campus_id(self):
        return self.__campus_id

    @property
    def role(self):
        return self.ROLE

    @property
    def role_label(self):
        return self.ROLE_LABEL

    def can(self, permission):
        """Role-based access control check."""
        return permission in self.PERMISSIONS

    def can_access_campus(self, campus_id):
        """Default: only a user's own campus. Overridden by roles with wider reach."""
        return self.__campus_id == campus_id

    def __repr__(self):
        return f"<{type(self).__name__} {self.username}>"


class Lecturer(User):
    ROLE = "lecturer"
    ROLE_LABEL = "Lecturer"
    PERMISSIONS = frozenset({"book_resource", "view_own_bookings", "cancel_own_booking",
                             "view_availability"})

    def can_access_campus(self, campus_id):
        return True  # lecturers may select any campus to book at


class CampusAdministrator(User):
    ROLE = "campus_admin"
    ROLE_LABEL = "Campus Administrator"
    PERMISSIONS = frozenset({"manage_resources", "view_campus_bookings",
                             "view_campus_reports", "view_availability"})


class SystemOperator(User):
    ROLE = "operator"
    ROLE_LABEL = "System Operator"
    PERMISSIONS = frozenset({"view_all_campuses", "view_campus_bookings",
                             "view_campus_reports", "compare_campuses",
                             "manage_campuses", "view_availability"})

    def can_access_campus(self, campus_id):
        return True


ROLE_CLASSES = {c.ROLE: c for c in (Lecturer, CampusAdministrator, SystemOperator)}


def user_from_row(row):
    cls = ROLE_CLASSES[row["role"]]
    return cls(row["id"], row["username"], row["full_name"], row["campus_id"])


class Campus:
    def __init__(self, campus_id, name, policy_key):
        self.id = campus_id
        self.name = name
        self.policy_key = policy_key

    @property
    def policy(self):
        return get_policy(self.policy_key)

    def __str__(self):
        return self.name


@dataclass
class Resource:
    id: int
    code: str
    name: str
    type: str
    capacity: int
    campus_id: int
    active: bool = True


@dataclass
class Booking:
    id: int
    resource_id: int
    resource_name: str
    lecturer_id: int
    lecturer_name: str
    campus_id: int
    campus_name: str
    date: str
    start_time: str
    end_time: str
    duration: int
    status: str

    @property
    def start_dt(self):
        return datetime.strptime(f"{self.date} {self.start_time}", "%Y-%m-%d %H:%M")

    @property
    def end_dt(self):
        h, m = map(int, self.end_time.split(":"))
        base = datetime.strptime(self.date, "%Y-%m-%d")
        return base + timedelta(hours=h, minutes=m)

    def state(self, now=None):
        """'Cancelled', 'Upcoming', 'In progress' or 'Completed'."""
        now = now or datetime.now()
        if self.status == "cancelled":
            return "Cancelled"
        if self.start_dt > now:
            return "Upcoming"
        if self.end_dt > now:
            return "In progress"
        return "Completed"
