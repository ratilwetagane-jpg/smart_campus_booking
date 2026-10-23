"""
main.py - Entry point for the Smart Campus Resource Booking System.

Run with:   python main.py
"""
import sys

try:
    import tkinter  # noqa: F401
except ImportError:  # pragma: no cover
    sys.exit("Tkinter is not installed. On Linux run: sudo apt install python3-tk")

from database import Database, seed_defaults
from gui import App


def main():
    db = Database()          # creates campus_booking.db next to the program on first run
    seed_defaults(db)        # adds campuses, resources and default accounts only if empty
    App(db).mainloop()


if __name__ == "__main__":
    main()
