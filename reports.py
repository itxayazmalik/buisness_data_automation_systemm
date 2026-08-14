"""Analytics and chart datasets for the reports dashboard.

All report data is derived live from the customers table so the numbers
always match the other modules (validation, duplicates, cleaning).
"""

from collections import Counter

from validation import validation_report


def _duplicate_records(conn):
    return conn.execute(
        """
        SELECT COUNT(*)
        FROM customers
        WHERE email IN (
            SELECT email
            FROM customers
            GROUP BY email
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]


def _city_distribution(conn):
    """Top cities by record count; overflow buckets collapse into 'Other'."""
    rows = conn.execute(
        """
        SELECT city, COUNT(*) AS count
        FROM customers
        WHERE city IS NOT NULL AND TRIM(city) != ''
        GROUP BY city
        ORDER BY count DESC, city COLLATE NOCASE ASC
        """
    ).fetchall()

    distribution = [{"label": row["city"], "value": row["count"]} for row in rows]

    if len(distribution) > 6:
        top = distribution[:5]
        other = sum(item["value"] for item in distribution[5:])
        top.append({"label": "Other", "value": other})
        distribution = top

    return distribution


def _customer_growth(conn):
    """Cumulative record count over insertion order (no date column exists).

    Records are grouped by ID range into up to ten buckets; the value of each
    bucket is the running total. Labeled by record range as a proxy timeline.
    """
    ids = [row[0] for row in conn.execute("SELECT id FROM customers ORDER BY id ASC")]
    total = len(ids)
    if total == 0:
        return []

    bucket_size = max(1, (total + 9) // 10)
    growth = []
    for start in range(0, total, bucket_size):
        end = min(start + bucket_size, total)
        growth.append(
            {
                "label": f"#{ids[start]}-{ids[end - 1]}",
                "value": end,
            }
        )
    return growth


def _quality_metrics(validation):
    """Per-metric issue counts used by the Data Quality bar chart."""
    counter = Counter()
    for record in validation["missing_records"]:
        counter.update(record["missing"])

    return [
        {"label": "Missing Name", "value": counter["name"]},
        {"label": "Missing Email", "value": counter["email"]},
        {"label": "Missing Phone", "value": counter["phone"]},
        {"label": "Missing City", "value": counter["city"]},
        {"label": "Invalid Emails", "value": len(validation["invalid_emails"])},
        {"label": "Invalid Phones", "value": len(validation["invalid_phones"])},
    ]


def _validation_summary(validation):
    """Unique record count with at least one issue, versus fully valid."""
    issue_ids = set()
    for record in validation["invalid_emails"]:
        issue_ids.add(record["id"])
    for record in validation["invalid_phones"]:
        issue_ids.add(record["id"])
    for record in validation["missing_records"]:
        issue_ids.add(record["id"])

    with_issues = len(issue_ids)
    return {
        "valid": max(0, validation["total_records"] - with_issues),
        "with_issues": with_issues,
    }


def _quality_score(validation):
    """Completeness + validity as a 0–100 score.

    Each record has four fields (name, email, phone, city). Points are lost
    for missing cells and for invalid emails / invalid phone numbers.
    """
    total = validation["total_records"]
    if total == 0:
        return 100.0

    missing_cells = sum(len(record["missing"]) for record in validation["missing_records"])
    invalid = len(validation["invalid_emails"]) + len(validation["invalid_phones"])

    cells = total * 4
    lost = min(missing_cells + invalid, cells)
    return round((1 - lost / cells) * 100, 1)


def _grade(score):
    if score >= 90:
        return ("Excellent", "success")
    if score >= 75:
        return ("Good", "primary")
    if score >= 50:
        return ("Fair", "amber")
    return ("Needs Attention", "danger")


def get_report_data(conn):
    """Assemble every metric and chart dataset for the reports page."""
    validation = validation_report(conn)
    summary = _validation_summary(validation)
    score = _quality_score(validation)
    grade_label, grade_color = _grade(score)

    total_customers = validation["total_records"]
    missing_fields = sum(
        len(record["missing"]) for record in validation["missing_records"]
    )

    return {
        "total_customers": total_customers,
        "total_cities": conn.execute(
            """
            SELECT COUNT(DISTINCT city)
            FROM customers
            WHERE city IS NOT NULL AND TRIM(city) != ''
            """
        ).fetchone()[0],
        "duplicate_records": _duplicate_records(conn),
        "invalid_emails": len(validation["invalid_emails"]),
        "missing_fields": missing_fields,
        "quality_score": score,
        "quality_grade": grade_label,
        "quality_grade_color": grade_color,
        "records_with_issues": summary["with_issues"],
        "city_distribution": _city_distribution(conn),
        "customer_growth": _customer_growth(conn),
        "quality_metrics": _quality_metrics(validation),
        "validation_summary": [
            {"label": "Valid", "value": summary["valid"]},
            {"label": "With Issues", "value": summary["with_issues"]},
        ],
    }
