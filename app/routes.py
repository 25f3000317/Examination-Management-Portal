from app import app
from flask import render_template

@app.route('/')
def index():
    return render_template('index.html', portal_name="Examination Management Portal", description="manage examinations, bookings and evaluations", version="1.0", maintenance=False)

@app.route('/about')
def about():
    return render_template('about.html', portal_name="Examination Management Portal", description="manage examinations, bookings and evaluations", version="1.0", maintenance=False)