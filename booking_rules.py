"""
booking_rules.py - Campus-specific booking policies, kept separate from core logic.

Design (Section 5.2 - Design for Future Expansion):
  * Every rule is a small class that inherits from BookingRule and implements
    check() and describe().
  * A BookingPolicy is just a named list of rules.
  * POLICY_REGISTRY maps a policy key (stored in the campuses table) to a factory
    function.  To add a new campus rule set you only call register_policy(...);
    no existing code needs to change.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class BookingRequest:
    """All the information a rule may need to judge a booking request."""
    resource_type: str
    start: datetime
    duration_minutes: int
    now: datetime
    active_bookings_for_user: int = 0

    @property
    def end(self):
        return self.start + timedelta(minutes=self.duration_minutes)


def _hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class BookingRule(ABC):
    """Base class for every booking rule."""

    @abstractmethod
    def check(self, request):
        """Return an error message (str) if the request breaks the rule, else None."""

    @abstractmethod
    def describe(self):
        """Return a human-readable description of the rule."""


class MaxDurationRule(BookingRule):
    def __init__(self, max_minutes):
        self.max_minutes = max_minutes

    def check(self, req):
        if req.duration_minutes > self.max_minutes:
            return (f"Maximum booking duration on this campus is "
                    f"{self.max_minutes} minutes per session.")

    def describe(self):
        return f"Max {self.max_minutes} min per session"


class OperatingHoursRule(BookingRule):
    """Restricted booking hours: the whole session must fit between open and close."""

    def __init__(self, open_time, close_time):
        self.open_time, self.close_time = open_time, close_time

    def check(self, req):
        start_min = req.start.hour * 60 + req.start.minute
        end_min = start_min + req.duration_minutes
        if start_min < _to_minutes(self.open_time) or end_min > _to_minutes(self.close_time):
            return (f"Bookings must fall between {self.open_time} and "
                    f"{self.close_time} on this campus.")

    def describe(self):
        return f"Bookable {self.open_time}-{self.close_time}"


class WeekdaysOnlyRule(BookingRule):
    def check(self, req):
        if req.start.weekday() >= 5:
            return "This campus does not accept weekend bookings."

    def describe(self):
        return "Weekdays only"


class AdvanceWindowRule(BookingRule):
    """Bookings may only be made up to N days ahead."""

    def __init__(self, max_days):
        self.max_days = max_days

    def check(self, req):
        if req.start.date() > (req.now + timedelta(days=self.max_days)).date():
            return f"Bookings may only be made up to {self.max_days} days in advance."

    def describe(self):
        return f"Book up to {self.max_days} days ahead"


class MaxActiveBookingsRule(BookingRule):
    """Limits how many upcoming bookings one lecturer may hold at a time."""

    def __init__(self, limit):
        self.limit = limit

    def check(self, req):
        if req.active_bookings_for_user >= self.limit:
            return (f"You already hold {self.limit} upcoming bookings, the maximum on "
                    f"this campus. Cancel one first.")

    def describe(self):
        return f"Max {self.limit} upcoming bookings per lecturer"


class PriorityResourceRule(BookingRule):
    """Priority-access rule: high-demand resource types get a shorter session cap
    so that more lecturers can use them."""

    def __init__(self, caps):
        self.caps = dict(caps)  # {resource type: max minutes}

    def check(self, req):
        cap = self.caps.get(req.resource_type)
        if cap is not None and req.duration_minutes > cap:
            return (f"{req.resource_type} is a high-demand resource: sessions are "
                    f"limited to {cap} minutes on this campus.")

    def describe(self):
        return "; ".join(f"{t} capped at {m} min" for t, m in self.caps.items())


class BookingPolicy:
    """A named collection of rules applied automatically for a campus."""

    def __init__(self, name, rules):
        self.name = name
        self.rules = list(rules)

    def validate(self, request):
        """Return a list of rule violations (empty list = request allowed)."""
        return [msg for msg in (r.check(request) for r in self.rules) if msg]

    def describe(self):
        return f"{self.name}: " + " | ".join(r.describe() for r in self.rules)

    def rule_descriptions(self):
        return [r.describe() for r in self.rules]


# ---------------------------------------------------------------------------
# Registry - add new campus policies here (or at runtime via register_policy)
# ---------------------------------------------------------------------------
POLICY_REGISTRY = {}


def register_policy(key, factory):
    """Register a policy factory (a function returning a BookingPolicy)."""
    POLICY_REGISTRY[key] = factory


def get_policy(key):
    if key not in POLICY_REGISTRY:
        raise KeyError(f"Unknown booking policy '{key}'")
    return POLICY_REGISTRY[key]()


register_policy("centurion", lambda: BookingPolicy("Centurion Policy", [
    MaxDurationRule(120),
    OperatingHoursRule("07:00", "16:00"),
    MaxActiveBookingsRule(5),
]))

register_policy("durban", lambda: BookingPolicy("Durban Policy", [
    MaxDurationRule(180),
    OperatingHoursRule("08:00", "17:00"),
    WeekdaysOnlyRule(),
    AdvanceWindowRule(30),
]))

register_policy("pretoria", lambda: BookingPolicy("Pretoria Policy", [
    MaxDurationRule(90),
    OperatingHoursRule("08:00", "18:00"),
    PriorityResourceRule({"Computer Laboratory": 60}),
    AdvanceWindowRule(14),
    MaxActiveBookingsRule(3),
]))

# Example of future expansion - uncomment to add a rule set for a new campus:
# register_policy("cape_town", lambda: BookingPolicy("Cape Town Policy", [
#     MaxDurationRule(240), OperatingHoursRule("08:00", "19:00")]))
