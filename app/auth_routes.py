from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, g
)
from werkzeug.security import check_password_hash
from app.database import get_db_connection
import re
import sqlite3
from werkzeug.security import generate_password_hash

auth = Blueprint("auth", __name__, url_prefix="/auth")

def get_dashboard_url(role):
    dashboards = {
        "Admin": "admin_dashboard",
        "Examiner": "examiner_dashboard",
        "Student": "student_dashboard"
    }
    return url_for(dashboards[role])

@auth.before_app_request
def load_logged_in_user():
    from app.auth import load_user
    load_user()

@auth.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user") is not None:
        return redirect(url_for("index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        error = None
        db = get_db_connection()
        user = db.execute(
            """
            SELECT user_id, name, email, password_hash, role, is_active
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()
        if not email or not password:
            error = "Email and password are required."
        elif user is None or not check_password_hash(user["password_hash"], password):
            error = "Invalid email or password."
        elif not user["is_active"]:
            error = "Your account has been deactivated."
        if error:
            flash(error, "danger")
        else:
            session.clear()
            session["user_id"] = user["user_id"]
            flash(f"Welcome, {user['name']}!", "success")
            return redirect(get_dashboard_url(user["role"]))
    return render_template("login.html")

@auth.route("/register/<role>", methods=["GET", "POST"])
def register(role):
    if role not in ("Student", "Examiner"):
        return redirect(url_for("index"))
    if g.get("user") is not None:
        return redirect(url_for("index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        department = request.form.get("department", "").strip()
        enrollment_number = request.form.get("enrollment_number", "").strip()
        designation = request.form.get("designation", "").strip()
        semester_raw = request.form.get("semester", "").strip()
        error = None
        if not name or len(name) > 100:
            error = "Enter a valid name (maximum 100 characters)."
        # elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        #     error = "Enter a valid email address."
        # this has been commented out because the email validation is disabled for development purposes can be enabled by uncommenting the above lines and reenabling the same in login.html as well. password below has been changed to minimum 1 character for development purposes can be changed to 8 characters by changing the below line and the same in create_admin.py
        elif len(password) < 1:
            error = "Password must contain at least 8 characters."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif not department:
            error = "Department is required."
        elif role == "Student" and not enrollment_number:
            error = "Enrollment number is required."
        elif role == "Examiner" and not designation:
            error = "Designation is required."
        semester = None
        if not error and role == "Student":
            try:
                semester = int(semester_raw)
                if semester <= 0:
                    raise ValueError
            except ValueError:
                error = "Enter a valid positive semester number."
        if error:
            flash(error, "danger")
            return render_template("register.html", role=role)
        db = get_db_connection()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT user_id FROM users WHERE email = ?",
                (email,)
            ).fetchone()
            if existing:
                db.rollback()
                flash("An account with this email already exists.", "danger")
                return render_template("register.html", role=role)
            cursor = db.execute(
                """
                INSERT INTO users (name, email, password_hash, role)
                VALUES (?, ?, ?, ?)
                """,
                (name, email, generate_password_hash(password), role)
            )
            user_id = cursor.lastrowid
            if role == "Student":
                db.execute(
                    """
                    INSERT INTO student_profiles
                    (user_id, enrollment_number, department, semester)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, enrollment_number, department, semester)
                )
            else:
                db.execute(
                    """
                    INSERT INTO examiner_profiles
                    (user_id, department, designation)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, department, designation)
                )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            flash(
                "Registration failed. The email, enrollment number or "
                "Employee may already be registered.",
                "danger"
            )
            return render_template("register.html", role=role)
        flash(
            "Registration successful. Your examiner account requires "
            "administrator approval." if role == "Examiner"
            else "Registration successful. You can now log in.",
            "success"
        )
        return redirect(url_for("auth.login"))
    return render_template("register.html", role=role)

@auth.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))