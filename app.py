from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from data_cleaning import detect_issues, import_customers, run_cleaning
from database.db import (
    create_user,
    get_db as _get_db,
    get_user_by_email,
    get_user_by_id,
    init_db,
    is_valid_email,
)
from reports import get_report_data
from validation import duplicate_summary, find_duplicates, validation_report

app = Flask(__name__)

# Needed for flash messages and session cookies. Override in production.
app.secret_key = "dev-secret-key-change-in-production"

# Expose the email validator to templates (used on the customer detail page).
app.jinja_env.globals["is_valid_email"] = is_valid_email

# Number of customer rows shown per page.
PER_PAGE = 10

# Default credentials created on first run:  admin@example.com / admin123
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin123"

# ------------------------------------------------------------------ #
# Database helpers                                                    #
# ------------------------------------------------------------------ #


def get_db():
    """Open a connection for the current request and cache it on Flask's g."""
    if "db" not in g:
        g.db = _get_db()
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    """Close the request-scoped database connection."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def current_user():
    """Return the logged-in user row, or None when unauthenticated."""
    user_id = session.get("user_id")
    if user_id is None:
        return None
    return get_user_by_id(user_id)


def login_required(view):
    """Redirect anonymous visitors to the login page."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def ensure_admin_user():
    """Create the default admin account on first launch."""
    if get_user_by_email(ADMIN_EMAIL) is not None:
        return
    create_user(
        "Administrator",
        ADMIN_EMAIL,
        generate_password_hash(ADMIN_PASSWORD),
        is_admin=True,
    )


@app.context_processor
def inject_current_user():
    """Make ``current_user`` available to every template."""
    return {"current_user": current_user()}


# ------------------------------------------------------------------ #
# Authentication                                                     #
# ------------------------------------------------------------------ #


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user() is not None:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        user = get_user_by_email(email)
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
        else:
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            flash(f"Welcome back, {user['name']}!", "success")
            nxt = (request.args.get("next") or "").strip()
            if not nxt.startswith("/"):
                nxt = url_for("dashboard")
            return redirect(nxt)

    return render_template("login.html", active_page="login")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user() is not None:
        return redirect(url_for("dashboard"))

    form = {"name": "", "email": ""}
    error = None

    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["email"] = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        if not form["name"]:
            error = "Name is required."
        elif not is_valid_email(form["email"]):
            error = "Enter a valid email address, e.g. name@example.com."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."
        elif get_user_by_email(form["email"]) is not None:
            error = "An account with this email already exists."

        if error is None:
            user_id = create_user(
                form["name"],
                form["email"],
                generate_password_hash(password),
            )
            session.clear()
            session["user_id"] = user_id
            session["user_name"] = form["name"]
            flash(f"Welcome, {form['name']}! Your account has been created.", "success")
            return redirect(url_for("dashboard"))

    return render_template("register.html", form=form, error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


# ------------------------------------------------------------------ #
# Settings                                                           #
# ------------------------------------------------------------------ #


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = current_user()

    if request.method == "POST":
        form_action = request.form.get("form_action")

        if form_action == "profile":
            name = (request.form.get("name") or "").strip()
            if not name:
                flash("Name cannot be empty.", "error")
            else:
                conn = get_db()
                conn.execute(
                    "UPDATE users SET name = ? WHERE id = ?",
                    (name, user["id"]),
                )
                conn.commit()
                session["user_name"] = name
                flash("Profile updated successfully.", "success")
                return redirect(url_for("settings"))

        elif form_action == "password":
            current_pw = request.form.get("current_password") or ""
            new_pw = request.form.get("new_password") or ""
            confirm_pw = request.form.get("confirm_password") or ""

            if not check_password_hash(user["password_hash"], current_pw):
                flash("Current password is incorrect.", "error")
            elif len(new_pw) < 6:
                flash("New password must be at least 6 characters.", "error")
            elif new_pw != confirm_pw:
                flash("New passwords do not match.", "error")
            else:
                conn = get_db()
                conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new_pw), user["id"]),
                )
                conn.commit()
                flash("Password changed successfully.", "success")
                return redirect(url_for("settings"))

        return redirect(url_for("settings"))

    return render_template("settings.html", user=user, active_page="settings")


def validate_customer(name, email, conn, exclude_id=None):
    """Return a dict of field errors; empty when the input is valid.

    Enforces a required name, a well-formed email, and a unique email.
    ``exclude_id`` ignores the current record so editing keeps its own email.
    """
    errors = {}
    name = (name or "").strip()
    email = (email or "").strip().lower()

    if not name:
        errors["name"] = "Name is required."

    if not email:
        errors["email"] = "Email is required."
    elif not is_valid_email(email):
        errors["email"] = "Enter a valid email address, e.g. name@example.com."
    else:
        sql = "SELECT id FROM customers WHERE email = ?"
        params = [email]
        if exclude_id is not None:
            sql += " AND id != ?"
            params.append(exclude_id)
        if conn.execute(sql, params).fetchone():
            errors["email"] = "A customer with this email already exists."

    return errors


# ------------------------------------------------------------------ #
# Dashboard                                                           #
# ------------------------------------------------------------------ #


@app.route("/")
@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    stats = get_dashboard_stats(conn)

    recent_customers = conn.execute(
        "SELECT * FROM customers ORDER BY id DESC LIMIT 8"
    ).fetchall()

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_customers=recent_customers,
        active_page="dashboard",
    )


def get_dashboard_stats(conn):
    """Compute the four headline metrics shown on the dashboard."""
    total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]

    total_cities = conn.execute(
        """
        SELECT COUNT(DISTINCT city)
        FROM customers
        WHERE city IS NOT NULL AND TRIM(city) != ''
        """
    ).fetchone()[0]

    duplicate_records = conn.execute(
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

    rows = conn.execute("SELECT email FROM customers").fetchall()
    invalid_emails = sum(1 for row in rows if not is_valid_email(row["email"]))

    return {
        "total_customers": total_customers,
        "total_cities": total_cities,
        "duplicate_records": duplicate_records,
        "invalid_emails": invalid_emails,
    }


# ------------------------------------------------------------------ #
# Customers                                                           #
# ------------------------------------------------------------------ #


@app.route("/customers")
@login_required
def customers():
    conn = get_db()

    query = (request.args.get("q") or "").strip()
    page = max(request.args.get("page", 1, type=int), 1)

    where = ""
    params = []
    if query:
        like = f"%{query}%"
        where = """
            WHERE name LIKE ?
               OR email LIKE ?
               OR phone LIKE ?
               OR city LIKE ?
        """
        params = [like, like, like, like]

    total = conn.execute(f"SELECT COUNT(*) FROM customers {where}", params).fetchone()[0]
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, pages)

    customers = conn.execute(
        f"""
        SELECT * FROM customers {where}
        ORDER BY name COLLATE NOCASE ASC
        LIMIT ? OFFSET ?
        """,
        params + [PER_PAGE, (page - 1) * PER_PAGE],
    ).fetchall()

    # Sliding window of page numbers around the current page.
    page_range = range(max(1, page - 2), min(pages, page + 2) + 1)

    return render_template(
        "customers.html",
        customers=customers,
        total=total,
        query=query,
        page=page,
        pages=pages,
        page_range=page_range,
        active_page="customers",
    )


@app.route("/customers/add", methods=["GET", "POST"])
@login_required
def add_customer():
    conn = get_db()

    form = {"name": "", "email": "", "phone": "", "city": ""}

    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["email"] = (request.form.get("email") or "").strip().lower()
        form["phone"] = (request.form.get("phone") or "").strip()
        form["city"] = (request.form.get("city") or "").strip()

        errors = validate_customer(form["name"], form["email"], conn)
        if errors:
            form.update({f"{key}_error": msg for key, msg in errors.items()})
            return render_template(
                "add_customer.html", form=form, active_page="customers"
            )

        conn.execute(
            "INSERT INTO customers (name, email, phone, city) VALUES (?, ?, ?, ?)",
            (form["name"], form["email"], form["phone"], form["city"]),
        )
        conn.commit()
        flash(f'Customer "{form["name"]}" added successfully.', "success")
        return redirect(url_for("customers"))

    return render_template("add_customer.html", form=form, active_page="customers")


@app.route("/customers/<int:customer_id>")
@login_required
def view_customer(customer_id):
    conn = get_db()
    customer = conn.execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()

    if customer is None:
        flash("Customer not found.", "error")
        return redirect(url_for("customers"))

    return render_template(
        "view_customer.html", customer=customer, active_page="customers"
    )


@app.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
@login_required
def edit_customer(customer_id):
    conn = get_db()
    customer = conn.execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()

    if customer is None:
        flash("Customer not found.", "error")
        return redirect(url_for("customers"))

    form = dict(customer)

    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["email"] = (request.form.get("email") or "").strip().lower()
        form["phone"] = (request.form.get("phone") or "").strip()
        form["city"] = (request.form.get("city") or "").strip()

        errors = validate_customer(form["name"], form["email"], conn, exclude_id=customer_id)
        if errors:
            form.update({f"{key}_error": msg for key, msg in errors.items()})
            return render_template(
                "edit_customer.html",
                customer=customer,
                form=form,
                active_page="customers",
            )

        conn.execute(
            """
            UPDATE customers
            SET name = ?, email = ?, phone = ?, city = ?
            WHERE id = ?
            """,
            (form["name"], form["email"], form["phone"], form["city"], customer_id),
        )
        conn.commit()
        flash(f'Customer "{form["name"]}" updated successfully.', "success")
        return redirect(url_for("customers"))

    return render_template(
        "edit_customer.html", customer=customer, form=form, active_page="customers"
    )


@app.route("/customers/<int:customer_id>/delete", methods=["POST"])
@login_required
def delete_customer(customer_id):
    conn = get_db()
    customer = conn.execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()

    if customer is None:
        flash("Customer not found.", "error")
        return redirect(url_for("customers"))

    conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    conn.commit()
    flash(f'Customer "{customer["name"]}" deleted successfully.', "success")
    return redirect(url_for("customers"))


# ------------------------------------------------------------------ #
# CSV import                                                          #
# ------------------------------------------------------------------ #


@app.route("/import", methods=["GET", "POST"])
@login_required
def import_csv():
    summary = None

    if request.method == "POST":
        file = request.files.get("csv_file")

        if file is None or not (file.filename or "").strip():
            flash("Please choose a CSV file to upload.", "error")
        else:
            conn = get_db()
            try:
                summary = import_customers(conn, file)
                flash(
                    f'Imported {summary["imported"]} of {summary["total_rows"]} '
                    f"record(s) from the file.",
                    "success",
                )
            except ValueError as exc:
                flash(str(exc), "error")

    return render_template("import_csv.html", summary=summary, active_page="import")


# ------------------------------------------------------------------ #
# Data cleaning center                                                #
# ------------------------------------------------------------------ #


@app.route("/clean", methods=["GET", "POST"])
@login_required
def clean():
    conn = get_db()
    report = None

    if request.method == "POST":
        report = run_cleaning(conn)
        flash("Data cleaning complete.", "success")

    issues = detect_issues(conn)
    return render_template(
        "cleaning.html",
        report=report,
        issues=issues,
        active_page="clean",
    )


# ------------------------------------------------------------------ #
# Duplicate detection                                                 #
# ------------------------------------------------------------------ #


@app.route("/duplicates", methods=["GET", "POST"])
@login_required
def duplicates():
    conn = get_db()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "remove_all":
            groups = find_duplicates(conn)
            removed = 0
            for group in groups:
                for record_id in group["remove_ids"]:
                    conn.execute("DELETE FROM customers WHERE id = ?", (record_id,))
                    removed += 1
            conn.commit()
            flash(
                f"Removed {removed} duplicate record(s); kept the earliest entry "
                f"for each email.",
                "success",
            )

        elif action == "keep_group":
            email = (request.form.get("email") or "").strip()
            row = conn.execute(
                "SELECT MIN(id) AS keep_id FROM customers WHERE LOWER(email) = ?",
                (email.lower(),),
            ).fetchone()
            if row and row["keep_id"] is not None:
                cursor = conn.execute(
                    "DELETE FROM customers WHERE LOWER(email) = ? AND id != ?",
                    (email.lower(), row["keep_id"]),
                )
                conn.commit()
                flash(
                    f"Removed {cursor.rowcount} duplicate(s) for '{email}'; "
                    f"kept the earliest entry.",
                    "success",
                )
            else:
                flash("No duplicate group found for that email.", "error")

        elif action == "remove_single":
            record_id = request.form.get("record_id", type=int)
            if record_id is None:
                flash("Invalid record reference.", "error")
            else:
                cursor = conn.execute(
                    "DELETE FROM customers WHERE id = ?", (record_id,)
                )
                conn.commit()
                if cursor.rowcount:
                    flash(f"Removed record #{record_id}.", "success")
                else:
                    flash("Record not found.", "error")

        return redirect(url_for("duplicates"))

    groups = find_duplicates(conn)
    summary = duplicate_summary(conn)
    return render_template(
        "duplicates.html",
        groups=groups,
        summary=summary,
        active_page="duplicates",
    )


# ------------------------------------------------------------------ #
# Validation center                                                   #
# ------------------------------------------------------------------ #


@app.route("/validation")
@login_required
def validation():
    conn = get_db()
    report = validation_report(conn)
    return render_template(
        "validation.html",
        report=report,
        active_page="validation",
    )


# ------------------------------------------------------------------ #
# Reports & analytics                                                 #
# ------------------------------------------------------------------ #


@app.route("/reports")
@login_required
def reports():
    conn = get_db()
    report_data = get_report_data(conn)
    return render_template(
        "reports.html",
        report=report_data,
        active_page="reports",
    )


if __name__ == "__main__":
    init_db()
    ensure_admin_user()
    app.run(debug=True, port=5001)
