from app import app
from flask import render_template, g, redirect, url_for, flash, request
from app.auth import login_required, role_required
from app.database import get_db_connection
from datetime import datetime
import sqlite3

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

def get_current_student():
    return get_db_connection().execute("SELECT student_id FROM student_profiles WHERE user_id=?",(g.user["user_id"],)).fetchone()

def student_booking_open(exam):
    now=datetime.now().strftime("%Y-%m-%dT%H:%M")
    return exam["status"]=="Active" and exam["booking_enabled"]==1 and exam["booking_start"]<=now<exam["booking_end"]

@app.route("/student/examinations")
@login_required
@role_required("Student")
def student_examinations():
    db=get_db_connection()
    if not get_current_student():
        flash("Student profile not found.","danger")
        return redirect(url_for("student_dashboard"))
    q=request.args.get("q","").strip()
    course_id=request.args.get("course_id","")
    exam_type=request.args.get("exam_type","")
    conditions=["e.status='Active'","(e.exam_name LIKE ? OR c.course_name LIKE ? OR c.course_code LIKE ? OR CAST(e.exam_id AS TEXT)=?)"]
    params=[f"%{q}%",f"%{q}%",f"%{q}%",q]
    if course_id:
        try:
            course_id=int(course_id)
            conditions.append("e.course_id=?")
            params.append(course_id)
        except ValueError:
            course_id=""
    if exam_type:
        conditions.append("e.exam_type=?")
        params.append(exam_type)
    now=datetime.now().strftime("%Y-%m-%dT%H:%M")
    exams=db.execute(f"""
        SELECT e.*,c.course_name,c.course_code,
        (SELECT COUNT(*) FROM exam_slots s WHERE s.exam_id=e.exam_id AND s.is_active=1 AND s.slot_date||'T'||s.start_time>? AND (SELECT COUNT(*) FROM bookings b WHERE b.slot_id=s.slot_id AND b.booking_status='Active')<s.capacity) AS available_slots
        FROM examinations e JOIN courses c ON c.course_id=e.course_id
        WHERE {" AND ".join(conditions)}
        ORDER BY e.exam_date_start,e.exam_name
    """,(now,*params)).fetchall()
    courses=db.execute("SELECT DISTINCT c.course_id,c.course_name,c.course_code FROM courses c JOIN examinations e ON e.course_id=c.course_id WHERE e.status='Active' ORDER BY c.course_name").fetchall()
    types=db.execute("SELECT DISTINCT exam_type FROM examinations WHERE status='Active' ORDER BY exam_type").fetchall()
    return render_template("student_examinations.html",exams=exams,courses=courses,types=types,q=q,course_id=course_id,exam_type=exam_type,now=now)

@app.route("/student/examinations/<int:exam_id>")
@login_required
@role_required("Student")
def student_exam_details(exam_id):
    db=get_db_connection()
    if not get_current_student():
        flash("Student profile not found.","danger")
        return redirect(url_for("student_dashboard"))
    exam=db.execute("""
        SELECT e.*,c.course_name,c.course_code,c.department
        FROM examinations e JOIN courses c ON c.course_id=e.course_id
        WHERE e.exam_id=? AND e.status='Active'
    """,(exam_id,)).fetchone()
    if not exam:
        flash("Examination not found or unavailable.","danger")
        return redirect(url_for("student_examinations"))
    now=datetime.now().strftime("%Y-%m-%dT%H:%M")
    rows=db.execute("""
        SELECT s.*,u.name AS examiner_name,COUNT(b.booking_id) AS booking_count
        FROM exam_slots s
        JOIN examiner_profiles ep ON ep.employee_id=s.examiner_id
        JOIN users u ON u.user_id=ep.user_id
        LEFT JOIN bookings b ON b.slot_id=s.slot_id AND b.booking_status='Active'
        WHERE s.exam_id=? AND s.is_active=1 AND s.slot_date||'T'||s.start_time>?
        GROUP BY s.slot_id ORDER BY s.slot_date,s.start_time
    """,(exam_id,now)).fetchall()
    slots=[]
    for row in rows:
        slot=dict(row)
        slot["remaining"]=slot["capacity"]-slot["booking_count"]
        slots.append(slot)
    return render_template("student_exam_details.html",exam=exam,slots=slots,booking_open=student_booking_open(exam))

@app.route("/admin/examiners")
@login_required
@role_required("Admin")
def manage_examiners():
    db = get_db_connection()
    status = request.args.get("status", "Pending")
    if status not in ("Pending", "Approved", "Rejected"):
        status = "Pending"
    examiners = db.execute("""
        SELECT ep.employee_id,ep.department,ep.designation,ep.approval_status,u.user_id,u.name,u.email,u.created_at
        FROM examiner_profiles ep
        JOIN users u ON ep.user_id=u.user_id
        WHERE ep.approval_status=?
        ORDER BY u.created_at ASC
    """, (status,)).fetchall()
    counts = db.execute("""
        SELECT approval_status,COUNT(*) AS total
        FROM examiner_profiles
        GROUP BY approval_status
    """).fetchall()
    status_counts = {row["approval_status"]: row["total"] for row in counts}
    return render_template("admin_examiners.html", examiners=examiners,status=status, status_counts=status_counts)

@app.route("/admin/examiners/<int:employee_id>/status", methods=["POST"])
@login_required
@role_required("Admin")
def update_examiner_status(employee_id):
    new_status = request.form.get("status")
    tab = request.form.get("tab","Pending")
    if new_status not in ("Pending","Approved","Rejected"):
        flash("Invalid approval status.","danger")
        return redirect(url_for("manage_examiners"))
    if tab not in ("Pending","Approved","Rejected"):
        tab = "Pending"
    db = get_db_connection()
    try:
        db.execute("BEGIN IMMEDIATE")
        examiner = db.execute("""
            SELECT user_id,approval_status
            FROM examiner_profiles
            WHERE employee_id=?
        """,(employee_id,)).fetchone()
        if examiner is None:
            db.rollback()
            flash("Examiner not found.","danger")
            return redirect(url_for("manage_examiners",status=tab))
        old_status = examiner["approval_status"]
        if old_status == new_status:
            db.rollback()
            flash("Examiner already has this status.","info")
            return redirect(url_for("manage_examiners",status=tab))
        db.execute("""
            UPDATE examiner_profiles
            SET approval_status=?
            WHERE employee_id=?
        """,(new_status,employee_id))
        db.execute("""
            INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details)
            VALUES(?,?,?,?,?)
        """,(g.user["user_id"],"Examiner Status Changed","Examiner Profile",employee_id,f"Status changed from {old_status} to {new_status}."))
        db.commit()
        flash(f"Examiner EMP{employee_id:05d} status changed to {new_status}.","success")
    except Exception:
        db.rollback()
        raise
    return redirect(url_for("manage_examiners",status=tab))

@app.route("/admin/users")
@login_required
@role_required("Admin")
def manage_users():
    db=get_db_connection()
    q=request.args.get("q","").strip()
    role=request.args.get("role","All")
    status=request.args.get("status","All")
    conditions=["u.role IN ('Student','Examiner')"]
    params=[]
    if q:
        conditions.append("(u.name LIKE ? OR u.email LIKE ?)")
        params.extend([f"%{q}%",f"%{q}%"])
    if role in ("Student","Examiner"):
        conditions.append("u.role=?")
        params.append(role)
    else:
        role="All"
    if status=="Active":
        conditions.append("u.is_active=1")
    elif status=="Inactive":
        conditions.append("u.is_active=0")
    else:
        status="All"
    users=db.execute(f"""
        SELECT u.user_id,u.name,u.email,u.role,u.is_active,u.created_at,
        ep.employee_id,ep.approval_status,sp.student_id
        FROM users u
        LEFT JOIN examiner_profiles ep ON ep.user_id=u.user_id
        LEFT JOIN student_profiles sp ON sp.user_id=u.user_id
        WHERE {" AND ".join(conditions)}
        ORDER BY u.created_at DESC
    """,params).fetchall()
    return render_template("admin_users.html",users=users,q=q,role=role,status=status)

@app.route("/admin/users/<int:user_id>/status",methods=["POST"])
@login_required
@role_required("Admin")
def update_user_status(user_id):
    new_status=request.form.get("is_active")
    q=request.form.get("q","")
    role=request.form.get("role","All")
    status=request.form.get("filter_status","All")
    if new_status not in ("0","1"):
        flash("Invalid account status.","danger")
        return redirect(url_for("manage_users"))
    db=get_db_connection()
    try:
        db.execute("BEGIN IMMEDIATE")
        user=db.execute("SELECT name,role,is_active FROM users WHERE user_id=?",(user_id,)).fetchone()
        if user is None or user["role"]!="Examiner":
            db.rollback()
            flash("Only examiner accounts can be activated or deactivated here.","danger")
            return redirect(url_for("manage_users",q=q,role=role,status=status))
        if user["is_active"]==int(new_status):
            db.rollback()
            flash("The examiner already has this status.","info")
            return redirect(url_for("manage_users",q=q,role=role,status=status))
        db.execute("UPDATE users SET is_active=? WHERE user_id=?",(int(new_status),user_id))
        action="Examiner Activated" if new_status=="1" else "Examiner Deactivated"
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],action,"Examiner",user_id,f"{user['name']} account status changed."))
        db.commit()
        flash(f"{user['name']}'s account has been {'activated' if new_status=='1' else 'deactivated'}.","success")
    except Exception:
        db.rollback()
        raise
    return redirect(url_for("manage_users",q=q,role=role,status=status))

def validate_exam_form(form):
    data={
        "course_id":form.get("course_id","").strip(),
        "exam_name":form.get("exam_name","").strip(),
        "exam_type":form.get("exam_type","").strip(),
        "description":form.get("description","").strip(),
        "duration":form.get("duration","").strip(),
        "max_marks":form.get("max_marks","").strip(),
        "slot_creation_start":form.get("slot_creation_start","").strip(),
        "slot_creation_end":form.get("slot_creation_end","").strip(),
        "booking_start":form.get("booking_start","").strip(),
        "booking_end":form.get("booking_end","").strip(),
        "status":form.get("status","Draft"),
        "exam_date_start":form.get("exam_date_start","").strip(),
        "exam_date_end":form.get("exam_date_end","").strip(),
        "daily_slot_start":form.get("daily_slot_start","").strip(),
        "daily_slot_end":form.get("daily_slot_end","").strip()
    }
    if not all(data[k] for k in ("course_id","exam_name","exam_type","duration","max_marks","slot_creation_start","slot_creation_end","booking_start","booking_end")):
        return None,"All required fields must be completed."
    if len(data["exam_name"])>150 or len(data["exam_type"])>50:
        return None,"Exam name or type is too long."
    try:
        data["course_id"]=int(data["course_id"])
        data["duration"]=int(data["duration"])
        data["max_marks"]=int(data["max_marks"])
        if data["duration"]<=0 or data["max_marks"]<=0:
            raise ValueError
    except ValueError:
        return None,"Select a valid course and enter positive duration and maximum marks."
    try:
        start_date=datetime.strptime(data["exam_date_start"],"%Y-%m-%d").date()
        end_date=datetime.strptime(data["exam_date_end"],"%Y-%m-%d").date()
        daily_start=datetime.strptime(data["daily_slot_start"],"%H:%M").time()
        daily_end=datetime.strptime(data["daily_slot_end"],"%H:%M").time()
        if start_date>end_date or daily_start>=daily_end:
            raise ValueError
    except ValueError:
        return None,"Invalid examination date range or daily slot timings."
    try:
        times=[datetime.strptime(data[k],"%Y-%m-%dT%H:%M") for k in ("slot_creation_start","slot_creation_end","booking_start","booking_end")]
    except ValueError:
        return None,"Enter valid timeline dates and times."
    if not times[0]<times[1]<=times[2]<times[3]:
        return None,"Timeline order must be: slot creation start, slot creation end, booking start, booking end."
    if data["status"] not in ("Draft","Active","Completed","Cancelled"):
        return None,"Invalid examination status."
    return data,None

@app.route("/admin/examinations")
@login_required
@role_required("Admin")
def manage_examinations():
    db=get_db_connection()
    q=request.args.get("q","").strip()
    status=request.args.get("status","All")
    if status not in ("All","Draft","Active","Completed","Cancelled"):
        status="All"
    conditions=["(e.exam_name LIKE ? OR c.course_name LIKE ? OR c.course_code LIKE ? OR CAST(e.exam_id AS TEXT)=? OR CAST(c.course_id AS TEXT)=?)"]
    params=[f"%{q}%",f"%{q}%",f"%{q}%",q,q]
    if status!="All":
        conditions.append("e.status=?")
        params.append(status)
    exams=db.execute(f"""
        SELECT e.*,c.course_name,c.course_code,
        (SELECT COUNT(*) FROM exam_slots s WHERE s.exam_id=e.exam_id) AS slot_count,
        (SELECT COUNT(*) FROM bookings b WHERE b.exam_id=e.exam_id) AS booking_count
        FROM examinations e JOIN courses c ON c.course_id=e.course_id
        WHERE {" AND ".join(conditions)}
        ORDER BY e.created_at DESC
    """,params).fetchall()
    return render_template("admin_examinations.html",exams=exams,q=q,status=status)

@app.route("/admin/examinations/new",methods=["GET","POST"])
@login_required
@role_required("Admin")
def create_examination():
    db=get_db_connection()
    courses=db.execute("SELECT course_id,course_name,course_code FROM courses ORDER BY course_name").fetchall()
    if request.method=="POST":
        data,error=validate_exam_form(request.form)
        if not error and not db.execute("SELECT 1 FROM courses WHERE course_id=?",(data["course_id"],)).fetchone():
            error="Selected course does not exist."
        if error:
            flash(error,"danger")
            return render_template("exam_form.html",exam=request.form,courses=courses)
        try:
            db.execute("BEGIN IMMEDIATE")
            cursor=db.execute("""
                INSERT INTO examinations(course_id,exam_name,exam_type,description,duration,max_marks,slot_creation_start,slot_creation_end,booking_start,booking_end,status,exam_date_start,exam_date_end,daily_slot_start,daily_slot_end)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,(data["course_id"],data["exam_name"],data["exam_type"],data["description"] or None,data["duration"],data["max_marks"],data["slot_creation_start"],data["slot_creation_end"],data["booking_start"],data["booking_end"],data["status"],data["exam_date_start"],data["exam_date_end"],data["daily_slot_start"],data["daily_slot_end"]))
            exam_id=cursor.lastrowid
            db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],"Examination Created","Examination",exam_id,data["exam_name"]))
            db.commit()
            flash("Examination created successfully.","success")
            return redirect(url_for("manage_examinations"))
        except sqlite3.IntegrityError:
            db.rollback()
            flash("Could not create examination. Verify the selected course and timeline values.","danger")
    return render_template("exam_form.html",exam=None,courses=courses)

@app.route("/admin/examinations/<int:exam_id>/edit",methods=["GET","POST"])
@login_required
@role_required("Admin")
def edit_examination(exam_id):
    db=get_db_connection()
    exam=db.execute("SELECT * FROM examinations WHERE exam_id=?",(exam_id,)).fetchone()
    if exam is None:
        flash("Examination not found.","danger")
        return redirect(url_for("manage_examinations"))
    courses=db.execute("SELECT course_id,course_name,course_code FROM courses ORDER BY course_name").fetchall()
    if request.method=="POST":
        data,error=validate_exam_form(request.form)
        if not error and not db.execute("SELECT 1 FROM courses WHERE course_id=?",(data["course_id"],)).fetchone():
            error="Selected course does not exist."
        if error:
            flash(error,"danger")
            return render_template("exam_form.html",exam=request.form,courses=courses)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                UPDATE examinations SET course_id=?,exam_name=?,exam_type=?,description=?,duration=?,max_marks=?,slot_creation_start=?,slot_creation_end=?,booking_start=?,booking_end=?,status=?,exam_date_start=?,exam_date_end=?,daily_slot_start=?,daily_slot_end=?,
                slot_creation_enabled=CASE WHEN ? IN ('Draft','Completed','Cancelled') THEN 0 ELSE slot_creation_enabled END,
                booking_enabled=CASE WHEN ? IN ('Draft','Completed','Cancelled') THEN 0 ELSE booking_enabled END
                WHERE exam_id=?
            """,(data["course_id"],data["exam_name"],data["exam_type"],data["description"] or None,data["duration"],data["max_marks"],data["slot_creation_start"],data["slot_creation_end"],data["booking_start"],data["booking_end"],data["status"],data["exam_date_start"],data["exam_date_end"],data["daily_slot_start"],data["daily_slot_end"],data["status"],data["status"],exam_id))
            db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],"Examination Updated","Examination",exam_id,f"{data['exam_name']}; status: {data['status']}"))
            db.commit()
            flash("Examination updated successfully.","success")
            return redirect(url_for("manage_examinations"))
        except sqlite3.IntegrityError:
            db.rollback()
            flash("Could not update examination. Check its linked records and timeline values.","danger")
    return render_template("exam_form.html",exam=exam,courses=courses)

@app.route("/admin/examinations/<int:exam_id>/status",methods=["POST"])
@login_required
@role_required("Admin")
def update_examination_status(exam_id):
    status=request.form.get("status")
    if status not in ("Draft","Active","Completed","Cancelled"):
        flash("Invalid examination status.","danger")
        return redirect(url_for("manage_examinations"))
    db=get_db_connection()
    try:
        db.execute("BEGIN IMMEDIATE")
        exam=db.execute("SELECT exam_name,status FROM examinations WHERE exam_id=?",(exam_id,)).fetchone()
        if exam is None:
            db.rollback()
            flash("Examination not found.","danger")
            return redirect(url_for("manage_examinations"))
        db.execute("""
            UPDATE examinations SET status=?,
            slot_creation_enabled=CASE WHEN ?='Active' THEN slot_creation_enabled ELSE 0 END,
            booking_enabled=CASE WHEN ?='Active' THEN booking_enabled ELSE 0 END
            WHERE exam_id=?
        """,(status,status,status,exam_id))
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],"Examination Status Changed","Examination",exam_id,f"{exam['status']} to {status}"))
        db.commit()
        flash("Examination status updated.","success")
    except Exception:
        db.rollback()
        raise
    return redirect(url_for("manage_examinations"))

@app.route("/admin/examinations/<int:exam_id>/toggle",methods=["POST"])
@login_required
@role_required("Admin")
def toggle_examination_window(exam_id):
    field=request.form.get("field")
    value=request.form.get("value")
    fields={"slot_creation_enabled":"Examiner Slot Creation","booking_enabled":"Student Booking"}
    if field not in fields or value not in ("0","1"):
        flash("Invalid timeline control.","danger")
        return redirect(url_for("manage_examinations"))
    db=get_db_connection()
    try:
        db.execute("BEGIN IMMEDIATE")
        exam=db.execute("SELECT exam_name,status,slot_creation_start,slot_creation_end,booking_start,booking_end FROM examinations WHERE exam_id=?",(exam_id,)).fetchone()
        if exam is None:
            db.rollback()
            flash("Examination not found.","danger")
            return redirect(url_for("manage_examinations"))
        if value=="1" and exam["status"]!="Active":
            db.rollback()
            flash("Only Active examinations can open booking or slot creation.","danger")
            return redirect(url_for("manage_examinations"))
        now=datetime.now().strftime("%Y-%m-%dT%H:%M")
        start=exam["slot_creation_start"] if field=="slot_creation_enabled" else exam["booking_start"]
        end=exam["slot_creation_end"] if field=="slot_creation_enabled" else exam["booking_end"]
        if value=="1" and not start<=now<end:
            db.rollback()
            flash("This window can only be opened during its configured timeline.","danger")
            return redirect(url_for("manage_examinations"))
        db.execute(f"UPDATE examinations SET {field}=? WHERE exam_id=?",(int(value),exam_id))
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],fields[field]+(" Opened" if value=="1" else " Closed"),"Examination",exam_id,exam["exam_name"]))
        db.commit()
        flash(fields[field]+(" opened." if value=="1" else " closed."),"success")
    except Exception:
        db.rollback()
        raise
    return redirect(url_for("manage_examinations"))

@app.route("/admin/examinations/<int:exam_id>/delete",methods=["POST"])
@login_required
@role_required("Admin")
def delete_examination(exam_id):
    db=get_db_connection()
    try:
        db.execute("BEGIN IMMEDIATE")
        exam=db.execute("SELECT exam_name FROM examinations WHERE exam_id=?",(exam_id,)).fetchone()
        if exam is None:
            db.rollback()
            flash("Examination not found.","danger")
            return redirect(url_for("manage_examinations"))
        dependencies=db.execute("SELECT COUNT(*) FROM exam_slots WHERE exam_id=?",(exam_id,)).fetchone()[0]
        if dependencies:
            db.rollback()
            flash("This examination has slots or bookings and cannot be deleted. Cancel it instead.","danger")
            return redirect(url_for("manage_examinations"))
        db.execute("DELETE FROM examinations WHERE exam_id=?",(exam_id,))
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],"Examination Deleted","Examination",exam_id,exam["exam_name"]))
        db.commit()
        flash("Examination deleted successfully.","success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("This examination has linked records and cannot be deleted.","danger")
    return redirect(url_for("manage_examinations"))

@app.route("/admin/courses")
@login_required
@role_required("Admin")
def manage_courses():
    db=get_db_connection()
    q=request.args.get("q","").strip()
    courses=db.execute("""
        SELECT c.*,COUNT(e.exam_id) AS exam_count
        FROM courses c LEFT JOIN examinations e ON e.course_id=c.course_id
        WHERE c.course_name LIKE ? OR c.course_code LIKE ? OR c.department LIKE ? OR CAST(c.course_id AS TEXT)=?
        GROUP BY c.course_id ORDER BY c.course_name
    """,(f"%{q}%",f"%{q}%",f"%{q}%",q)).fetchall()
    return render_template("admin_courses.html",courses=courses,q=q)

@app.route("/admin/courses/new",methods=["GET","POST"])
@login_required
@role_required("Admin")
def create_course():
    if request.method=="POST":
        name=request.form.get("course_name","").strip()
        code=request.form.get("course_code","").strip().upper()
        department=request.form.get("department","").strip()
        description=request.form.get("description","").strip()
        if not name or not code or not department or len(name)>150 or len(code)>30 or len(department)>100:
            flash("Enter valid course details.","danger")
            return render_template("course_form.html",course=None)
        db=get_db_connection()
        try:
            db.execute("BEGIN IMMEDIATE")
            cursor=db.execute("INSERT INTO courses(course_name,course_code,department,description) VALUES(?,?,?,?)",(name,code,department,description or None))
            course_id=cursor.lastrowid
            db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],"Course Created","Course",course_id,f"{code}: {name}"))
            db.commit()
            flash("Course created successfully.","success")
            return redirect(url_for("manage_courses"))
        except sqlite3.IntegrityError:
            db.rollback()
            flash("Course code already exists.","danger")
    return render_template("course_form.html",course=None)

@app.route("/admin/courses/<int:course_id>/edit",methods=["GET","POST"])
@login_required
@role_required("Admin")
def edit_course(course_id):
    db=get_db_connection()
    course=db.execute("SELECT * FROM courses WHERE course_id=?",(course_id,)).fetchone()
    if course is None:
        flash("Course not found.","danger")
        return redirect(url_for("manage_courses"))
    if request.method=="POST":
        name=request.form.get("course_name","").strip()
        code=request.form.get("course_code","").strip().upper()
        department=request.form.get("department","").strip()
        description=request.form.get("description","").strip()
        if not name or not code or not department or len(name)>150 or len(code)>30 or len(department)>100:
            flash("Enter valid course details.","danger")
            return render_template("course_form.html",course=request.form)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE courses SET course_name=?,course_code=?,department=?,description=? WHERE course_id=?",(name,code,department,description or None,course_id))
            db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],"Course Updated","Course",course_id,f"{code}: {name}"))
            db.commit()
            flash("Course updated successfully.","success")
            return redirect(url_for("manage_courses"))
        except sqlite3.IntegrityError:
            db.rollback()
            flash("Course code already exists.","danger")
    return render_template("course_form.html",course=course)

@app.route("/admin/courses/<int:course_id>/delete",methods=["POST"])
@login_required
@role_required("Admin")
def delete_course(course_id):
    db=get_db_connection()
    try:
        db.execute("BEGIN IMMEDIATE")
        course=db.execute("SELECT course_name,course_code FROM courses WHERE course_id=?",(course_id,)).fetchone()
        if course is None:
            db.rollback()
            flash("Course not found.","danger")
            return redirect(url_for("manage_courses"))
        db.execute("DELETE FROM courses WHERE course_id=?",(course_id,))
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],"Course Deleted","Course",course_id,f"{course['course_code']}: {course['course_name']}"))
        db.commit()
        flash("Course deleted successfully.","success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Cannot delete this course because examinations are linked to it.","danger")
    return redirect(url_for("manage_courses"))

@app.route("/admin/examinations/<int:exam_id>/rubric",methods=["GET","POST"])
@login_required
@role_required("Admin")
def manage_rubric(exam_id):
    db=get_db_connection()
    exam=db.execute("SELECT * FROM examinations WHERE exam_id=?",(exam_id,)).fetchone()
    if not exam:
        flash("Examination not found.","danger")
        return redirect(url_for("manage_examinations"))
    rubric=db.execute("SELECT * FROM rubrics WHERE exam_id=?",(exam_id,)).fetchone()
    if request.method=="POST":
        name=request.form.get("rubric_name","").strip()
        description=request.form.get("description","").strip()
        if not name or len(name)>150:
            flash("Enter a valid rubric name.","danger")
            return redirect(url_for("manage_rubric",exam_id=exam_id))
        try:
            db.execute("BEGIN IMMEDIATE")
            if rubric:
                db.execute("UPDATE rubrics SET rubric_name=?,description=? WHERE rubric_id=?",(name,description or None,rubric["rubric_id"]))
                action="Rubric Updated"
                rubric_id=rubric["rubric_id"]
            else:
                cur=db.execute("INSERT INTO rubrics(exam_id,rubric_name,description) VALUES(?,?,?)",(exam_id,name,description or None))
                rubric_id=cur.lastrowid
                action="Rubric Created"
            db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],action,"Rubric",rubric_id,name))
            db.commit()
            flash("Rubric saved successfully.","success")
        except sqlite3.IntegrityError:
            db.rollback()
            flash("A rubric already exists for this examination.","danger")
        return redirect(url_for("manage_rubric",exam_id=exam_id))
    criteria=[]
    total_marks=0
    total_weightage=0
    if rubric:
        criteria=db.execute("SELECT * FROM rubric_criteria WHERE rubric_id=? ORDER BY criterion_id",(rubric["rubric_id"],)).fetchall()
        total_marks=sum(c["max_marks"] for c in criteria)
        total_weightage=sum(c["weightage"] for c in criteria)
    complete=bool(criteria) and total_marks==exam["max_marks"] and abs(total_weightage-100)<0.001
    return render_template("admin_rubric.html",exam=exam,rubric=rubric,criteria=criteria,total_marks=total_marks,total_weightage=total_weightage,complete=complete)

@app.route("/admin/rubrics/<int:rubric_id>/criteria/new",methods=["GET","POST"])
@login_required
@role_required("Admin")
def create_rubric_criterion(rubric_id):
    db=get_db_connection()
    rubric=db.execute("SELECT r.*,e.max_marks AS exam_max_marks,e.exam_id FROM rubrics r JOIN examinations e ON e.exam_id=r.exam_id WHERE r.rubric_id=?",(rubric_id,)).fetchone()
    if not rubric:
        flash("Rubric not found.","danger")
        return redirect(url_for("manage_examinations"))
    if request.method=="POST":
        name=request.form.get("criterion_name","").strip()
        description=request.form.get("description","").strip()
        try:
            marks=int(request.form.get("max_marks",""))
            weight=float(request.form.get("weightage",""))
            if not name or len(name)>150 or marks<=0 or not 0<weight<=100:
                raise ValueError
        except (ValueError,TypeError):
            flash("Enter a valid name, positive marks and weightage between 0 and 100.","danger")
            return render_template("criterion_form.html",rubric=rubric,criterion=None)
        totals=db.execute("SELECT COALESCE(SUM(max_marks),0) AS marks,COALESCE(SUM(weightage),0) AS weight FROM rubric_criteria WHERE rubric_id=?",(rubric_id,)).fetchone()
        if totals["marks"]+marks>rubric["exam_max_marks"] or totals["weight"]+weight>100.001:
            flash("This criterion would exceed the examination's maximum marks or 100% weightage.","danger")
            return render_template("criterion_form.html",rubric=rubric,criterion=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            cur=db.execute("INSERT INTO rubric_criteria(rubric_id,criterion_name,description,max_marks,weightage) VALUES(?,?,?,?,?)",(rubric_id,name,description or None,marks,weight))
            db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],"Criterion Created","Rubric Criterion",cur.lastrowid,name))
            db.commit()
            flash("Criterion added.","success")
            return redirect(url_for("manage_rubric",exam_id=rubric["exam_id"]))
        except sqlite3.IntegrityError:
            db.rollback()
            flash("Unable to add criterion.","danger")
    return render_template("criterion_form.html",rubric=rubric,criterion=None)

@app.route("/admin/rubrics/criteria/<int:criterion_id>/edit",methods=["GET","POST"])
@login_required
@role_required("Admin")
def edit_rubric_criterion(criterion_id):
    db=get_db_connection()
    criterion=db.execute("""
        SELECT rc.*,r.exam_id,e.max_marks AS exam_max_marks
        FROM rubric_criteria rc
        JOIN rubrics r ON r.rubric_id=rc.rubric_id
        JOIN examinations e ON e.exam_id=r.exam_id
        WHERE rc.criterion_id=?
    """,(criterion_id,)).fetchone()
    if not criterion:
        flash("Criterion not found.","danger")
        return redirect(url_for("manage_examinations"))
    rubric={"rubric_id":criterion["rubric_id"],"exam_id":criterion["exam_id"],"exam_max_marks":criterion["exam_max_marks"]}
    if request.method=="POST":
        name=request.form.get("criterion_name","").strip()
        description=request.form.get("description","").strip()
        try:
            marks=int(request.form.get("max_marks",""))
            weight=float(request.form.get("weightage",""))
            if not name or len(name)>150 or marks<=0 or not 0<weight<=100:
                raise ValueError
        except (ValueError,TypeError):
            flash("Enter valid criterion details.","danger")
            return render_template("criterion_form.html",rubric=rubric,criterion=request.form)
        totals=db.execute("""
            SELECT COALESCE(SUM(max_marks),0) AS marks,COALESCE(SUM(weightage),0) AS weight
            FROM rubric_criteria WHERE rubric_id=? AND criterion_id!=?
        """,(criterion["rubric_id"],criterion_id)).fetchone()
        if totals["marks"]+marks>criterion["exam_max_marks"] or totals["weight"]+weight>100.001:
            flash("The updated criterion would exceed the examination's maximum marks or 100% weightage.","danger")
            return render_template("criterion_form.html",rubric=rubric,criterion=request.form)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE rubric_criteria SET criterion_name=?,description=?,max_marks=?,weightage=? WHERE criterion_id=?",(name,description or None,marks,weight,criterion_id))
            db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],"Criterion Updated","Rubric Criterion",criterion_id,name))
            db.commit()
            flash("Criterion updated.","success")
            return redirect(url_for("manage_rubric",exam_id=criterion["exam_id"]))
        except sqlite3.IntegrityError:
            db.rollback()
            flash("Unable to update criterion.","danger")
    return render_template("criterion_form.html",rubric=rubric,criterion=criterion)

@app.route("/admin/rubrics/criteria/<int:criterion_id>/delete",methods=["POST"])
@login_required
@role_required("Admin")
def delete_rubric_criterion(criterion_id):
    db=get_db_connection()
    try:
        db.execute("BEGIN IMMEDIATE")
        criterion=db.execute("""
            SELECT rc.criterion_name,rc.rubric_id,r.exam_id
            FROM rubric_criteria rc JOIN rubrics r ON r.rubric_id=rc.rubric_id
            WHERE rc.criterion_id=?
        """,(criterion_id,)).fetchone()
        if not criterion:
            db.rollback()
            flash("Criterion not found.","danger")
            return redirect(url_for("manage_examinations"))
        db.execute("DELETE FROM rubric_criteria WHERE criterion_id=?",(criterion_id,))
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(g.user["user_id"],"Criterion Deleted","Rubric Criterion",criterion_id,criterion["criterion_name"]))
        db.commit()
        flash("Criterion deleted.","success")
        return redirect(url_for("manage_rubric",exam_id=criterion["exam_id"]))
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Cannot delete a criterion already used in an evaluation.","danger")
        return redirect(url_for("manage_examinations"))

def get_current_examiner():
    return get_db_connection().execute(
        "SELECT employee_id FROM examiner_profiles WHERE user_id=? AND approval_status='Approved'",
        (g.user["user_id"],)
    ).fetchone()

def slot_window_open(exam):
    now=datetime.now().strftime("%Y-%m-%dT%H:%M")
    return exam["status"]=="Active" and exam["slot_creation_enabled"]==1 and exam["slot_creation_start"]<=now<exam["slot_creation_end"]

def validate_slot_form(form,exam):
    date=form.get("slot_date","").strip()
    start=form.get("start_time","").strip()
    end=form.get("end_time","").strip()
    try:
        slot_date=datetime.strptime(date,"%Y-%m-%d").date()
        start_time=datetime.strptime(start,"%H:%M").time()
        end_time=datetime.strptime(end,"%H:%M").time()
        capacity=int(form.get("capacity",""))
        first=datetime.strptime(exam["exam_date_start"],"%Y-%m-%d").date()
        last=datetime.strptime(exam["exam_date_end"],"%Y-%m-%d").date()
        earliest=datetime.strptime(exam["daily_slot_start"],"%H:%M").time()
        latest=datetime.strptime(exam["daily_slot_end"],"%H:%M").time()
        duration=int((datetime.combine(slot_date,end_time)-datetime.combine(slot_date,start_time)).total_seconds()//60)
        if duration!=exam["duration"]:
            raise ValueError("duration")
        if not first<=slot_date<=last:
            raise ValueError("date")
        if start_time>=end_time or start_time<earliest or end_time>latest:
            raise ValueError("time")
        if capacity<=0 or datetime.combine(slot_date,start_time)<=datetime.now():
            raise ValueError("capacity")
    except (ValueError,TypeError):
        return None,"Slot must be in the permitted date range and daily time window, with a future start and positive capacity."
    return {"slot_date":date,"start_time":start,"end_time":end,"capacity":capacity},None

@app.route("/examiner/examinations")
@login_required
@role_required("Examiner")
def examiner_examinations():
    db=get_db_connection()
    examiner=get_current_examiner()
    exams=db.execute("""
        SELECT e.*,c.course_name,c.course_code,COUNT(s.slot_id) AS slot_count
        FROM examiners a
        JOIN examinations e ON e.exam_id=a.exam_id
        JOIN courses c ON c.course_id=e.course_id
        LEFT JOIN exam_slots s ON s.exam_id=e.exam_id AND s.examiner_id=a.examiner_id
        WHERE a.examiner_id=?
        GROUP BY e.exam_id ORDER BY e.slot_creation_start DESC
    """,(examiner["employee_id"],)).fetchall()
    return render_template("examiner_examinations.html",exams=exams)

@app.route("/examiner/examinations/<int:exam_id>/slots")
@login_required
@role_required("Examiner")
def examiner_slots(exam_id):
    db=get_db_connection()
    examiner=get_current_examiner()
    exam=db.execute("""
        SELECT e.*,c.course_name FROM examinations e
        JOIN courses c ON c.course_id=e.course_id
        JOIN examiners a ON a.exam_id=e.exam_id
        WHERE e.exam_id=? AND a.examiner_id=?
    """,(exam_id,examiner["employee_id"])).fetchone()
    if not exam:
        flash("Examination not assigned to you.","danger")
        return redirect(url_for("examiner_examinations"))
    slots=db.execute("""
        SELECT s.*,COUNT(b.booking_id) AS booking_count
        FROM exam_slots s LEFT JOIN bookings b
        ON b.slot_id=s.slot_id AND b.booking_status='Active'
        WHERE s.exam_id=? AND s.examiner_id=?
        GROUP BY s.slot_id ORDER BY s.slot_date,s.start_time
    """,(exam_id,examiner["employee_id"])).fetchall()
    can_edit=datetime.now().strftime("%Y-%m-%dT%H:%M")<exam["booking_start"]
    return render_template("examiner_slots.html",exam=exam,slots=slots,can_edit=can_edit,window_open=slot_window_open(exam))

@app.route("/examiner/examinations/<int:exam_id>/slots/new",methods=["GET","POST"])
@login_required
@role_required("Examiner")
def create_exam_slot(exam_id):
    db=get_db_connection()
    examiner=get_current_examiner()
    exam=db.execute("""
        SELECT e.* FROM examinations e
        JOIN examiners a ON a.exam_id=e.exam_id
        WHERE e.exam_id=? AND a.examiner_id=?
    """,(exam_id,examiner["employee_id"])).fetchone()
    if not exam:
        flash("Examination not assigned to you.","danger")
        return redirect(url_for("examiner_examinations"))
    if not slot_window_open(exam):
        flash("Slot creation is currently closed for this examination.","danger")
        return redirect(url_for("examiner_slots",exam_id=exam_id))
    if request.method=="POST":
        data,error=validate_slot_form(request.form,exam)
        if error:
            flash(error,"danger")
            return render_template("slot_form.html",exam=exam,slot=request.form)
        overlap=db.execute("""
            SELECT 1 FROM exam_slots
            WHERE examiner_id=? AND slot_date=? AND is_active=1
            AND start_time<? AND end_time>?
        """,(examiner["employee_id"],data["slot_date"],data["end_time"],data["start_time"])).fetchone()
        if overlap:
            flash("This slot overlaps another active slot assigned to you.","danger")
            return render_template("slot_form.html",exam=exam,slot=request.form)
        try:
            db.execute("BEGIN IMMEDIATE")
            cur=db.execute("""
                INSERT INTO exam_slots(exam_id,examiner_id,slot_date,start_time,end_time,capacity)
                VALUES(?,?,?,?,?,?)
            """,(exam_id,examiner["employee_id"],data["slot_date"],data["start_time"],data["end_time"],data["capacity"]))
            db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",
                (g.user["user_id"],"Slot Created","Exam Slot",cur.lastrowid,f"{exam['exam_name']} - {data['slot_date']} {data['start_time']}"))
            db.commit()
            flash("Examination slot created.","success")
            return redirect(url_for("examiner_slots",exam_id=exam_id))
        except sqlite3.IntegrityError:
            db.rollback()
            flash("Unable to create this slot.","danger")
    return render_template("slot_form.html",exam=exam,slot=None)

@app.route("/examiner/slots/<int:slot_id>/edit",methods=["GET","POST"])
@login_required
@role_required("Examiner")
def edit_exam_slot(slot_id):
    db=get_db_connection()
    examiner=get_current_examiner()
    slot=db.execute("""
        SELECT s.*,e.exam_name,e.booking_start,e.status,e.exam_id,e.exam_date_start,e.exam_date_end,e.daily_slot_start,e.daily_slot_end
        FROM exam_slots s JOIN examinations e ON e.exam_id=s.exam_id
        WHERE s.slot_id=? AND s.examiner_id=?
    """,(slot_id,examiner["employee_id"])).fetchone()
    if not slot:
        flash("Slot not found or not assigned to you.","danger")
        return redirect(url_for("examiner_examinations"))
    if slot["status"]!="Active" or datetime.now().strftime("%Y-%m-%dT%H:%M")>=slot["booking_start"]:
        flash("Slots can only be edited before student booking starts.","danger")
        return redirect(url_for("examiner_slots",exam_id=slot["exam_id"]))
    if request.method=="POST":
        data,error=validate_slot_form(request.form,slot)
        if error:
            flash(error,"danger")
            return render_template("slot_form.html",exam=slot,slot=request.form)
        overlap=db.execute("""
            SELECT 1 FROM exam_slots
            WHERE examiner_id=? AND slot_date=? AND is_active=1 AND slot_id!=?
            AND start_time<? AND end_time>?
        """,(examiner["employee_id"],data["slot_date"],slot_id,data["end_time"],data["start_time"])).fetchone()
        count=db.execute("SELECT COUNT(*) FROM bookings WHERE slot_id=? AND booking_status='Active'",(slot_id,)).fetchone()[0]
        if overlap or data["capacity"]<count:
            flash("Slot overlaps another slot or capacity is below existing bookings.","danger")
            return render_template("slot_form.html",exam=slot,slot=request.form)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                UPDATE exam_slots SET slot_date=?,start_time=?,end_time=?,capacity=?
                WHERE slot_id=? AND examiner_id=?
            """,(data["slot_date"],data["start_time"],data["end_time"],data["capacity"],slot_id,examiner["employee_id"]))
            db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",
                (g.user["user_id"],"Slot Updated","Exam Slot",slot_id,f"{data['slot_date']} {data['start_time']}"))
            db.commit()
            flash("Slot updated.","success")
            return redirect(url_for("examiner_slots",exam_id=slot["exam_id"]))
        except sqlite3.IntegrityError:
            db.rollback()
            flash("Unable to update slot.","danger")
    return render_template("slot_form.html",exam=slot,slot=slot)

@app.route("/examiner/slots/<int:slot_id>/delete",methods=["POST"])
@login_required
@role_required("Examiner")
def delete_exam_slot(slot_id):
    db=get_db_connection()
    examiner=get_current_examiner()
    try:
        db.execute("BEGIN IMMEDIATE")
        slot=db.execute("""
            SELECT s.*,e.booking_start,e.status FROM exam_slots s
            JOIN examinations e ON e.exam_id=s.exam_id
            WHERE s.slot_id=? AND s.examiner_id=?
        """,(slot_id,examiner["employee_id"])).fetchone()
        if not slot:
            db.rollback()
            flash("Slot not found.","danger")
            return redirect(url_for("examiner_examinations"))
        if slot["status"]!="Active" or datetime.now().strftime("%Y-%m-%dT%H:%M")>=slot["booking_start"]:
            db.rollback()
            flash("Slots can only be removed before student booking starts.","danger")
            return redirect(url_for("examiner_slots",exam_id=slot["exam_id"]))
        if db.execute("SELECT 1 FROM bookings WHERE slot_id=?",(slot_id,)).fetchone():
            db.rollback()
            flash("A slot with booking history cannot be deleted.","danger")
            return redirect(url_for("examiner_slots",exam_id=slot["exam_id"]))
        db.execute("DELETE FROM exam_slots WHERE slot_id=?",(slot_id,))
        db.execute("INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",
            (g.user["user_id"],"Slot Deleted","Exam Slot",slot_id,f"{slot['slot_date']} {slot['start_time']}"))
        db.commit()
        flash("Slot deleted.","success")
        return redirect(url_for("examiner_slots",exam_id=slot["exam_id"]))
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Unable to delete this slot.","danger")
        return redirect(url_for("examiner_examinations"))

@app.route("/admin/slots")
@login_required
@role_required("Admin")
def manage_all_slots():
    db=get_db_connection()
    q=request.args.get("q","").strip()
    slots=db.execute("""
        SELECT s.*,e.exam_name,c.course_name,u.name AS examiner_name,
        ep.employee_id,COUNT(b.booking_id) AS booking_count
        FROM exam_slots s
        JOIN examinations e ON e.exam_id=s.exam_id
        JOIN courses c ON c.course_id=e.course_id
        JOIN examiner_profiles ep ON ep.employee_id=s.examiner_id
        JOIN users u ON u.user_id=ep.user_id
        LEFT JOIN bookings b ON b.slot_id=s.slot_id AND b.booking_status='Active'
        WHERE e.exam_name LIKE ? OR c.course_name LIKE ? OR u.name LIKE ?
        OR CAST(s.slot_id AS TEXT)=? OR CAST(s.exam_id AS TEXT)=?
        OR CAST(ep.employee_id AS TEXT)=?
        GROUP BY s.slot_id ORDER BY s.slot_date DESC,s.start_time
    """,(f"%{q}%",f"%{q}%",f"%{q}%",q,q,q)).fetchall()
    return render_template("admin_slots.html",slots=slots,q=q)

@app.route("/examiner/slots/<int:slot_id>/students")
@login_required
@role_required("Examiner")
def examiner_slot_students(slot_id):
    db=get_db_connection()
    examiner=get_current_examiner()
    slot=db.execute("""
        SELECT s.*,e.exam_name FROM exam_slots s
        JOIN examinations e ON e.exam_id=s.exam_id
        WHERE s.slot_id=? AND s.examiner_id=?
    """,(slot_id,examiner["employee_id"])).fetchone()
    if not slot:
        flash("Slot not found or not assigned to you.","danger")
        return redirect(url_for("examiner_examinations"))
    students=db.execute("""
        SELECT b.booking_id,b.booking_status,b.booking_at,
        sp.student_id,sp.enrollment_number,sp.department,sp.semester,u.name
        FROM bookings b
        JOIN student_profiles sp ON sp.student_id=b.student_id
        JOIN users u ON u.user_id=sp.user_id
        WHERE b.slot_id=? AND b.booking_status='Active'
        ORDER BY u.name
    """,(slot_id,)).fetchall()
    return render_template("examiner_slot_students.html",slot=slot,students=students)

@app.route("/admin/examinations/<int:exam_id>/examiners",methods=["GET","POST"])
@login_required
@role_required("Admin")
def manage_exam_assignment(exam_id):
    db=get_db_connection()
    exam=db.execute("SELECT * FROM examinations WHERE exam_id=?",(exam_id,)).fetchone()
    if not exam:
        flash("Examination not found.","danger")
        return redirect(url_for("manage_examinations"))
    if request.method=="POST":
        ids=request.form.getlist("examiner_ids")
        if not ids:
            flash("Select at least one examiner.","warning")
            return redirect(url_for("manage_exam_assignment",exam_id=exam_id))
        try:
            ids=list(dict.fromkeys(int(x) for x in ids))
        except ValueError:
            flash("Invalid examiner selection.","danger")
            return redirect(url_for("manage_exam_assignment",exam_id=exam_id))
        placeholders=",".join("?" for _ in ids)
        eligible=db.execute(f"""
            SELECT ep.employee_id FROM examiner_profiles ep
            JOIN users u ON u.user_id=ep.user_id
            WHERE ep.employee_id IN ({placeholders})
            AND ep.approval_status='Approved' AND u.is_active=1 AND u.role='Examiner'
        """,ids).fetchall()
        if len(eligible)!=len(ids):
            flash("One or more selected examiners are not approved and active.","danger")
            return redirect(url_for("manage_exam_assignment",exam_id=exam_id))
        try:
            db.execute("BEGIN IMMEDIATE")
            for examiner in eligible:
                db.execute("""
                    INSERT OR IGNORE INTO examiners(exam_id,examiner_id,assigned_by)
                    VALUES(?,?,?)
                """,(exam_id,examiner["employee_id"],g.user["user_id"]))
                if db.execute("SELECT changes()").fetchone()[0]:
                    db.execute("""
                        INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details)
                        VALUES(?,?,?,?,?)
                    """,(g.user["user_id"],"Examiner Assigned","Examination",exam_id,f"Examiner ID: {examiner['employee_id']}"))
            db.commit()
            flash("Selected examiners assigned successfully.","success")
        except sqlite3.IntegrityError:
            db.rollback()
            flash("Unable to save examiner assignments.","danger")
        return redirect(url_for("manage_exam_assignment",exam_id=exam_id))
    assigned=db.execute("""
        SELECT ep.employee_id,ep.department,ep.designation,u.name,u.email,u.is_active
        FROM examiners a
        JOIN examiner_profiles ep ON ep.employee_id=a.examiner_id
        JOIN users u ON u.user_id=ep.user_id
        WHERE a.exam_id=? ORDER BY u.name
    """,(exam_id,)).fetchall()
    available=db.execute("""
        SELECT ep.employee_id,ep.department,ep.designation,u.name
        FROM examiner_profiles ep JOIN users u ON u.user_id=ep.user_id
        WHERE ep.approval_status='Approved' AND u.is_active=1
        AND NOT EXISTS(
            SELECT 1 FROM examiners a
            WHERE a.exam_id=? AND a.examiner_id=ep.employee_id
        )
        ORDER BY u.name
    """,(exam_id,)).fetchall()
    return render_template("admin_exam_assignment.html",exam=exam,assigned=assigned,available=available)


@app.route("/admin/examinations/<int:exam_id>/examiners/<int:examiner_id>/remove",methods=["POST"])
@login_required
@role_required("Admin")
def remove_exam_assignment(exam_id,examiner_id):
    db=get_db_connection()
    try:
        db.execute("BEGIN IMMEDIATE")
        assignment=db.execute("""
            SELECT 1 FROM examiners WHERE exam_id=? AND examiner_id=?
        """,(exam_id,examiner_id)).fetchone()
        if not assignment:
            db.rollback()
            flash("Assignment not found.","danger")
            return redirect(url_for("manage_exam_assignment",exam_id=exam_id))
        db.execute("DELETE FROM examiners WHERE exam_id=? AND examiner_id=?",(exam_id,examiner_id))
        db.execute("""
            INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details)
            VALUES(?,?,?,?,?)
        """,(g.user["user_id"],"Examiner Unassigned","Examination",exam_id,f"Examiner ID: {examiner_id}"))
        db.commit()
        flash("Examiner unassigned successfully.","success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Cannot remove this assignment because examination slots already depend on it.","danger")
    return redirect(url_for("manage_exam_assignment",exam_id=exam_id))

