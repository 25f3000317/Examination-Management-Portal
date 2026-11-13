from app import app
from flask import render_template, g
from app.auth import login_required, role_required

@app.route('/')
def index():
    return render_template('index.html', portal_name="Examination Management Portal", description="manage examinations, bookings and evaluations", version="1.0", maintenance=False)

@app.route('/about')
def about():
    return render_template('about.html', portal_name="Examination Management Portal", description="manage examinations, bookings and evaluations", version="1.0", maintenance=False)

@app.route("/admin/dashboard")
@login_required
@role_required("Admin")
def admin_dashboard():
    return render_template("admin_dashboard.html")

@app.route("/examiner/dashboard")
@login_required
@role_required("Examiner")
def examiner_dashboard():
    return render_template("examiner_dashboard.html")

@app.route("/student/dashboard")
@login_required
@role_required("Student")
def student_dashboard():
    return render_template("student_dashboard.html")