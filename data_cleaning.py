"""Pandas-powered data operations: CSV import and the data cleaning pipeline.

CSV import
    Validates the file, normalizes headers, enforces unique + valid emails,
    and writes clean rows to SQLite. Returns a per-run summary dict.

Data cleaning center
    Detects data quality issues (missing values, extra whitespace,
    non-lowercase emails, non-standard city names, empty rows) and applies
    fixes in place. Both a read-only preview and an applying run are exposed.
"""

import pandas as pd

from database.db import is_valid_email

# ------------------------------------------------------------------ #
# Column handling                                                     #
# ------------------------------------------------------------------ #

EXPECTED_HEADER = "ID,Name,Email,Phone,City"
TEXT_COLUMNS = ["name", "email", "phone", "city"]


def _collapse_spaces(value):
    """Trim a value and collapse internal runs of whitespace."""
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split())


def _clean_city(value):
    """Normalize a city name: trim, collapse spaces, then title-case."""
    return _collapse_spaces(value).title()


# ------------------------------------------------------------------ #
# CSV import                                                          #
# ------------------------------------------------------------------ #

def import_customers(conn, uploaded_file):
    """Read a CSV upload and store valid rows in the customers table.

    Raises ValueError with a user-facing message on format problems.
    Returns a summary dict describing what happened per row.
    """
    filename = (uploaded_file.filename or "").strip()
    if not filename.lower().endswith(".csv"):
        raise ValueError("Invalid file type. Please upload a CSV (.csv) file.")

    try:
        df = pd.read_csv(uploaded_file, dtype=str, keep_default_na=False)
    except Exception:
        raise ValueError("Could not read the file. Make sure it is a well-formed CSV file.")

    if df.empty:
        raise ValueError("The CSV file contains no data rows.")

    df.columns = [str(c).strip() for c in df.columns]
    header_map = {c.lower(): c for c in df.columns}

    missing = sorted({"name", "email"} - set(header_map))
    if missing:
        raise ValueError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Expected header: {EXPECTED_HEADER}"
        )

    name_col = header_map["name"]
    email_col = header_map["email"]
    phone_col = header_map.get("phone")
    city_col = header_map.get("city")

    # Email uniqueness is checked against the DB and against earlier rows
    # in the same file (case-insensitive).
    seen = {row[0] for row in conn.execute("SELECT email FROM customers")}

    summary = {
        "total_rows": len(df),
        "imported": 0,
        "duplicates_skipped": 0,
        "invalid_emails_skipped": 0,
        "empty_rows_skipped": 0,
    }

    for _, row in df.iterrows():
        name = _collapse_spaces(row.get(name_col))
        email_raw = str(row.get(email_col)).strip()
        email = email_raw.lower()

        if not name and not email:
            summary["empty_rows_skipped"] += 1
            continue
        if not is_valid_email(email):
            summary["invalid_emails_skipped"] += 1
            continue
        if email in seen:
            summary["duplicates_skipped"] += 1
            continue

        seen.add(email)
        phone = _collapse_spaces(row.get(phone_col)) if phone_col else ""
        city = _collapse_spaces(row.get(city_col)) if city_col else ""

        conn.execute(
            "INSERT INTO customers (name, email, phone, city) VALUES (?, ?, ?, ?)",
            (name, email_raw, phone, city),
        )
        summary["imported"] += 1

    conn.commit()
    return summary


# ------------------------------------------------------------------ #
# Data cleaning center                                                #
# ------------------------------------------------------------------ #

def _load_customers(conn):
    df = pd.read_sql_query("SELECT * FROM customers", conn)
    if not df.empty:
        for col in TEXT_COLUMNS:
            df[col] = df[col].fillna("").astype(str)
    return df


def detect_issues(conn):
    """Read-only report of data quality problems in the customers table."""
    df = _load_customers(conn)

    if df.empty:
        return {
            "total_records": 0,
            "missing_values": 0,
            "missing_by_column": {col: 0 for col in TEXT_COLUMNS},
            "empty_rows": 0,
            "emails_not_lowercase": 0,
            "extra_spaces": 0,
            "cities_nonstandard": 0,
            "formatting_issues": 0,
            "has_issues": False,
        }

    missing_by_column = {
        col: int((df[col].str.strip() == "").sum()) for col in TEXT_COLUMNS
    }
    missing_values = sum(missing_by_column.values())

    empty_rows = int(
        ((df["name"].str.strip() == "") & (df["email"].str.strip() == "")).sum()
    )

    emails_not_lowercase = int(
        (df["email"].str.strip() != df["email"].str.strip().str.lower()).sum()
    )

    extra_spaces = sum(
        int((df[col] != df[col].map(_collapse_spaces)).sum())
        for col in TEXT_COLUMNS
    )

    cities_nonstandard = int((df["city"].map(_clean_city) != df["city"]).sum())

    formatting_issues = emails_not_lowercase + extra_spaces + cities_nonstandard

    return {
        "total_records": len(df),
        "missing_values": missing_values,
        "missing_by_column": missing_by_column,
        "empty_rows": empty_rows,
        "emails_not_lowercase": emails_not_lowercase,
        "extra_spaces": extra_spaces,
        "cities_nonstandard": cities_nonstandard,
        "formatting_issues": formatting_issues,
        "has_issues": bool(missing_values or empty_rows or formatting_issues),
    }


def run_cleaning(conn):
    """Apply the cleaning pipeline to the customers table in place.

    Returns a report dict with counts of what was cleaned.
    """
    df = _load_customers(conn)

    report = {
        "total_before": len(df),
        "records_cleaned": 0,
        "missing_values": 0,
        "formatting_fixed": 0,
        "empty_rows_removed": 0,
        "spaces_fixed": 0,
        "emails_lowercased": 0,
        "cities_standardized": 0,
        "total_after": len(df),
    }

    if df.empty:
        return report

    report["missing_values"] = sum(
        int((df[col].str.strip() == "").sum()) for col in TEXT_COLUMNS
    )

    before = df[TEXT_COLUMNS].copy()

    # 1. Remove extra spaces.
    for col in TEXT_COLUMNS:
        df[col] = df[col].map(_collapse_spaces)
    # 2. Convert emails to lowercase.
    df["email"] = df["email"].str.lower()
    # 3. Standardize city names.
    df["city"] = df["city"].map(_clean_city)

    # 4. Remove empty rows (both name and email are blank).
    empty_mask = (df["name"] == "") & (df["email"] == "")
    removed_ids = df.loc[empty_mask, "id"].astype(int).tolist()

    keep = df[~empty_mask].reset_index(drop=True)
    keep_before = before[~empty_mask].reset_index(drop=True)

    report["emails_lowercased"] = int((keep_before["email"] != keep["email"]).sum())
    report["cities_standardized"] = int((keep_before["city"] != keep["city"]).sum())
    report["spaces_fixed"] = int(
        (keep_before["name"] != keep["name"]).sum()
        + (keep_before["phone"] != keep["phone"]).sum()
    )

    changed_cells = int((keep_before != keep[TEXT_COLUMNS]).sum().sum())
    report["formatting_fixed"] = changed_cells
    report["records_cleaned"] = int(
        (keep_before != keep[TEXT_COLUMNS]).any(axis=1).sum()
    )
    report["empty_rows_removed"] = len(removed_ids)

    # Persist the cleaned records.
    for _, row in keep.iterrows():
        conn.execute(
            "UPDATE customers SET name = ?, email = ?, phone = ?, city = ? WHERE id = ?",
            (row["name"], row["email"], row["phone"], row["city"], int(row["id"])),
        )
    for row_id in removed_ids:
        conn.execute("DELETE FROM customers WHERE id = ?", (row_id,))
    conn.commit()

    report["total_after"] = len(keep)
    return report
