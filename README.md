# Smart Campus Resource Booking System (Programming 512)

Python 3.9+ application using **Tkinter** (GUI) and **SQLite** (persistence).
No third-party packages are needed - only the standard library.


## Screenshots
## Screenshots
| Login | Campus booking |
|---|---|
| ![Login](screenshots/login.png) | ![Campus booking](screenshots/campus_booking.png) |

| Lecturer: campus | Lecturer: booking saved |
|---|---|
| ![Lecturer campus](screenshots/lecturer_campus.png) | ![Booking saved](screenshots/booking_saved.png) |

| Admin: manage resources | Admin: usage and report |
|---|---|
| ![Admin manage resources](screenshots/admin_manage_resources.png) | ![Admin usageandreport](screenshots/admin_usageandreport.png) |

| Operator | System operator report |
|---|---|
| ![Operator](screenshots/operator.png) | ![System op report](screenshots/system_op_report.png) |

| Admin dashboard | Lecturer register |
|---|---|
| ![Admin](screenshots/admin.png) | ![Lecturer register](screenshots/lecturer_register.png) |

## How to run
```
python main.py
```
(Linux only, if Tkinter is missing: `sudo apt install python3-tk`.)
The database file `campus_booking.db` is created automatically on first run and
all data is kept between runs. Delete that file to reset the system.

To run the automated tests (they use a temporary database):
```
python test_system.py
```

## Default accounts
| Role                  | Username   | Password       | Campus            |
|-----------------------|------------|----------------|-------------------|
| Lecturer (demo)       | lecturer1  | Lecturer@123   | any               |
| Campus Administrator  | admin_jhb  | Admin@123      | Centurion      |
| Campus Administrator  | admin_dbn  | Admin@123      | Durban            |
| Campus Administrator  | admin_pta  | Admin@123      | Pretoria          |
| System Operator       | operator   | Operator@123   | all campuses      |

New lecturers can register from the login screen. A few demo past bookings are
seeded so that the reports are not empty.

## Project structure
| File               | Purpose |
|--------------------|---------|
| `main.py`          | Entry point |
| `gui.py`           | All Tkinter screens (login, campus selection, three dashboards) |
| `services.py`      | Business logic: authentication, campuses, resources, bookings, reports |
| `models.py`        | OOP model: `User` -> `Lecturer`, `CampusAdministrator`, `SystemOperator`; `Campus`, `Resource`, `Booking` |
| `booking_rules.py` | Campus booking policies, separated from core logic (rule classes + registry) |
| `database.py`      | SQLite schema, helpers, first-run seed data |
| `test_system.py`   | 21 automated tests |

## Requirement coverage
* **Multiple campuses / data structures** - campuses are returned as a dictionary of `Campus` objects; resources and bookings as lists of objects; sets are used for duplicate detection; `Counter`/dict for reports.
* **OOP and RBAC** - inheritance (`User` subclasses), encapsulation (private attributes exposed through read-only properties), per-role `PERMISSIONS` checked with `can()`. Services re-check permissions, not just the GUI.
* **Lecturer** - register, log in, choose campus, see availability, book (date, time, duration), view active bookings, cancel future bookings, view past history.
* **Campus administrator** - add / update / remove resources, view all campus bookings, live availability, usage trends (charts by hour and weekday).
* **System operator** - sees all campuses, all bookings and resources, campus reports, cross-campus comparison with insights, and can add campuses.
* **Resource rules** - unique resource ID (database `UNIQUE` + set-based check), duplicate names on the same campus rejected, resources always belong to one campus.
* **Bookings** - store date, start time, duration, lecturer and campus; overlapping bookings for the same resource are rejected inside a database transaction.
* **Campus-specific policies** (3 campuses, all different), applied automatically and shown in the GUI header:
  * Centurion: max 120 min, 07:00-20:00, max 5 upcoming bookings per lecturer
  * Durban: max 180 min, 08:00-17:00, weekdays only, up to 30 days ahead
  * Pretoria: max 90 min (computer labs capped at 60 min - priority rule), 08:00-18:00, up to 14 days ahead, max 3 upcoming bookings
* **Future expansion** - to add a new rule set write one `register_policy(...)` call in `booking_rules.py` (a commented Cape Town example is included); then the operator can add the campus in the GUI. No other code changes are needed.
* **Reports** - per campus: total bookings, most used resources, average duration (plus hours, cancellations, trends); cross-campus comparison table, policy explanation and insights.
* **Persistence** - users (passwords salted and hashed with PBKDF2), campuses, resources and bookings are all stored in SQLite.
* **Validation & errors** - dates, times, durations, passwords, usernames, duplicates, permissions and policy violations all produce clear messages instead of crashes.
