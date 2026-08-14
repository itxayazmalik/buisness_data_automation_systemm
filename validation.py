"""Duplicate detection and record validation for the quality center.

find_duplicates      Groups customer records that share an email address.
validation_report    Flags invalid emails, invalid phone numbers, and records
                     with missing fields.
"""

from database.db import is_valid_email, is_valid_phone

FIELDS = ["name", "email", "phone", "city"]


# ------------------------------------------------------------------ #
# Duplicate detection                                                 #
# ------------------------------------------------------------------ #

def find_duplicates(conn):
    """Return a list of duplicate groups.

    Each group is a dict with the shared email, the total count of matching
    records, the record list (sorted oldest first), and which ids to keep /
    remove. Grouping is case-insensitive; records with a blank email are
    ignored.
    """
    rows = conn.execute(
        "SELECT * FROM customers ORDER BY email COLLATE NOCASE ASC, id ASC"
    ).fetchall()

    buckets = {}
    for row in rows:
        key = (row["email"] or "").strip().lower()
        if key:
            buckets.setdefault(key, []).append(dict(row))

    groups = []
    for email, records in buckets.items():
        if len(records) < 2:
            continue
        groups.append(
            {
                "email": records[0]["email"],
                "count": len(records),
                "records": records,
                "keep_id": records[0]["id"],
                "remove_ids": [rec["id"] for rec in records[1:]],
            }
        )

    return groups


def duplicate_summary(conn):
    """Aggregate duplicate metrics for report cards."""
    groups = find_duplicates(conn)
    duplicate_records = sum(group["count"] for group in groups)
    removable = sum(len(group["remove_ids"]) for group in groups)
    total = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    return {
        "total_records": total,
        "groups": len(groups),
        "duplicate_records": duplicate_records,
        "removable": removable,
        "clean_records": total - duplicate_records,
    }


# ------------------------------------------------------------------ #
# Validation                                                          #
# ------------------------------------------------------------------ #

def validation_report(conn):
    """Scan every record and split it into invalid / missing buckets."""
    rows = conn.execute("SELECT * FROM customers ORDER BY id ASC").fetchall()

    invalid_emails = []
    invalid_phones = []
    missing_records = []

    for row in rows:
        rec = dict(row)
        email = (rec.get("email") or "").strip()
        phone = (rec.get("phone") or "").strip()

        if email and not is_valid_email(email):
            invalid_emails.append(rec)

        if phone and not is_valid_phone(phone):
            invalid_phones.append(rec)

        missing = [field for field in FIELDS if not (rec.get(field) or "").strip()]
        if missing:
            rec["missing"] = missing
            missing_records.append(rec)

    return {
        "total_records": len(rows),
        "invalid_emails": invalid_emails,
        "invalid_phones": invalid_phones,
        "missing_records": missing_records,
    }
