from functools import wraps
from flask import g, redirect, url_for, flash, session

def load_user():
    from app.database import get_db_connection
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
        return
    db = get_db_connection()
    user = db.execute(
        """
        SELECT user_id, name, email, role, is_active
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()
    if user is None or not user["is_active"]:
        session.clear()
        g.user = None
        return
    g.user = user

def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.get("user") is None:
            flash("Please log in to access that page.", "warning")
            return redirect(url_for("auth.login"))
        return view(**kwargs)

    return wrapped_view

def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(**kwargs):
            if g.get("user") is None:
                flash("Please log in first.", "warning")
                return redirect(url_for("auth.login"))
            if g.user["role"] not in roles:
                flash("You do not have permission to access that page.", "danger")
                return redirect(url_for("index"))
            if g.user["role"] == "Examiner":
                from app.database import get_db_connection
                examiner = get_db_connection().execute(
                    """
                    SELECT approval_status
                    FROM examiner_profiles
                    WHERE user_id = ?
                    """,
                    (g.user["user_id"],)
                ).fetchone()
                if examiner is None or examiner["approval_status"] != "Approved":
                    flash("Your examiner account is awaiting approval.", "warning")
                    return redirect(url_for("index"))
            return view(**kwargs)
        return wrapped_view
    return decorator
