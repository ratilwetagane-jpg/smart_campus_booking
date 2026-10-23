"""
gui.py - Tkinter graphical user interface.

Screens:  LoginFrame -> CampusSelectFrame -> LecturerDashboard / AdminDashboard /
OperatorDashboard.  All business rules live in services.py; this file only collects
input, calls the services and displays results (errors are shown in message boxes).
"""
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox, ttk

from booking_rules import POLICY_REGISTRY
from services import (AuthService, BookingService, CampusService, ReportService,
                      ResourceService, ValidationError)

BLUE, DARK, LIGHT, GREEN, RED = "#0057B8", "#12356F", "#EAF1FB", "#1B7F3B", "#B3261E"
REFRESH_MS = 30_000  # real-time availability refresh interval


# ---------------------------------------------------------------------------
# Small reusable helpers
# ---------------------------------------------------------------------------
def make_tree(parent, columns, height=10):
    """Create a scrollable ttk.Treeview. columns = [(id, heading, width), ...]"""
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height)
    for cid, heading, width in columns:
        tree.heading(cid, text=heading)
        tree.column(cid, width=width, anchor="w")
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    tree.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    tree.container = frame
    return tree


def fill_tree(tree, rows, tags=None):
    tree.delete(*tree.get_children())
    for i, row in enumerate(rows):
        tree.insert("", "end", iid=str(row[0]) if tags is None else None,
                    values=row[1:] if tags is None else row,
                    tags=(tags[i],) if tags else ())


def show_error(parent, exc):
    messagebox.showerror("Cannot complete request", str(exc), parent=parent)


# ---------------------------------------------------------------------------
class App(tk.Tk):
    """Root window: owns the services and swaps screens."""

    def __init__(self, db):
        super().__init__()
        self.title("Smart Campus Resource Booking System - Richfield")
        self.geometry("1100x790")
        self.minsize(980, 640)
        self.configure(bg=LIGHT)
        self.db = db
        self.auth = AuthService(db)
        self.campuses = CampusService(db)
        self.resources = ResourceService(db)
        self.bookings = BookingService(db, self.campuses, self.resources)
        self.reports = ReportService(db, self.campuses, self.resources)
        self.user = None
        self.campus = None
        self._setup_style()
        self.current = None
        self.show_login()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=LIGHT)
        style.configure("TLabel", background=LIGHT, font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground=DARK)
        style.configure("Sub.TLabel", font=("Segoe UI", 10, "italic"), foreground="#444")
        style.configure("TButton", font=("Segoe UI", 10), padding=6)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                        background=BLUE, foreground="white")
        style.map("Accent.TButton", background=[("active", DARK)])
        style.configure("TLabelframe", background=LIGHT)
        style.configure("TLabelframe.Label", background=LIGHT, font=("Segoe UI", 10, "bold"),
                        foreground=DARK)
        style.configure("Treeview", rowheight=24, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("TNotebook", background=LIGHT)
        style.configure("TNotebook.Tab", padding=(14, 6), font=("Segoe UI", 10, "bold"))

    # -- navigation ---------------------------------------------------------
    def _swap(self, frame):
        if self.current is not None:
            if hasattr(self.current, "stop"):
                self.current.stop()
            self.current.destroy()
        self.current = frame
        frame.pack(fill="both", expand=True)

    def show_login(self):
        self.user, self.campus = None, None
        self._swap(LoginFrame(self))

    def show_campus_select(self):
        self.campus = None
        self._swap(CampusSelectFrame(self))

    def show_dashboard(self, campus):
        self.campus = campus
        cls = {"lecturer": LecturerDashboard, "campus_admin": AdminDashboard,
               "operator": OperatorDashboard}[self.user.role]
        self._swap(cls(self))

    def _on_close(self):
        if self.current is not None and hasattr(self.current, "stop"):
            self.current.stop()
        self.db.close()
        self.destroy()


# ---------------------------------------------------------------------------
class LoginFrame(ttk.Frame):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        banner = tk.Frame(self, bg=DARK, height=90)
        banner.pack(fill="x")
        tk.Label(banner, text="Smart Campus Resource Booking System", bg=DARK, fg="white",
                 font=("Segoe UI", 20, "bold")).pack(pady=(18, 0))
        tk.Label(banner, text="Richfield Graduate Institution", bg=DARK, fg="#BBD3F5",
                 font=("Segoe UI", 11)).pack()

        box = ttk.LabelFrame(self, text=" Sign in ", padding=24)
        box.pack(pady=40)
        ttk.Label(box, text="Username").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Label(box, text="Password").grid(row=1, column=0, sticky="w", pady=6)
        self.username = ttk.Entry(box, width=32)
        self.password = ttk.Entry(box, width=32, show="*")
        self.username.grid(row=0, column=1, padx=10)
        self.password.grid(row=1, column=1, padx=10)
        ttk.Button(box, text="Log in", style="Accent.TButton",
                   command=self.login).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 4))
        ttk.Button(box, text="Register as a Lecturer",
                   command=self.open_register).grid(row=3, column=0, columnspan=2, sticky="ew")
        self.username.focus_set()
        for entry in (self.username, self.password):
            entry.bind("<Return>", lambda e: self.login())

        hint = ("Demo accounts:  lecturer1 / Lecturer@123   |   admin_cen / Admin@123   |   "
                "operator / Operator@123")
        ttk.Label(self, text=hint, style="Sub.TLabel").pack(side="bottom", pady=12)

    def login(self):
        try:
            user = self.app.auth.login(self.username.get(), self.password.get())
        except ValidationError as e:
            show_error(self, e)
            self.password.delete(0, "end")
            return
        self.app.user = user
        self.app.show_campus_select()

    def open_register(self):
        RegisterDialog(self.app, self.app.auth)


class RegisterDialog(tk.Toplevel):
    def __init__(self, app, auth):
        super().__init__(app)
        self.auth = auth
        self.title("Register - Lecturer")
        self.configure(bg=LIGHT)
        self.resizable(False, False)
        self.transient(app)
        frm = ttk.Frame(self, padding=20)
        frm.pack()
        ttk.Label(frm, text="Create a lecturer account", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, pady=(0, 12))
        self.fields = {}
        for i, (key, label, secret) in enumerate([
                ("full_name", "Full name", False), ("username", "Username", False),
                ("password", "Password", True), ("confirm", "Confirm password", True)], start=1):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=5)
            e = ttk.Entry(frm, width=30, show="*" if secret else "")
            e.grid(row=i, column=1, padx=8)
            self.fields[key] = e
        ttk.Label(frm, text="Password: 8+ characters, letters and digits.",
                  style="Sub.TLabel").grid(row=5, column=0, columnspan=2, pady=4)
        ttk.Button(frm, text="Register", style="Accent.TButton",
                   command=self.submit).grid(row=6, column=0, columnspan=2, sticky="ew", pady=8)
        self.fields["full_name"].focus_set()
        self.grab_set()

    def submit(self):
        try:
            self.auth.register_lecturer(self.fields["username"].get(), self.fields["full_name"].get(),
                                        self.fields["password"].get(), self.fields["confirm"].get())
        except ValidationError as e:
            show_error(self, e)
            return
        messagebox.showinfo("Registered", "Account created. You can now log in.", parent=self)
        self.destroy()


# ---------------------------------------------------------------------------
class CampusSelectFrame(ttk.Frame):
    """Section 4.1 - the user picks the campus to work with after logging in."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.options = app.campuses.campuses_for(app.user)  # dict {id: Campus}
        ttk.Label(self, text=f"Welcome, {app.user.full_name}", style="Title.TLabel").pack(pady=(40, 2))
        ttk.Label(self, text=f"Role: {app.user.role_label}", style="Sub.TLabel").pack()
        ttk.Label(self, text="Select a campus to work with:").pack(pady=(26, 8))

        self.listbox = tk.Listbox(self, height=max(3, len(self.options)), width=40,
                                  font=("Segoe UI", 12), exportselection=False,
                                  selectbackground=BLUE)
        self.ids = list(self.options)
        for cid in self.ids:
            self.listbox.insert("end", self.options[cid].name)
        self.listbox.pack()
        if self.ids:
            preferred = app.user.campus_id if app.user.campus_id in self.ids else self.ids[0]
            self.listbox.selection_set(self.ids.index(preferred))
        self.listbox.bind("<Double-Button-1>", lambda e: self.proceed())

        self.policy_var = tk.StringVar()
        ttk.Label(self, textvariable=self.policy_var, wraplength=700, justify="center",
                  style="Sub.TLabel").pack(pady=10)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.show_policy())
        self.show_policy()
        row = ttk.Frame(self)
        row.pack(pady=10)
        ttk.Button(row, text="Continue", style="Accent.TButton", command=self.proceed).pack(side="left", padx=6)
        ttk.Button(row, text="Log out", command=app.show_login).pack(side="left", padx=6)

    def selected(self):
        sel = self.listbox.curselection()
        return self.options[self.ids[sel[0]]] if sel else None

    def show_policy(self):
        c = self.selected()
        self.policy_var.set(f"Booking policy in effect - {c.policy.describe()}" if c else "")

    def proceed(self):
        c = self.selected()
        if c is None:
            messagebox.showwarning("Select a campus", "Please select a campus first.", parent=self)
            return
        self.app.show_dashboard(c)


# ---------------------------------------------------------------------------
class DashboardBase(ttk.Frame):
    """Header bar (user, active campus, active booking policy) + a Notebook of tabs."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._after_id = None
        head = tk.Frame(self, bg=DARK)
        head.pack(fill="x")
        left = tk.Frame(head, bg=DARK)
        left.pack(side="left", padx=14, pady=8)
        tk.Label(left, text=f"{app.user.full_name}  ({app.user.role_label})", bg=DARK, fg="white",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.campus_label = tk.Label(left, text=f"Active campus: {app.campus.name}", bg=DARK,
                                     fg="#FFD966", font=("Segoe UI", 11, "bold"))
        self.campus_label.pack(anchor="w")
        self.policy_label = tk.Label(left, text=f"Booking policy in effect - {app.campus.policy.describe()}",
                                     bg=DARK, fg="#BBD3F5", font=("Segoe UI", 9), wraplength=780,
                                     justify="left")
        self.policy_label.pack(anchor="w")
        right = tk.Frame(head, bg=DARK)
        right.pack(side="right", padx=14)
        ttk.Button(right, text="Switch campus", command=app.show_campus_select).pack(side="left", padx=4)
        ttk.Button(right, text="Log out", command=app.show_login).pack(side="left", padx=4)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=10)
        self.build_tabs()

    def build_tabs(self):  # implemented by subclasses
        raise NotImplementedError

    def schedule(self, func):
        """Call func every REFRESH_MS ms (real-time updates)."""
        def tick():
            try:
                func()
            finally:
                self._after_id = self.after(REFRESH_MS, tick)
        self._after_id = self.after(REFRESH_MS, tick)

    def stop(self):
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def tab(self, title):
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text=title)
        return frame


BOOKING_COLUMNS = [("id", "ID", 50), ("resource", "Resource", 190), ("campus", "Campus", 160),
                   ("date", "Date", 100), ("start", "Start", 70), ("end", "End", 70),
                   ("dur", "Minutes", 70), ("state", "Status", 100)]


def booking_rows(bookings, with_lecturer=False):
    rows = []
    for b in bookings:
        row = [b.id, b.id, b.resource_name, b.campus_name, b.date, b.start_time, b.end_time,
               b.duration, b.state()]
        if with_lecturer:
            row.append(b.lecturer_name)
        rows.append(tuple(row))
    return rows


# ---------------------------------------------------------------------------
class LecturerDashboard(DashboardBase):
    def build_tabs(self):
        self.build_book_tab(self.tab("Book a Resource"))
        self.build_mine_tab(self.tab("My Bookings"))
        self.schedule(self.refresh_availability)

    # -- booking tab --------------------------------------------------------
    def build_book_tab(self, tab):
        ttk.Label(tab, text="Resource availability (updates automatically every 30 s)",
                  style="Sub.TLabel").pack(anchor="w")
        self.avail_tree = make_tree(tab, [("code", "Resource ID", 110), ("name", "Name", 190),
                                          ("type", "Type", 170), ("cap", "Capacity", 70),
                                          ("status", "Now", 90), ("detail", "Details", 210),
                                          ("slot", "Chosen slot", 100)], height=9)
        self.avail_tree.container.pack(fill="both", expand=True, pady=6)
        self.avail_tree.tag_configure("free", foreground=GREEN)
        self.avail_tree.tag_configure("busy", foreground=RED)
        self.avail_tree.bind("<<TreeviewSelect>>", lambda e: self.update_selected_label())

        form = ttk.LabelFrame(tab, text=" New booking ", padding=12)
        form.pack(fill="x", pady=6)
        self.selected_var = tk.StringVar(value="Selected resource: (none - click a row above)")
        ttk.Label(form, textvariable=self.selected_var, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=8, sticky="w", pady=(0, 8))
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.date_var, self.time_var, self.dur_var = tk.StringVar(value=tomorrow), tk.StringVar(value="09:00"), tk.StringVar(value="60")
        for col, (label, var, w) in enumerate([("Date (YYYY-MM-DD)", self.date_var, 14),
                                               ("Start time (HH:MM)", self.time_var, 10),
                                               ("Duration (minutes)", self.dur_var, 10)]):
            ttk.Label(form, text=label).grid(row=1, column=col * 2, sticky="e", padx=(8, 4))
            ttk.Entry(form, textvariable=var, width=w).grid(row=1, column=col * 2 + 1)
        ttk.Button(form, text="Check slot", command=self.refresh_availability).grid(row=1, column=6, padx=8)
        ttk.Button(form, text="Book resource", style="Accent.TButton",
                   command=self.book).grid(row=1, column=7, padx=4)

    def selected_resource_id(self):
        sel = self.avail_tree.selection()
        return int(sel[0]) if sel else None

    def update_selected_label(self):
        rid = self.selected_resource_id()
        if rid is None:
            return
        r = self.app.resources.get(rid)
        self.selected_var.set(f"Selected resource: {r.name} ({r.code}) - {r.type}")

    def _slot(self):
        """Return (date, start, end) if the form holds a valid slot, else None."""
        try:
            d = datetime.strptime(self.date_var.get().strip(), "%Y-%m-%d")
            t = datetime.strptime(self.time_var.get().strip(), "%H:%M")
            m = int(self.dur_var.get().strip())
            if m <= 0:
                return None
        except ValueError:
            return None
        s = t.hour * 60 + t.minute
        e = s + m
        if e > 24 * 60:
            return None
        return d.strftime("%Y-%m-%d"), f"{s // 60:02d}:{s % 60:02d}", f"{e // 60:02d}:{e % 60:02d}"

    def refresh_availability(self):
        keep = self.selected_resource_id()
        data = self.app.resources.availability(self.app.campus.id, slot=self._slot())
        self.avail_tree.delete(*self.avail_tree.get_children())
        for a in data:
            r = a["resource"]
            slot_text = "-" if a["slot_free"] is None else ("Free" if a["slot_free"] else "Booked")
            self.avail_tree.insert("", "end", iid=str(r.id), values=(
                r.code, r.name, r.type, r.capacity or "-", a["status"], a["detail"], slot_text),
                tags=("free" if a["status"] == "Available" else "busy",))
        if keep and self.avail_tree.exists(str(keep)):
            self.avail_tree.selection_set(str(keep))

    def book(self):
        rid = self.selected_resource_id()
        if rid is None:
            messagebox.showwarning("Select a resource", "Please click a resource in the table first.",
                                   parent=self)
            return
        try:
            self.app.bookings.create_booking(self.app.user, self.app.campus.id, rid,
                                             self.date_var.get(), self.time_var.get(),
                                             self.dur_var.get())
        except ValidationError as e:
            show_error(self, e)
            return
        messagebox.showinfo("Booking confirmed", "Your booking has been saved.", parent=self)
        self.refresh_availability()
        self.refresh_mine()

    # -- my bookings tab ----------------------------------------------------
    def build_mine_tab(self, tab):
        cols = [c for c in BOOKING_COLUMNS]
        ttk.Label(tab, text="Active bookings (upcoming / in progress)",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.active_tree = make_tree(tab, cols, height=7)
        self.active_tree.container.pack(fill="both", expand=True, pady=4)
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        ttk.Button(bar, text="Cancel selected booking", command=self.cancel).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self.refresh_mine).pack(side="left", padx=6)
        ttk.Label(tab, text="Past booking history (completed and cancelled)",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 0))
        self.history_tree = make_tree(tab, cols, height=7)
        self.history_tree.container.pack(fill="both", expand=True, pady=4)
        self.refresh_mine()
        self.refresh_availability()

    def refresh_mine(self):
        active, history = self.app.bookings.lecturer_bookings(self.app.user)
        fill_tree(self.active_tree, booking_rows(active))
        fill_tree(self.history_tree, booking_rows(history))

    def cancel(self):
        sel = self.active_tree.selection()
        if not sel:
            messagebox.showwarning("Select a booking", "Select an active booking to cancel.", parent=self)
            return
        if not messagebox.askyesno("Confirm", "Cancel the selected booking?", parent=self):
            return
        try:
            self.app.bookings.cancel_booking(self.app.user, int(sel[0]))
        except ValidationError as e:
            show_error(self, e)
            return
        self.refresh_mine()
        self.refresh_availability()


# ---------------------------------------------------------------------------
def draw_bars(canvas, data, title, width=520, height=200, color=BLUE):
    """Minimal bar chart drawn on a Canvas (usage trends)."""
    canvas.delete("all")
    canvas.create_text(8, 8, anchor="nw", text=title, font=("Segoe UI", 10, "bold"), fill=DARK)
    if not data or max(data.values()) == 0:
        canvas.create_text(width // 2, height // 2, text="No data yet", fill="#666")
        return
    top, bottom, left = 34, height - 28, 12
    mx = max(data.values())
    slot = (width - left * 2) / len(data)
    for i, (label, value) in enumerate(data.items()):
        x0 = left + i * slot + slot * 0.15
        x1 = left + (i + 1) * slot - slot * 0.15
        y = bottom - (bottom - top) * value / mx
        canvas.create_rectangle(x0, y, x1, bottom, fill=color, outline="")
        canvas.create_text((x0 + x1) / 2, y - 8, text=str(value), font=("Segoe UI", 8))
        canvas.create_text((x0 + x1) / 2, bottom + 12, text=str(label), font=("Segoe UI", 8))


class ReportPanel(ttk.Frame):
    """Campus-level report: totals, most used resources, average duration, trends."""

    def __init__(self, parent, app, campus_id_getter):
        super().__init__(parent)
        self.app, self.get_campus_id = app, campus_id_getter
        self.summary = tk.StringVar()
        ttk.Label(self, textvariable=self.summary, font=("Segoe UI", 11, "bold"),
                  justify="left").pack(anchor="w", pady=4)
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True)
        left = ttk.Frame(mid)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="Most frequently used resources", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.top_tree = make_tree(left, [("rank", "#", 40), ("res", "Resource", 200),
                                         ("n", "Bookings", 80), ("hrs", "Hours", 70)], height=6)
        self.top_tree.container.pack(fill="x", pady=4)
        self.hour_canvas = tk.Canvas(left, height=200, bg="white", highlightthickness=1)
        self.hour_canvas.pack(fill="x", pady=4)
        self.day_canvas = tk.Canvas(mid, width=360, height=200, bg="white", highlightthickness=1)
        self.day_canvas.pack(side="right", anchor="n", padx=(10, 0))
        ttk.Button(self, text="Refresh report", command=self.refresh).pack(anchor="w")
        self.refresh()

    def refresh(self):
        try:
            rep = self.app.reports.campus_report(self.app.user, self.get_campus_id())
        except ValidationError as e:
            show_error(self, e)
            return
        self.summary.set(f"{rep['campus'].name}\nTotal bookings: {rep['total_bookings']}   |   "
                         f"Average duration: {rep['avg_duration']} min   |   "
                         f"Total booked hours: {rep['total_hours']}   |   "
                         f"Cancelled: {rep['cancelled_bookings']}")
        rows = []
        for i, (name, n) in enumerate(rep["most_used"], 1):
            rows.append((i, i, name, n, round(rep["minutes_by_resource"].get(name, 0) / 60, 1)))
        fill_tree(self.top_tree, rows)
        hours = {f"{h:02d}h": c for h, c in rep["by_hour"].items()}
        draw_bars(self.hour_canvas, hours, "Bookings by start hour (usage trend)", width=520)
        draw_bars(self.day_canvas, rep["by_weekday"], "Bookings by weekday", width=360, color=GREEN)


# ---------------------------------------------------------------------------
class AdminDashboard(DashboardBase):
    def build_tabs(self):
        self.build_resources_tab(self.tab("Manage Resources"))
        self.build_bookings_tab(self.tab("Campus Bookings"))
        self.build_availability_tab(self.tab("Availability"))
        report_tab = self.tab("Usage & Reports")
        self.report = ReportPanel(report_tab, self.app, lambda: self.app.campus.id)
        self.report.pack(fill="both", expand=True)
        self.schedule(self.refresh_availability)

    # -- resources ----------------------------------------------------------
    def build_resources_tab(self, tab):
        self.res_tree = make_tree(tab, [("code", "Resource ID", 120), ("name", "Name", 220),
                                        ("type", "Type", 180), ("cap", "Capacity", 80)], height=9)
        self.res_tree.container.pack(fill="both", expand=True)
        self.res_tree.bind("<<TreeviewSelect>>", lambda e: self.load_selected())
        form = ttk.LabelFrame(tab, text=" Add / update resource ", padding=12)
        form.pack(fill="x", pady=8)
        self.code_var, self.name_var = tk.StringVar(), tk.StringVar()
        self.type_var, self.cap_var = tk.StringVar(value=ResourceService.RESOURCE_TYPES[0]), tk.StringVar(value="0")
        items = [("Resource ID", ttk.Entry(form, textvariable=self.code_var, width=14)),
                 ("Name", ttk.Entry(form, textvariable=self.name_var, width=22)),
                 ("Type", ttk.Combobox(form, textvariable=self.type_var, width=22, state="readonly",
                                       values=ResourceService.RESOURCE_TYPES)),
                 ("Capacity", ttk.Entry(form, textvariable=self.cap_var, width=6))]
        for i, (label, widget) in enumerate(items):
            ttk.Label(form, text=label).grid(row=0, column=i * 2, padx=(8, 3))
            widget.grid(row=0, column=i * 2 + 1)
        bar = ttk.Frame(form)
        bar.grid(row=1, column=0, columnspan=8, pady=(10, 0), sticky="w")
        ttk.Button(bar, text="Add resource", style="Accent.TButton", command=self.add).pack(side="left", padx=4)
        ttk.Button(bar, text="Update selected", command=self.update).pack(side="left", padx=4)
        ttk.Button(bar, text="Remove selected", command=self.remove).pack(side="left", padx=4)
        ttk.Button(bar, text="Clear form", command=self.clear_form).pack(side="left", padx=4)
        self.refresh_resources()

    def refresh_resources(self):
        rows = [(r.id, r.code, r.name, r.type, r.capacity)
                for r in self.app.resources.list_for_campus(self.app.campus.id)]
        fill_tree(self.res_tree, rows)

    def clear_form(self):
        self.code_var.set(""); self.name_var.set(""); self.cap_var.set("0")
        self.type_var.set(ResourceService.RESOURCE_TYPES[0])

    def load_selected(self):
        sel = self.res_tree.selection()
        if not sel:
            return
        r = self.app.resources.get(int(sel[0]))
        if r:
            self.code_var.set(r.code); self.name_var.set(r.name)
            self.type_var.set(r.type); self.cap_var.set(str(r.capacity))

    def _run(self, action, success_msg):
        try:
            action()
        except ValidationError as e:
            show_error(self, e)
            return
        messagebox.showinfo("Success", success_msg, parent=self)
        self.refresh_resources()
        self.refresh_availability()
        self.refresh_bookings()

    def add(self):
        self._run(lambda: self.app.resources.add(self.app.user, self.app.campus.id, self.code_var.get(),
                                                 self.name_var.get(), self.type_var.get(), self.cap_var.get()),
                  "Resource added.")

    def update(self):
        sel = self.res_tree.selection()
        if not sel:
            messagebox.showwarning("Select a resource", "Select a resource to update.", parent=self)
            return
        self._run(lambda: self.app.resources.update(self.app.user, int(sel[0]), self.code_var.get(),
                                                    self.name_var.get(), self.type_var.get(), self.cap_var.get()),
                  "Resource updated.")

    def remove(self):
        sel = self.res_tree.selection()
        if not sel:
            messagebox.showwarning("Select a resource", "Select a resource to remove.", parent=self)
            return
        if not messagebox.askyesno("Confirm", "Remove the selected resource?", parent=self):
            return
        self._run(lambda: self.app.resources.remove(self.app.user, int(sel[0])), "Resource removed.")
        self.clear_form()

    # -- bookings -----------------------------------------------------------
    def build_bookings_tab(self, tab):
        cols = BOOKING_COLUMNS + [("lecturer", "Lecturer", 160)]
        self.bk_tree = make_tree(tab, cols, height=18)
        self.bk_tree.container.pack(fill="both", expand=True)
        ttk.Button(tab, text="Refresh", command=self.refresh_bookings).pack(anchor="w", pady=6)
        self.refresh_bookings()

    def refresh_bookings(self):
        fill_tree(self.bk_tree, booking_rows(
            self.app.bookings.campus_bookings(self.app.user, self.app.campus.id), with_lecturer=True))

    # -- availability -------------------------------------------------------
    def build_availability_tab(self, tab):
        ttk.Label(tab, text="Real-time resource status (refreshes every 30 s)",
                  style="Sub.TLabel").pack(anchor="w")
        self.av_tree = make_tree(tab, [("code", "Resource ID", 120), ("name", "Name", 200),
                                       ("type", "Type", 170), ("status", "Status", 90),
                                       ("detail", "Details", 260)], height=16)
        self.av_tree.container.pack(fill="both", expand=True, pady=6)
        self.av_tree.tag_configure("free", foreground=GREEN)
        self.av_tree.tag_configure("busy", foreground=RED)
        ttk.Button(tab, text="Refresh now", command=self.refresh_availability).pack(anchor="w")
        self.refresh_availability()

    def refresh_availability(self):
        self.av_tree.delete(*self.av_tree.get_children())
        for a in self.app.resources.availability(self.app.campus.id):
            r = a["resource"]
            self.av_tree.insert("", "end", values=(r.code, r.name, r.type, a["status"], a["detail"]),
                                tags=("free" if a["status"] == "Available" else "busy",))


# ---------------------------------------------------------------------------
class OperatorDashboard(DashboardBase):
    def build_tabs(self):
        self.build_all_bookings(self.tab("All Bookings"))
        self.build_resources(self.tab("All Resources"))
        report_tab = self.tab("Campus Report")
        self.report = ReportPanel(report_tab, self.app, lambda: self.app.campus.id)
        self.report.pack(fill="both", expand=True)
        self.build_compare(self.tab("Cross-Campus Comparison"))
        self.build_campuses(self.tab("Campuses"))

    def build_all_bookings(self, tab):
        cols = BOOKING_COLUMNS + [("lecturer", "Lecturer", 160)]
        self.all_tree = make_tree(tab, cols, height=18)
        self.all_tree.container.pack(fill="both", expand=True)
        ttk.Button(tab, text="Refresh", command=self.refresh_all).pack(anchor="w", pady=6)
        self.refresh_all()

    def refresh_all(self):
        fill_tree(self.all_tree, booking_rows(self.app.bookings.all_bookings(self.app.user), with_lecturer=True))

    def build_resources(self, tab):
        self.res_tree = make_tree(tab, [("campus", "Campus", 200), ("code", "Resource ID", 120),
                                        ("name", "Name", 220), ("type", "Type", 170), ("cap", "Capacity", 70)],
                                  height=18)
        self.res_tree.container.pack(fill="both", expand=True)
        ttk.Button(tab, text="Refresh", command=self.refresh_resources).pack(anchor="w", pady=6)
        self.refresh_resources()

    def refresh_resources(self):
        rows = []
        for cid, c in self.app.campuses.all_campuses().items():
            for r in self.app.resources.list_for_campus(cid):
                rows.append((r.id, c.name, r.code, r.name, r.type, r.capacity))
        fill_tree(self.res_tree, rows)

    def build_compare(self, tab):
        ttk.Label(tab, text="Resource usage and booking trends across campuses",
                  font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.cmp_tree = make_tree(tab, [("campus", "Campus", 160), ("res", "Resources", 70),
                                        ("bk", "Bookings", 70), ("bpr", "Per resource", 90),
                                        ("avg", "Avg min", 70), ("hrs", "Hours", 60),
                                        ("cx", "Cancel %", 70), ("top", "Top resource", 150)], height=5)
        self.cmp_tree.container.pack(fill="x", pady=4)
        self.cmp_tree.bind("<<TreeviewSelect>>", lambda e: None)
        ttk.Label(tab, text="Booking policy per campus (explains the differences)",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 0))
        self.policy_text = tk.Text(tab, height=6, wrap="word", font=("Segoe UI", 9), bg="white")
        self.policy_text.pack(fill="x", pady=4)
        ttk.Label(tab, text="Insights", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8, 0))
        self.insight_text = tk.Text(tab, height=4, wrap="word", font=("Segoe UI", 10), bg="white")
        self.insight_text.pack(fill="x", pady=4)
        self.chart = tk.Canvas(tab, height=130, bg="white", highlightthickness=1)
        self.chart.pack(fill="x", pady=4)
        ttk.Button(tab, text="Refresh comparison", command=self.refresh_compare).pack(anchor="w")
        self.refresh_compare()

    def refresh_compare(self):
        data = self.app.reports.compare_campuses(self.app.user)
        rows = [(i, r["campus"], r["resources"], r["bookings"], r["bookings_per_resource"],
                 r["avg_duration"], r["total_hours"], r["cancel_rate"], r["top_resource"])
                for i, r in enumerate(data["rows"])]
        fill_tree(self.cmp_tree, rows)
        for widget, lines in ((self.policy_text, [f"{r['campus']}: {r['policy']}" for r in data["rows"]]),
                              (self.insight_text, ["- " + t for t in data["insights"]])):
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("end", "\n".join(lines))
            widget.configure(state="disabled")
        draw_bars(self.chart, {r["campus"].replace(" Campus", ""): r["bookings"] for r in data["rows"]},
                  "Total bookings per campus", width=1000, height=130)

    def build_campuses(self, tab):
        self.campus_tree = make_tree(tab, [("name", "Campus", 220), ("policy", "Policy key", 140),
                                           ("desc", "Booking rules", 520)], height=8)
        self.campus_tree.container.pack(fill="both", expand=True)
        form = ttk.LabelFrame(tab, text=" Add a new campus ", padding=12)
        form.pack(fill="x", pady=8)
        self.new_name, self.new_policy = tk.StringVar(), tk.StringVar()
        ttk.Label(form, text="Campus name").grid(row=0, column=0, padx=4)
        ttk.Entry(form, textvariable=self.new_name, width=26).grid(row=0, column=1)
        ttk.Label(form, text="Booking policy").grid(row=0, column=2, padx=(14, 4))
        ttk.Combobox(form, textvariable=self.new_policy, state="readonly", width=18,
                     values=sorted(POLICY_REGISTRY)).grid(row=0, column=3)
        ttk.Button(form, text="Add campus", style="Accent.TButton", command=self.add_campus).grid(row=0, column=4, padx=12)
        ttk.Label(form, text="New policies are registered in booking_rules.py (see README).",
                  style="Sub.TLabel").grid(row=1, column=0, columnspan=5, sticky="w", pady=(8, 0))
        self.refresh_campuses()

    def refresh_campuses(self):
        rows = [(cid, c.name, c.policy_key, c.policy.describe())
                for cid, c in self.app.campuses.all_campuses().items()]
        fill_tree(self.campus_tree, rows)

    def add_campus(self):
        try:
            self.app.campuses.add_campus(self.app.user, self.new_name.get(), self.new_policy.get())
        except ValidationError as e:
            show_error(self, e)
            return
        messagebox.showinfo("Success", "Campus added. Campus administrators and resources can "
                                       "now be created for it.", parent=self)
        self.new_name.set("")
        self.refresh_campuses()
        self.refresh_compare()
