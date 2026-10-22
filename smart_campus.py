import hashlib
import random
import sqlite3
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import ttk, messagebox

# ======================================================================
# SECTION: DATABASE
# ======================================================================

DB_FILE = "campus_booking.db"


def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def make_salt():
    return "".join(random.choice("0123456789abcdef") for _ in range(16))


def hash_password(password, salt):
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def init_database():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS campuses (
            campus_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            policy_key TEXT NOT NULL
        )""")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt          TEXT NOT NULL,
            full_name     TEXT NOT NULL,
            role          TEXT NOT NULL
                          CHECK (role IN ('lecturer', 'admin', 'operator')),
            campus_id     INTEGER REFERENCES campuses(campus_id)
        )""")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS resources (
            resource_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_code TEXT NOT NULL UNIQUE,
            name          TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            campus_id     INTEGER NOT NULL REFERENCES campuses(campus_id),
            available     INTEGER NOT NULL DEFAULT 1,
            removed       INTEGER NOT NULL DEFAULT 0
        )""")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_id      INTEGER NOT NULL REFERENCES resources(resource_id),
            user_id          INTEGER NOT NULL REFERENCES users(user_id),
            campus_id        INTEGER NOT NULL REFERENCES campuses(campus_id),
            booking_date     TEXT NOT NULL,      -- YYYY-MM-DD
            start_time       TEXT NOT NULL,      -- HH:MM
            duration_minutes INTEGER NOT NULL,
            status           TEXT NOT NULL DEFAULT 'active'
                             CHECK (status IN ('active', 'cancelled'))
        )""")
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM campuses")
    if cur.fetchone()[0] == 0:
        seed_data(conn)
    conn.close()


def _add_user(cur, username, password, full_name, role, campus_id=None):
    """Helper used by the seed code to insert a user."""
    salt = make_salt()
    cur.execute(
        "INSERT INTO users (username, password_hash, salt, full_name, role, campus_id)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (username, hash_password(password, salt), salt, full_name, role, campus_id))


def seed_data(conn):
    """Insert starter campuses, resources and demo accounts."""
    cur = conn.cursor()

    # (campus name, policy key) - the policy keys are defined in booking_rules.py
    campuses = [
        ("Johannesburg", "JHB"),
        ("Durban", "DBN"),
        ("Cape Town", "CPT"),
        ("Pretoria", "PTA"),
    ]
    for name, policy_key in campuses:
        cur.execute("INSERT INTO campuses (name, policy_key) VALUES (?, ?)",
                    (name, policy_key))

    # Starter resources for every campus.
    for campus_id, (name, key) in enumerate(campuses, start=1):
        starter = [
            (key + "-LAB-01", "Computer Lab 1", "Computer Laboratory"),
            (key + "-LAB-02", "Computer Lab 2", "Computer Laboratory"),
            (key + "-PRJ-01", "Projector A", "Multimedia Projector"),
            (key + "-SEM-01", "Seminar Room 1", "Seminar Room"),
            (key + "-PRS-01", "Presentation Kit", "Presentation Equipment"),
        ]
        for code, rname, rtype in starter:
            cur.execute(
                "INSERT INTO resources (resource_code, name, resource_type, campus_id)"
                " VALUES (?, ?, ?, ?)", (code, rname, rtype, campus_id))

    # Demo accounts (passwords are hashed before they are stored).
    _add_user(cur, "operator", "operator123", "Head Office Operator", "operator")
    for campus_id, (name, key) in enumerate(campuses, start=1):
        _add_user(cur, "admin_" + key.lower(), "admin123",
                  name + " Administrator", "admin", campus_id)
    _add_user(cur, "lecturer1", "lecturer123", "Demo Lecturer", "lecturer")
    conn.commit()


# ======================================================================
# SECTION: BOOKING RULES
# ======================================================================
# booking_rules.py
# ----------------
# Campus-specific booking policies, kept SEPARATE from the core system logic.
#
# HOW TO ADD A NEW CAMPUS RULE SET
# --------------------------------
# 1. Add one line to the POLICIES dictionary below with a new key.
# 2. Insert a campus row in the database using that key as its policy_key.
# Nothing else in the program has to change.
def to_minutes(time_text):
    """Convert 'HH:MM' to minutes after midnight (e.g. '09:30' -> 570)."""
    hours, minutes = time_text.split(":")
    return int(hours) * 60 + int(minutes)


class BookingPolicy:
    """A set of booking constraints that one campus applies."""

    def __init__(self, name, max_minutes, open_time, close_time,
                 max_active_bookings, advance_days, weekends_allowed):
        self.name = name
        self.max_minutes = max_minutes                    # longest single session
        self.open_time = open_time                        # earliest start ('HH:MM')
        self.close_time = close_time                      # latest finish ('HH:MM')
        self.max_active_bookings = max_active_bookings    # per lecturer
        self.advance_days = advance_days                  # how far ahead you may book
        self.weekends_allowed = weekends_allowed

    def describe(self):
        """Return a one-line summary shown in the GUI."""
        weekend = "weekends allowed" if self.weekends_allowed else "no weekends"
        return (f"{self.name}: max {self.max_minutes} min per session, "
                f"{self.open_time}-{self.close_time}, "
                f"max {self.max_active_bookings} active bookings, "
                f"book up to {self.advance_days} days ahead, {weekend}")

    def check(self, booking_date, start_time, duration, active_count):
        """
        Check a requested booking against this policy.
        booking_date is a datetime.date, start_time is 'HH:MM',
        duration is in minutes. Returns a list of error messages
        (an empty list means the booking is allowed).
        """
        errors = []
        start = to_minutes(start_time)
        end = start + duration

        if duration > self.max_minutes:
            errors.append(f"Duration too long. This campus allows at most "
                          f"{self.max_minutes} minutes per session.")
        if start < to_minutes(self.open_time) or end > to_minutes(self.close_time):
            errors.append(f"Bookings must fall between {self.open_time} "
                          f"and {self.close_time} on this campus.")
        if booking_date.weekday() >= 5 and not self.weekends_allowed:
            errors.append("This campus does not allow weekend bookings.")
        days_ahead = (booking_date - datetime.now().date()).days
        if days_ahead > self.advance_days:
            errors.append(f"You can only book up to {self.advance_days} "
                          f"days in advance on this campus.")
        if active_count >= self.max_active_bookings:
            errors.append(f"You already have {active_count} active bookings. "
                          f"The limit on this campus is {self.max_active_bookings}.")
        return errors

POLICIES = {
    "JHB": BookingPolicy("Johannesburg Policy", 120, "08:00", "17:00", 3, 30, False),
    "DBN": BookingPolicy("Durban Policy",       180, "07:00", "19:00", 5, 14, True),
    "CPT": BookingPolicy("Cape Town Policy",    240, "08:00", "21:00", 2, 60, True),
    "PTA": BookingPolicy("Pretoria Policy",      90, "08:00", "16:00", 4, 7,  False),
}

# Used if a campus has an unknown policy key (keeps the program from crashing).
DEFAULT_POLICY = BookingPolicy("Default Policy", 120, "08:00", "17:00", 3, 30, True)

def get_policy(policy_key):
    """Return the BookingPolicy for a campus policy key."""
    return POLICIES.get(policy_key, DEFAULT_POLICY)

# ======================================================================
# SECTION: MODELS
# ======================================================================

class User:
    """Base class for every person who logs into the system."""

    role = "user"
    role_label = "User"
    permissions = set()          # overridden by each subclass

    def __init__(self, user_id, username, full_name, campus_id=None):
        self._user_id = user_id
        self._username = username
        self._full_name = full_name
        self._campus_id = campus_id

    @property
    def user_id(self):
        return self._user_id

    @property
    def username(self):
        return self._username

    @property
    def full_name(self):
        return self._full_name

    @property
    def campus_id(self):
        return self._campus_id

    def can(self, permission):
        """Return True if this role is allowed to do the given action."""
        return permission in self.permissions

    def __str__(self):
        return f"{self._full_name} ({self.role_label})"

class Lecturer(User):
    role = "lecturer"
    role_label = "Lecturer"
    permissions = {"book_resource", "view_own_bookings", "cancel_booking"}

class CampusAdministrator(User):
    role = "admin"
    role_label = "Campus Administrator"
    permissions = {"manage_resources", "view_campus_bookings", "view_campus_reports"}

class SystemOperator(User):
    role = "operator"
    role_label = "System Operator"
    permissions = {"view_all_data", "compare_campuses", "view_campus_reports"}

ROLE_CLASSES = {
    "lecturer": Lecturer,
    "admin": CampusAdministrator,
    "operator": SystemOperator,
}

def create_user(row):
    """Build the correct User subclass from a database row."""
    user_class = ROLE_CLASSES[row["role"]]
    return user_class(row["user_id"], row["username"],
                      row["full_name"], row["campus_id"])

class Campus:
    """A campus and the booking policy it uses."""

    def __init__(self, campus_id, name, policy_key):
        self.campus_id = campus_id
        self.name = name
        self.policy = get_policy(policy_key)

    def __str__(self):
        return self.name

class Resource:
    """A bookable resource (lab, projector, seminar room...)."""

    def __init__(self, resource_id, code, name, resource_type, campus_id, available):
        self.resource_id = resource_id
        self.code = code
        self.name = name
        self.resource_type = resource_type
        self.campus_id = campus_id
        self.available = bool(available)

# ======================================================================
# SECTION: SERVICES (CORE LOGIC)
# ======================================================================

class BookingError(Exception):
    """Raised when the user enters something invalid or breaks a rule."""

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"]

# ---------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------

def parse_date(text):
    """Turn 'YYYY-MM-DD' text into a date object."""
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise BookingError("Date must be in the format YYYY-MM-DD (e.g. 2026-11-05).")

def parse_time(text):
    """Check 'HH:MM' (24 hour) and return it in a clean format."""
    try:
        return datetime.strptime(text.strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        raise BookingError("Time must be in 24-hour format HH:MM (e.g. 09:30).")

def parse_duration(text):
    """Duration in minutes must be a whole number greater than zero."""
    try:
        minutes = int(str(text).strip())
    except ValueError:
        raise BookingError("Duration must be a whole number of minutes.")
    if minutes <= 0:
        raise BookingError("Duration must be greater than zero.")
    return minutes

def end_time_text(start_time, duration):
    """Return the finish time ('HH:MM') of a booking."""
    total = to_minutes(start_time) + duration
    return f"{total // 60:02d}:{total % 60:02d}"

# ---------------------------------------------------------------------
# Users and login
# ---------------------------------------------------------------------

def register_lecturer(username, full_name, password, confirm):
    """Create a new lecturer account."""
    username = username.strip()
    full_name = full_name.strip()
    if not username or not full_name or not password:
        raise BookingError("Please fill in all fields.")
    if len(username) < 3:
        raise BookingError("Username must be at least 3 characters.")
    if len(password) < 6:
        raise BookingError("Password must be at least 6 characters.")
    if password != confirm:
        raise BookingError("Passwords do not match.")

    salt = make_salt()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, full_name, role)"
            " VALUES (?, ?, ?, ?, 'lecturer')",
            (username, hash_password(password, salt), salt, full_name))
        conn.commit()
    except sqlite3.IntegrityError:
        raise BookingError("That username is already taken.")
    finally:
        conn.close()

def authenticate(username, password):
    """Check login details and return the matching User object."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE username = ?",
                       (username.strip(),)).fetchone()
    conn.close()
    if row is None or hash_password(password, row["salt"]) != row["password_hash"]:
        raise BookingError("Incorrect username or password.")
    return create_user(row)

# ---------------------------------------------------------------------
# Campuses and resources
# ---------------------------------------------------------------------

def load_campuses():
    """Return a dictionary {campus_id: Campus object}."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM campuses ORDER BY name").fetchall()
    conn.close()
    campuses = {}
    for row in rows:
        campuses[row["campus_id"]] = Campus(row["campus_id"], row["name"],
                                            row["policy_key"])
    return campuses

def get_resources(campus_id, include_removed=False):
    """Return a list of Resource objects for one campus."""
    sql = "SELECT * FROM resources WHERE campus_id = ?"
    if not include_removed:
        sql += " AND removed = 0"
    sql += " ORDER BY resource_code"
    conn = get_connection()
    rows = conn.execute(sql, (campus_id,)).fetchall()
    conn.close()
    return [Resource(r["resource_id"], r["resource_code"], r["name"],
                     r["resource_type"], r["campus_id"], r["available"])
            for r in rows]

def get_all_resource_codes():
    """Return a SET of every resource code (used to detect duplicates)."""
    conn = get_connection()
    rows = conn.execute("SELECT resource_code FROM resources").fetchall()
    conn.close()
    return {row["resource_code"].upper() for row in rows}

def add_resource(campus_id, code, name, resource_type):
    """Register a new resource. Duplicate codes are rejected."""
    code = code.strip().upper()
    name = name.strip()
    resource_type = resource_type.strip()
    if not code or not name or not resource_type:
        raise BookingError("Resource code, name and type are all required.")
    if " " in code:
        raise BookingError("Resource code may not contain spaces.")
    if code in get_all_resource_codes():
        raise BookingError(f"A resource with code '{code}' already exists.")
    
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO resources (resource_code, name, resource_type, campus_id)"
            " VALUES (?, ?, ?, ?)", (code, name, resource_type, campus_id))
        conn.commit()
    except sqlite3.IntegrityError:
        raise BookingError(f"A resource with code '{code}' already exists.")
    finally:
        conn.close()

def update_resource(resource_id, name, resource_type, available):
    """Change a resource's name, type or availability (maintenance)."""
    name = name.strip()
    resource_type = resource_type.strip()
    if not name or not resource_type:
        raise BookingError("Resource name and type cannot be empty.")
    conn = get_connection()
    conn.execute("UPDATE resources SET name = ?, resource_type = ?, available = ?"
                 " WHERE resource_id = ?",
                 (name, resource_type, 1 if available else 0, resource_id))
    conn.commit()
    conn.close()

def remove_resource(resource_id):
    """
    Remove a resource from use. It is marked as removed (not deleted) so old
    bookings and reports stay correct. Not allowed if future bookings exist.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT booking_date, start_time, duration_minutes FROM bookings"
        " WHERE resource_id = ? AND status = 'active'", (resource_id,)).fetchall()
    now = datetime.now()
    for row in rows:
        start = datetime.strptime(row["booking_date"] + " " + row["start_time"],
                                  "%Y-%m-%d %H:%M")
        if start + timedelta(minutes=row["duration_minutes"]) > now:
            conn.close()
            raise BookingError("This resource still has upcoming bookings. "
                               "Cancel them or mark the resource unavailable instead.")
    conn.execute("UPDATE resources SET removed = 1 WHERE resource_id = ?",
                 (resource_id,))
    conn.commit()
    conn.close()

def get_resource_statuses(campus_id):
    """
    Real-time availability: returns {resource_id: text} where text is
    'Available', 'In use now' or 'Unavailable (maintenance)'.
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    now_minutes = now.hour * 60 + now.minute

    conn = get_connection()
    rows = conn.execute(
        "SELECT resource_id, start_time, duration_minutes FROM bookings"
        " WHERE campus_id = ? AND booking_date = ? AND status = 'active'",
        (campus_id, today)).fetchall()
    conn.close()

    in_use = set()
    for row in rows:
        start = to_minutes(row["start_time"])
        if start <= now_minutes < start + row["duration_minutes"]:
            in_use.add(row["resource_id"])

    statuses = {}
    for res in get_resources(campus_id):
        if not res.available:
            statuses[res.resource_id] = "Unavailable (maintenance)"
        elif res.resource_id in in_use:
            statuses[res.resource_id] = "In use now"
        else:
            statuses[res.resource_id] = "Available"
    return statuses

# ---------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------

BOOKING_QUERY = """
    SELECT b.booking_id, b.booking_date, b.start_time, b.duration_minutes,
           b.status, r.resource_code, r.name AS resource_name,
           c.name AS campus_name, u.full_name AS lecturer_name
    FROM bookings b
    JOIN resources r ON r.resource_id = b.resource_id
    JOIN campuses  c ON c.campus_id   = b.campus_id
    JOIN users     u ON u.user_id     = b.user_id
"""

def _row_to_dict(row):
    """Convert a database row to a dictionary and add end time / past flag."""
    booking = dict(row)
    booking["end_time"] = end_time_text(row["start_time"], row["duration_minutes"])
    end = datetime.strptime(row["booking_date"] + " " + booking["end_time"],
                            "%Y-%m-%d %H:%M")
    booking["finished"] = end <= datetime.now()
    return booking

def _fetch_bookings(where="", params=()):
    conn = get_connection()
    rows = conn.execute(BOOKING_QUERY + where +
                        " ORDER BY b.booking_date, b.start_time", params).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]

def get_booked_slots(resource_id, date_text):
    """List the already-booked time slots of a resource on a given date."""
    booking_date = parse_date(date_text)
    bookings = _fetch_bookings(
        " WHERE b.resource_id = ? AND b.booking_date = ? AND b.status = 'active'",
        (resource_id, booking_date.isoformat()))
    return [f"{b['start_time']} - {b['end_time']}  ({b['lecturer_name']})"
            for b in bookings]

def create_booking(user, campus_id, resource_id, date_text, start_text, duration_text):
    """Validate and save a new booking. Raises BookingError if not allowed."""
    if not user.can("book_resource"):
        raise BookingError("Your role is not allowed to create bookings.")
    if resource_id is None:
        raise BookingError("Please select a resource first.")

    booking_date = parse_date(date_text)
    start_time = parse_time(start_text)
    duration = parse_duration(duration_text)
    start_dt = datetime.strptime(booking_date.isoformat() + " " + start_time,
                                 "%Y-%m-%d %H:%M")
    if start_dt < datetime.now():
        raise BookingError("You cannot make a booking in the past.")

    campuses = load_campuses()
    campus = campuses[campus_id]
    resource = None
    for res in get_resources(campus_id):
        if res.resource_id == resource_id:
            resource = res
    if resource is None:
        raise BookingError("That resource does not belong to the selected campus.")
    if not resource.available:
        raise BookingError("This resource is currently unavailable.")

    my_active = [b for b in get_user_bookings(user.user_id)[0]
                 if b["campus_name"] == campus.name]
    errors = campus.policy.check(booking_date, start_time, duration, len(my_active))
    if errors:
        raise BookingError("\n".join(errors))

    new_start = to_minutes(start_time)
    new_end = new_start + duration
    for other in _fetch_bookings(
            " WHERE b.resource_id = ? AND b.booking_date = ? AND b.status = 'active'",
            (resource_id, booking_date.isoformat())):
        old_start = to_minutes(other["start_time"])
        old_end = old_start + other["duration_minutes"]
        if new_start < old_end and old_start < new_end:
            raise BookingError(f"This resource is already booked from "
                               f"{other['start_time']} to {other['end_time']}.")

    conn = get_connection()
    conn.execute(
        "INSERT INTO bookings (resource_id, user_id, campus_id, booking_date,"
        " start_time, duration_minutes) VALUES (?, ?, ?, ?, ?, ?)",
        (resource_id, user.user_id, campus_id, booking_date.isoformat(),
         start_time, duration))
    conn.commit()
    conn.close()


def get_user_bookings(user_id):
    """Return (active_bookings, history) for one user."""
    all_bookings = _fetch_bookings(" WHERE b.user_id = ?", (user_id,))
    active = [b for b in all_bookings
              if b["status"] == "active" and not b["finished"]]
    history = [b for b in all_bookings if b not in active]
    return active, history


def cancel_booking(user, booking_id):
    """Cancel one of the user's own FUTURE bookings."""
    if not user.can("cancel_booking"):
        raise BookingError("Your role is not allowed to cancel bookings.")
    if booking_id is None:
        raise BookingError("Please select a booking to cancel.")
    matches = _fetch_bookings(" WHERE b.booking_id = ? AND b.user_id = ?",
                              (booking_id, user.user_id))
    if not matches:
        raise BookingError("Booking not found.")
    booking = matches[0]
    if booking["status"] == "cancelled":
        raise BookingError("This booking is already cancelled.")
    start = datetime.strptime(booking["booking_date"] + " " + booking["start_time"],
                              "%Y-%m-%d %H:%M")
    if start <= datetime.now():
        raise BookingError("Only future bookings can be cancelled.")

    conn = get_connection()
    conn.execute("UPDATE bookings SET status = 'cancelled' WHERE booking_id = ?",
                 (booking_id,))
    conn.commit()
    conn.close()


def get_campus_bookings(campus_id):
    """All bookings for one campus (administrators)."""
    return _fetch_bookings(" WHERE b.campus_id = ?", (campus_id,))


def get_all_bookings():
    """All bookings across every campus (system operators)."""
    return _fetch_bookings()


# ---------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------

def campus_report(campus_id):
    """
    Build a report for one campus using its non-cancelled bookings.
    Returns a dictionary with totals, top resources, averages and trends.
    """
    bookings = [b for b in get_campus_bookings(campus_id)
                if b["status"] == "active"]
    cancelled = len(get_campus_bookings(campus_id)) - len(bookings)

    usage = {}          # resource name -> number of bookings
    weekday_counts = {name: 0 for name in WEEKDAYS}
    total_minutes = 0
    for b in bookings:
        label = b["resource_code"] + " - " + b["resource_name"]
        usage[label] = usage.get(label, 0) + 1
        total_minutes += b["duration_minutes"]
        day = datetime.strptime(b["booking_date"], "%Y-%m-%d").weekday()
        weekday_counts[WEEKDAYS[day]] += 1

    total = len(bookings)
    top = sorted(usage.items(), key=lambda item: item[1], reverse=True)
    resource_count = len(get_resources(campus_id))
    return {
        "total": total,
        "cancelled": cancelled,
        "average_duration": total_minutes / total if total else 0,
        "total_hours": total_minutes / 60,
        "most_used": top[:3],
        "usage": top,
        "weekdays": weekday_counts,
        "resource_count": resource_count,
        "bookings_per_resource": total / resource_count if resource_count else 0,
    }


def comparison_report():
    """Return a list of per-campus summary dictionaries for comparison."""
    rows = []
    for campus in load_campuses().values():
        report = campus_report(campus.campus_id)
        report["campus"] = campus.name
        report["policy"] = campus.policy
        rows.append(report)
    return rows


def comparison_insights(rows):
    """Write plain-English notes comparing campuses and how rules affect usage."""
    if not rows or all(r["total"] == 0 for r in rows):
        return ["No bookings have been made yet, so there is nothing to compare."]
    notes = []
    busiest = max(rows, key=lambda r: r["total"])
    notes.append(f"Most bookings: {busiest['campus']} ({busiest['total']} bookings).")
    longest = max(rows, key=lambda r: r["average_duration"])
    notes.append(f"Longest average session: {longest['campus']} "
                 f"({longest['average_duration']:.0f} min). Its policy allows up to "
                 f"{longest['policy'].max_minutes} min per session.")
    for r in rows:
        if r["total"] and r["average_duration"] >= 0.9 * r["policy"].max_minutes:
            notes.append(f"{r['campus']}: sessions are close to the "
                         f"{r['policy'].max_minutes}-minute limit, so the "
                         f"duration rule is shaping behaviour.")
        if not r["policy"].weekends_allowed:
            weekend = r["weekdays"]["Saturday"] + r["weekdays"]["Sunday"]
            notes.append(f"{r['campus']}: weekend bookings are blocked by policy "
                         f"({weekend} weekend bookings recorded).")
    return notes


# ======================================================================
# SECTION: GUI
# ======================================================================

def make_table(parent, columns, widths, height=10):
    """Create a Treeview table. columns is a list of heading names."""
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=columns, show="headings",
                        height=height, selectmode="browse")
    for name, width in zip(columns, widths):
        tree.heading(name, text=name)
        tree.column(name, width=width, anchor="w")
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return frame, tree


def clear_table(tree):
    for item in tree.get_children():
        tree.delete(item)


def fill_bookings_table(tree, bookings, show_lecturer=True, show_campus=True):
    """Put a list of booking dictionaries into a bookings table."""
    clear_table(tree)
    for b in bookings:
        status = b["status"].capitalize()
        if b["status"] == "active" and b["finished"]:
            status = "Completed"
        values = [b["booking_id"], b["booking_date"], b["start_time"],
                  b["end_time"], b["duration_minutes"],
                  b["resource_code"] + " " + b["resource_name"]]
        if show_campus:
            values.append(b["campus_name"])
        if show_lecturer:
            values.append(b["lecturer_name"])
        values.append(status)
        tree.insert("", "end", iid=str(b["booking_id"]), values=values)


def booking_columns(show_lecturer=True, show_campus=True):
    """Return (columns, widths) for a bookings table."""
    columns = ["ID", "Date", "Start", "End", "Minutes", "Resource"]
    widths = [40, 90, 55, 55, 60, 220]
    if show_campus:
        columns.append("Campus")
        widths.append(100)
    if show_lecturer:
        columns.append("Lecturer")
        widths.append(140)
    columns.append("Status")
    widths.append(90)
    return columns, widths


# ---------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Smart Campus Resource Booking System")
        self.geometry("1000x640")
        self.minsize(900, 600)

        self.user = None            # the logged-in User object
        self.campus = None          # the currently active Campus object
        self.campuses = {}          # {campus_id: Campus}
        self.current_frame = None

        self.show_login()

    def _switch(self, frame):
        """Remove the current screen and show a new one."""
        if self.current_frame is not None:
            self.current_frame.destroy()
        self.current_frame = frame
        frame.pack(fill="both", expand=True)

    def show_login(self):
        self.user = None
        self.campus = None
        self._switch(LoginFrame(self))

    def show_campus_select(self):
        self.campuses = load_campuses()
        self._switch(CampusSelectFrame(self))

    def show_dashboard(self):
        self._switch(DashboardFrame(self))


# ---------------------------------------------------------------------
# Screen 1: Login / Register
# ---------------------------------------------------------------------
class LoginFrame(ttk.Frame):
    def __init__(self, app):
        super().__init__(app, padding=40)
        self.app = app

        ttk.Label(self, text="Smart Campus Resource Booking System",
                  font=("Arial", 20, "bold")).pack(pady=(40, 5))
        ttk.Label(self, text="Richfield Graduate Institution",
                  font=("Arial", 12)).pack(pady=(0, 30))

        form = ttk.Frame(self)
        form.pack()
        ttk.Label(form, text="Username:").grid(row=0, column=0, sticky="e", pady=5)
        self.username = ttk.Entry(form, width=30)
        self.username.grid(row=0, column=1, pady=5, padx=5)
        ttk.Label(form, text="Password:").grid(row=1, column=0, sticky="e", pady=5)
        self.password = ttk.Entry(form, width=30, show="*")
        self.password.grid(row=1, column=1, pady=5, padx=5)

        buttons = ttk.Frame(self)
        buttons.pack(pady=15)
        ttk.Button(buttons, text="Log In", command=self.login).pack(side="left", padx=5)
        ttk.Button(buttons, text="Register (Lecturer)",
                   command=self.open_register).pack(side="left", padx=5)

        ttk.Label(self, foreground="gray", justify="center",
                  text="Demo accounts:  lecturer1 / lecturer123   |   "
                       "admin_jhb / admin123   |   operator / operator123"
                  ).pack(pady=20)

        self.username.focus()
        app.bind("<Return>", lambda event: self.login())

    def login(self):
        try:
            user = authenticate(self.username.get(), self.password.get())
        except BookingError as error:
            messagebox.showerror("Login failed", str(error))
            return
        self.app.unbind("<Return>")
        self.app.user = user
        self.app.show_campus_select()

    def open_register(self):
        RegisterWindow(self.app)


class RegisterWindow(tk.Toplevel):
    """Pop-up window for lecturers to create an account."""

    def __init__(self, app):
        super().__init__(app)
        self.title("Register Lecturer Account")
        self.resizable(False, False)
        self.grab_set()

        frame = ttk.Frame(self, padding=20)
        frame.pack()
        self.entries = {}
        fields = [("Full name:", "name", ""), ("Username:", "user", ""),
                  ("Password:", "pass", "*"), ("Confirm password:", "confirm", "*")]
        for row, (label, key, mask) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="e", pady=4)
            entry = ttk.Entry(frame, width=30, show=mask)
            entry.grid(row=row, column=1, padx=5, pady=4)
            self.entries[key] = entry
        ttk.Button(frame, text="Create Account",
                   command=self.register).grid(row=4, column=0, columnspan=2, pady=10)

    def register(self):
        try:
            register_lecturer(self.entries["user"].get(),
                                       self.entries["name"].get(),
                                       self.entries["pass"].get(),
                                       self.entries["confirm"].get())
        except BookingError as error:
            messagebox.showerror("Registration failed", str(error), parent=self)
            return
        messagebox.showinfo("Success", "Account created. You can now log in.",
                            parent=self)
        self.destroy()


# ---------------------------------------------------------------------
# Screen 2: Campus selection
# ---------------------------------------------------------------------
class CampusSelectFrame(ttk.Frame):
    def __init__(self, app):
        super().__init__(app, padding=40)
        self.app = app

        ttk.Label(self, text=f"Welcome, {app.user.full_name}",
                  font=("Arial", 18, "bold")).pack(pady=(40, 5))
        ttk.Label(self, text=f"Role: {app.user.role_label}").pack(pady=(0, 25))
        ttk.Label(self, text="Select a campus to work with:",
                  font=("Arial", 12)).pack(pady=5)

        names = {c.name: cid for cid, c in app.campuses.items()}
        self.name_to_id = names
        self.choice = tk.StringVar()
        self.combo = ttk.Combobox(self, textvariable=self.choice, state="readonly",
                                  values=list(names.keys()), width=30)
        self.combo.pack(pady=5)

        if app.user.role == "admin":
            own = app.campuses[app.user.campus_id]
            self.choice.set(own.name)
            self.combo.configure(state="disabled")
            ttk.Label(self, foreground="gray",
                      text="Administrators manage their own campus only.").pack()
        self.combo.bind("<<ComboboxSelected>>", lambda e: self.show_policy())

        self.policy_label = ttk.Label(self, wraplength=600, justify="center")
        self.policy_label.pack(pady=15)
        self.show_policy()

        buttons = ttk.Frame(self)
        buttons.pack(pady=10)
        ttk.Button(buttons, text="Continue", command=self.continue_clicked
                   ).pack(side="left", padx=5)
        ttk.Button(buttons, text="Log Out", command=app.show_login
                   ).pack(side="left", padx=5)

    def show_policy(self):
        name = self.choice.get()
        if name:
            campus = self.app.campuses[self.name_to_id[name]]
            self.policy_label.config(text="Booking policy:\n" + campus.policy.describe())
        else:
            self.policy_label.config(text="")

    def continue_clicked(self):
        name = self.choice.get()
        if not name:
            messagebox.showwarning("Select campus", "Please choose a campus.")
            return
        self.app.campus = self.app.campuses[self.name_to_id[name]]
        self.app.show_dashboard()


# ---------------------------------------------------------------------
# Screen 3: Dashboard
# ---------------------------------------------------------------------

class DashboardFrame(ttk.Frame):
    def __init__(self, app):
        super().__init__(app, padding=10)
        self.app = app

        # Header: always shows the active campus and the policy in effect.
        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text=f"Active campus: {app.campus.name}",
                  font=("Arial", 14, "bold")).pack(side="left")
        ttk.Button(header, text="Log Out", command=app.show_login
                   ).pack(side="right", padx=2)
        if app.user.role != "admin":
            ttk.Button(header, text="Change Campus", command=app.show_campus_select
                       ).pack(side="right", padx=2)
        ttk.Label(header, text=str(app.user)).pack(side="right", padx=15)

        ttk.Label(self, text="Policy in effect - " + app.campus.policy.describe(),
                  foreground="#7a3b00", wraplength=950).pack(fill="x", pady=(2, 8))

        # Role-based access: show only the tabs the role is allowed to use.
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        if app.user.can("book_resource"):
            LecturerView(self.notebook, app)
        elif app.user.can("manage_resources"):
            AdminView(self.notebook, app)
        elif app.user.can("view_all_data"):
            OperatorView(self.notebook, app)


# ---------------------------------------------------------------------
# Lecturer tabs
# ---------------------------------------------------------------------

class LecturerView:
    def __init__(self, notebook, app):
        self.app = app
        self.notebook = notebook
        self.resource_ids = {}

        self.book_tab = ttk.Frame(notebook, padding=10)
        self.my_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.book_tab, text="Book a Resource")
        notebook.add(self.my_tab, text="My Bookings")
        self.build_book_tab()
        self.build_my_tab()
        self.refresh_resources()
        self.refresh_my_bookings()
        self.auto_refresh()

    def build_book_tab(self):
        left = ttk.LabelFrame(self.book_tab, text="Resources (live availability)",
                              padding=5)
        left.pack(side="left", fill="both", expand=True)
        frame, self.res_tree = make_table(
            left, ["Code", "Name", "Type", "Status"], [90, 140, 150, 150], height=14)
        frame.pack(fill="both", expand=True)
        self.res_tree.bind("<<TreeviewSelect>>", lambda e: self.show_slots())
        ttk.Button(left, text="Refresh", command=self.refresh_resources
                   ).pack(pady=5)

        right = ttk.LabelFrame(self.book_tab, text="New booking", padding=10)
        right.pack(side="right", fill="y", padx=(10, 0))

        self.selected_label = ttk.Label(right, text="Selected: (none)",
                                        font=("Arial", 10, "bold"), wraplength=240)
        self.selected_label.pack(anchor="w", pady=(0, 8))

        ttk.Label(right, text="Date (YYYY-MM-DD):").pack(anchor="w")
        self.date_entry = ttk.Entry(right, width=22)
        self.date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self.date_entry.pack(anchor="w", pady=(0, 6))
        self.date_entry.bind("<FocusOut>", lambda e: self.show_slots())

        ttk.Label(right, text="Start time (HH:MM):").pack(anchor="w")
        self.start_entry = ttk.Entry(right, width=22)
        self.start_entry.insert(0, "09:00")
        self.start_entry.pack(anchor="w", pady=(0, 6))

        ttk.Label(right, text="Duration (minutes):").pack(anchor="w")
        self.duration_box = ttk.Combobox(
            right, width=19, values=["30", "45", "60", "90", "120", "180", "240"])
        self.duration_box.set("60")
        self.duration_box.pack(anchor="w", pady=(0, 10))

        ttk.Button(right, text="Book Resource", command=self.book
                   ).pack(fill="x", pady=4)

        ttk.Label(right, text="Already booked on this date:").pack(anchor="w", pady=(10, 2))
        self.slots_list = tk.Listbox(right, height=7, width=36)
        self.slots_list.pack(anchor="w")

    def selected_resource_id(self):
        selection = self.res_tree.selection()
        if not selection:
            return None
        return self.resource_ids.get(selection[0])

    def refresh_resources(self):
        """Reload the resource list with real-time availability."""
        chosen = self.res_tree.selection()
        clear_table(self.res_tree)
        self.resource_ids = {}
        statuses = get_resource_statuses(self.app.campus.campus_id)
        for res in get_resources(self.app.campus.campus_id):
            iid = str(res.resource_id)
            self.resource_ids[iid] = res.resource_id
            self.res_tree.insert("", "end", iid=iid, values=(
                res.code, res.name, res.resource_type, statuses[res.resource_id]))
        if chosen and self.res_tree.exists(chosen[0]):
            self.res_tree.selection_set(chosen[0])

    def auto_refresh(self):
        """Refresh availability every 30 seconds ("real-time" display)."""
        try:
            if self.res_tree.winfo_exists():
                self.refresh_resources()
                self.res_tree.after(30000, self.auto_refresh)
        except tk.TclError:
            pass

    def show_slots(self):
        """List bookings already made for the selected resource and date."""
        self.slots_list.delete(0, "end")
        resource_id = self.selected_resource_id()
        if resource_id is None:
            return
        selection = self.res_tree.selection()[0]
        values = self.res_tree.item(selection, "values")
        self.selected_label.config(text=f"Selected: {values[0]} - {values[1]}")
        try:
            slots = get_booked_slots(resource_id, self.date_entry.get())
        except BookingError:
            return
        if not slots:
            self.slots_list.insert("end", "(no bookings - fully free)")
        for slot in slots:
            self.slots_list.insert("end", slot)

    def book(self):
        try:
            create_booking(
                self.app.user, self.app.campus.campus_id, self.selected_resource_id(),
                self.date_entry.get(), self.start_entry.get(), self.duration_box.get())
        except BookingError as error:
            messagebox.showerror("Booking not allowed", str(error))
            return
        messagebox.showinfo("Booking confirmed", "Your booking has been saved.")
        self.show_slots()
        self.refresh_resources()
        self.refresh_my_bookings()

    # ---- My bookings ----
    def build_my_tab(self):
        ttk.Label(self.my_tab, text="Active (upcoming) bookings",
                  font=("Arial", 11, "bold")).pack(anchor="w")
        columns, widths = booking_columns(show_lecturer=False)
        frame, self.active_tree = make_table(self.my_tab, columns, widths, height=7)
        frame.pack(fill="both", expand=True)
        ttk.Button(self.my_tab, text="Cancel Selected Booking",
                   command=self.cancel).pack(anchor="e", pady=5)

        ttk.Label(self.my_tab, text="Booking history (past and cancelled)",
                  font=("Arial", 11, "bold")).pack(anchor="w")
        frame, self.history_tree = make_table(self.my_tab, columns, widths, height=7)
        frame.pack(fill="both", expand=True)

    def refresh_my_bookings(self):
        active, history = get_user_bookings(self.app.user.user_id)
        fill_bookings_table(self.active_tree, active, show_lecturer=False)
        fill_bookings_table(self.history_tree, history, show_lecturer=False)

    def cancel(self):
        selection = self.active_tree.selection()
        if not selection:
            messagebox.showwarning("Cancel booking", "Select an active booking first.")
            return
        if not messagebox.askyesno("Confirm", "Cancel the selected booking?"):
            return
        try:
            cancel_booking(self.app.user, int(selection[0]))
        except BookingError as error:
            messagebox.showerror("Cannot cancel", str(error))
            return
        messagebox.showinfo("Cancelled", "The booking was cancelled.")
        self.refresh_my_bookings()
        self.refresh_resources()
        self.show_slots()


# ---------------------------------------------------------------------
# Report text helpers
# ---------------------------------------------------------------------
def format_campus_report(name, report):
    lines = [f"CAMPUS REPORT: {name}", "=" * 50,
             f"Total bookings (not cancelled): {report['total']}",
             f"Cancelled bookings:             {report['cancelled']}",
             f"Average booking duration:       {report['average_duration']:.0f} minutes",
             f"Total hours booked:             {report['total_hours']:.1f}",
             "", "Most frequently used resources:"]
    if report["most_used"]:
        for rank, (label, count) in enumerate(report["most_used"], start=1):
            lines.append(f"  {rank}. {label}  ({count} bookings)")
    else:
        lines.append("  (no bookings yet)")
    lines += ["", "Usage trend - bookings per weekday:"]
    peak = max(report["weekdays"].values()) or 1
    for day, count in report["weekdays"].items():
        lines.append(f"  {day:<10} {'#' * round(20 * count / peak):<20} {count}")
    lines += ["", "Bookings per resource:"]
    for label, count in report["usage"]:
        lines.append(f"  {label}: {count}")
    return "\n".join(lines)


def make_text_box(parent):
    """Read-only style text box with scrollbar."""
    frame = ttk.Frame(parent)
    text = tk.Text(frame, wrap="word", font=("Courier", 10), height=20)
    scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    text.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return frame, text


def set_text(text_widget, content):
    text_widget.config(state="normal")
    text_widget.delete("1.0", "end")
    text_widget.insert("1.0", content)
    text_widget.config(state="disabled")


# ---------------------------------------------------------------------
# Campus administrator tabs
# ---------------------------------------------------------------------
class AdminView:
    def __init__(self, notebook, app):
        self.app = app
        self.res_tab = ttk.Frame(notebook, padding=10)
        self.book_tab = ttk.Frame(notebook, padding=10)
        self.report_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.res_tab, text="Manage Resources")
        notebook.add(self.book_tab, text="Campus Bookings")
        notebook.add(self.report_tab, text="Reports & Usage Trends")
        self.build_resources()
        self.build_bookings()
        self.build_reports()
        self.refresh_all()

    def refresh_all(self):
        self.refresh_resources()
        self.refresh_bookings()
        self.refresh_report()

    # ---- Resources ----
    def build_resources(self):
        frame, self.res_tree = make_table(
            self.res_tab, ["Code", "Name", "Type", "Status"], [100, 180, 180, 160],
            height=10)
        frame.pack(fill="both", expand=True)
        self.res_tree.bind("<<TreeviewSelect>>", lambda e: self.load_selected())

        form = ttk.LabelFrame(self.res_tab, text="Add / update resource", padding=10)
        form.pack(fill="x", pady=8)
        self.code_entry = ttk.Entry(form, width=14)
        self.name_entry = ttk.Entry(form, width=22)
        self.type_entry = ttk.Combobox(form, width=22, values=[
            "Computer Laboratory", "Multimedia Projector", "Seminar Room",
            "Presentation Equipment"])
        self.available_var = tk.BooleanVar(value=True)
        for col, (label, widget) in enumerate([("Code", self.code_entry),
                                               ("Name", self.name_entry),
                                               ("Type", self.type_entry)]):
            ttk.Label(form, text=label).grid(row=0, column=col, sticky="w", padx=4)
            widget.grid(row=1, column=col, padx=4)
        ttk.Checkbutton(form, text="Available for booking",
                        variable=self.available_var).grid(row=1, column=3, padx=8)

        buttons = ttk.Frame(self.res_tab)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Add Resource", command=self.add).pack(side="left", padx=3)
        ttk.Button(buttons, text="Update Selected", command=self.update).pack(side="left", padx=3)
        ttk.Button(buttons, text="Remove Selected", command=self.remove).pack(side="left", padx=3)
        ttk.Button(buttons, text="Clear Form", command=self.clear_form).pack(side="left", padx=3)

    def refresh_resources(self):
        clear_table(self.res_tree)
        statuses = get_resource_statuses(self.app.campus.campus_id)
        self.resources = {}
        for res in get_resources(self.app.campus.campus_id):
            self.resources[str(res.resource_id)] = res
            self.res_tree.insert("", "end", iid=str(res.resource_id), values=(
                res.code, res.name, res.resource_type, statuses[res.resource_id]))

    def clear_form(self):
        self.code_entry.config(state="normal")
        self.code_entry.delete(0, "end")
        self.name_entry.delete(0, "end")
        self.type_entry.set("")
        self.available_var.set(True)

    def load_selected(self):
        selection = self.res_tree.selection()
        if not selection:
            return
        res = self.resources[selection[0]]
        self.clear_form()
        self.code_entry.insert(0, res.code)
        self.code_entry.config(state="disabled")
        self.name_entry.insert(0, res.name)
        self.type_entry.set(res.resource_type)
        self.available_var.set(res.available)

    def selected_id(self):
        selection = self.res_tree.selection()
        if not selection:
            messagebox.showwarning("Select resource", "Select a resource in the table first.")
            return None
        return int(selection[0])

    def add(self):
        if str(self.code_entry.cget("state")) == "disabled":
            messagebox.showinfo("Add resource", "Click 'Clear Form' and enter the new resource details.")
            return
        try:
            add_resource(self.app.campus.campus_id, self.code_entry.get(),
                                  self.name_entry.get(), self.type_entry.get())
        except BookingError as error:
            messagebox.showerror("Cannot add resource", str(error))
            return
        messagebox.showinfo("Added", "Resource registered.")
        self.clear_form()
        self.refresh_all()

    def update(self):
        resource_id = self.selected_id()
        if resource_id is None:
            return
        try:
            update_resource(resource_id, self.name_entry.get(),
                                     self.type_entry.get(), self.available_var.get())
        except BookingError as error:
            messagebox.showerror("Cannot update", str(error))
            return
        messagebox.showinfo("Updated", "Resource updated.")
        self.refresh_all()

    def remove(self):
        resource_id = self.selected_id()
        if resource_id is None:
            return
        if not messagebox.askyesno("Confirm", "Remove the selected resource?"):
            return
        try:
            remove_resource(resource_id)
        except BookingError as error:
            messagebox.showerror("Cannot remove", str(error))
            return
        self.clear_form()
        self.refresh_all()

    def build_bookings(self):
        columns, widths = booking_columns(show_campus=False)
        frame, self.booking_tree = make_table(self.book_tab, columns, widths, height=18)
        frame.pack(fill="both", expand=True)
        ttk.Button(self.book_tab, text="Refresh", command=self.refresh_all
                   ).pack(pady=5)

    def refresh_bookings(self):
        fill_bookings_table(self.booking_tree,
                            get_campus_bookings(self.app.campus.campus_id),
                            show_campus=False)

    def build_reports(self):
        frame, self.report_text = make_text_box(self.report_tab)
        frame.pack(fill="both", expand=True)
        ttk.Button(self.report_tab, text="Refresh Report", command=self.refresh_all
                   ).pack(pady=5)

    def refresh_report(self):
        report = campus_report(self.app.campus.campus_id)
        set_text(self.report_text, format_campus_report(self.app.campus.name, report))


# ---------------------------------------------------------------------
# Operator tabs
# ---------------------------------------------------------------------

class OperatorView:
    def __init__(self, notebook, app):
        self.app = app
        self.book_tab = ttk.Frame(notebook, padding=10)
        self.res_tab = ttk.Frame(notebook, padding=10)
        self.report_tab = ttk.Frame(notebook, padding=10)
        self.compare_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.book_tab, text="All Bookings")
        notebook.add(self.res_tab, text="All Resources")
        notebook.add(self.report_tab, text="Campus Report")
        notebook.add(self.compare_tab, text="Cross-Campus Comparison")
        self.build_bookings()
        self.build_resources()
        self.build_report()
        self.build_compare()
        self.refresh_all()

    def refresh_all(self):
        self.refresh_bookings()
        self.refresh_resources()
        self.refresh_report()
        self.refresh_compare()

    def build_bookings(self):
        columns, widths = booking_columns()
        frame, self.booking_tree = make_table(self.book_tab, columns, widths, height=18)
        frame.pack(fill="both", expand=True)
        ttk.Button(self.book_tab, text="Refresh", command=self.refresh_all).pack(pady=5)

    def refresh_bookings(self):
        fill_bookings_table(self.booking_tree, get_all_bookings())

    def build_resources(self):
        frame, self.res_tree = make_table(
            self.res_tab, ["Campus", "Code", "Name", "Type", "Status"],
            [110, 100, 170, 170, 150], height=18)
        frame.pack(fill="both", expand=True)

    def refresh_resources(self):
        clear_table(self.res_tree)
        for campus in load_campuses().values():
            statuses = get_resource_statuses(campus.campus_id)
            for res in get_resources(campus.campus_id):
                self.res_tree.insert("", "end", values=(
                    campus.name, res.code, res.name, res.resource_type,
                    statuses[res.resource_id]))

    def build_report(self):
        ttk.Label(self.report_tab,
                  text="Report for the active campus (use 'Change Campus' to switch).",
                  foreground="gray").pack(anchor="w")
        frame, self.report_text = make_text_box(self.report_tab)
        frame.pack(fill="both", expand=True)

    def refresh_report(self):
        report = campus_report(self.app.campus.campus_id)
        set_text(self.report_text, format_campus_report(self.app.campus.name, report))

    def build_compare(self):
        columns = ["Campus", "Bookings", "Avg min", "Total hrs", "Resources",
                   "Bookings/resource", "Top resource", "Max session", "Hours", "Weekends"]
        widths = [100, 65, 60, 65, 70, 105, 170, 80, 100, 70]
        frame, self.compare_tree = make_table(self.compare_tab, columns, widths, height=5)
        frame.pack(fill="x")
        ttk.Label(self.compare_tab, text="Observations on usage and campus rules:",
                  font=("Arial", 11, "bold")).pack(anchor="w", pady=(10, 2))
        frame, self.compare_text = make_text_box(self.compare_tab)
        frame.pack(fill="both", expand=True)
        ttk.Button(self.compare_tab, text="Refresh", command=self.refresh_all).pack(pady=5)

    def refresh_compare(self):
        rows = comparison_report()
        clear_table(self.compare_tree)
        for r in rows:
            top = r["most_used"][0][0] if r["most_used"] else "-"
            policy = r["policy"]
            self.compare_tree.insert("", "end", values=(
                r["campus"], r["total"], f"{r['average_duration']:.0f}",
                f"{r['total_hours']:.1f}", r["resource_count"],
                f"{r['bookings_per_resource']:.2f}", top,
                f"{policy.max_minutes} min", f"{policy.open_time}-{policy.close_time}",
                "Yes" if policy.weekends_allowed else "No"))
        lines = ["- " + note for note in comparison_insights(rows)]
        set_text(self.compare_text, "\n".join(lines))


# ---------------------------------------------------------------------
# Run MAIN
# ---------------------------------------------------------------------



def main():
    init_database()      
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
