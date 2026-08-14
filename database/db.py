"""Database layer for the Business Data Automation System.

Provides connection helpers, schema initialization, seeding, and a small
email validation utility used by the dashboard stats.
"""

import re
import sqlite3
from pathlib import Path

# ------------------------------------------------------------------ #
# Paths                                                               #
# ------------------------------------------------------------------ #

# Store the SQLite file next to the project root.
DB_PATH = Path(__file__).resolve().parent.parent / "business_data.db"

# A pragmatic email pattern used to flag invalid addresses on the dashboard.
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# Phone numbers: optional leading +, then digits with spaces / dots / dashes
# / parentheses. Requires at least 7 digits total (roughly 8+ characters).
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s().\-]{6,19}$")


# ------------------------------------------------------------------ #
# Connection                                                          #
# ------------------------------------------------------------------ #

def get_db():
    """Return a SQLite connection with row access by name and foreign keys on."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ------------------------------------------------------------------ #
# Schema                                                              #
# ------------------------------------------------------------------ #

def init_db():
    """Create all tables if they do not already exist."""
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                name  TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT,
                city  TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin      INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Seed data                                                           #
# ------------------------------------------------------------------ #

def seed_db():
    """Insert sample customers for development.

    The sample data intentionally includes duplicate emails and invalid
    email addresses so the dashboard metrics are meaningful from the start.
    """
    conn = get_db()
    try:
        row = conn.execute("SELECT COUNT(*) AS count FROM customers").fetchone()
        if row["count"] > 0:
            return  # already seeded

        sample = [
            ("Ayesha Khan",    "ayesha.khan@example.com",   "+92 300 1112233", "Karachi"),
            ("Bilal Ahmed",    "bilal.ahmed@example.com",   "+92 321 2223344", "Lahore"),
            ("Catherine Rao",  "catherine.rao@example.com",  "+1 555 010 0201", "New York"),
            ("Danish Iqbal",   "danish.iqbal@example.com",   "+92 333 3334455", "Karachi"),
            ("Eman Ali",       "eman.ali@example.com",       "+92 311 4445566", "Islamabad"),
            ("Faraz Shah",     "faraz.shah@example.com",     "+92 345 5556677", "Lahore"),
            ("Ayesha Khan",    "ayesha.khan@example.com",    "+92 301 6667788", "Faisalabad"),
            ("Ghulam Abbas",   "ghulam.abbas@example.com",   "+92 302 7778899", "Multan"),
            ("Hina Naveed",    "hina.naveed@example.com",    "+92 333 8889900", "Karachi"),
            ("Imran Qureshi",  "imran.qureshi@example.com",  "+92 300 9990011", "Peshawar"),
            ("Javeria Malik",  "javeria.malik@example.com",  "+92 321 0001122", "Islamabad"),
            ("Bilal Ahmed",    "bilal.ahmed@example.com",    "+92 303 1112233", "Rawalpindi"),
            ("Komal Saeed",    "komal.saeed@example.com",    "+92 345 1223344", "Karachi"),
            ("Laraib Fatima",  "laraib.fatima@example.com",  "+92 311 1334455", "Hyderabad"),
            ("Moiz Raza",      "moiz.raza@example.com",      "+92 300 1445566", "Lahore"),
            ("Nimra Anjum",    "nimra.anjum@example.com",    "+92 333 1556677", "Faisalabad"),
            ("Omar Farooq",    "omar.farooq@example.com",    "+92 302 1667788", "Karachi"),
            ("Pakeeza Noor",   "pakeeza.noor@example.com",   "+92 321 1778899", "Quetta"),
            ("Qasim Javed",    "qasim.javed@example.com",    "+92 303 1889900", "Lahore"),
            ("Rania Tariq",    "rania.tariq@example.com",    "+92 345 1990011", "Karachi"),
            ("Sana Ullah",     "sana.ullah@example.com",     "+92 311 2001122", "Multan"),
            ("Taimoor Khan",   "taimoor.khan@example.com",   "+92 300 2112233", "Peshawar"),
            ("Uzma Aslam",     "uzma.aslam@example.com",     "+92 333 2223344", "Islamabad"),
            ("Waqar Younis",   "waqar.younis@example.com",   "+92 302 2334455", "Karachi"),
            ("Yasir Arafat",   "yasir.arafat@example.com",   "+92 321 2445566", "Lahore"),
            ("Zainab Bibi",    "zainab.bibi@example.com",    "+92 345 2556677", "Rawalpindi"),
            ("Ahmed Raza",     "ahmed.raza@invalid-email",   "+92 300 2667788", "Karachi"),
            ("Sadia Malik",    "sadia.malik@bad-domain",     "+92 333 2778899", "Lahore"),
            ("Hamza Ali",      "hamza.ali@example.com",      "+92 302 2889900", "Islamabad"),
            ("Farhana Shaikh", "farhana.shaikh@example.com", "+92 311 2990011", "Karachi"),
        ]

        conn.executemany(
            "INSERT INTO customers (name, email, phone, city) VALUES (?, ?, ?, ?)",
            sample,
        )
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def is_valid_email(email):
    """Return True when the address looks like a valid email."""
    if not email:
        return False
    return bool(EMAIL_PATTERN.match(email.strip()))


def is_valid_phone(phone):
    """Return True when the phone number looks plausible.

    Allows an optional country code and digits separated by spaces, dots,
    dashes, or parentheses. Empty values return False (callers treat blanks
    as a separate "missing data" case).
    """
    if not phone:
        return False
    return bool(PHONE_PATTERN.match(str(phone).strip()))


# ------------------------------------------------------------------ #
# User helpers                                                        #
# ------------------------------------------------------------------ #

def get_user_by_email(email):
    """Return the user row matching ``email`` (case-insensitive) or None."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE LOWER(email) = LOWER(?)",
            (email,),
        ).fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id):
    """Return the user row matching ``user_id`` or None."""
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()


def create_user(name, email, password_hash, is_admin=False):
    """Insert a new user and return its id.

    Raises sqlite3.IntegrityError when the email already exists.
    """
    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO users (name, email, password_hash, is_admin)
            VALUES (?, ?, ?, ?)
            """,
            (name, email, password_hash, 1 if is_admin else 0),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()
