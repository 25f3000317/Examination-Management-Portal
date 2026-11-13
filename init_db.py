from app import app
from app.database import get_db_connection

with app.app_context():
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('Admin', 'Student', 'Examiner')),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN(0, 1)),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS student_profiles (
            student_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            enrollment_number TEXT NOT NULL UNIQUE,
            department TEXT NOT NULL,
            semester INTEGER NOT NULL CHECK(semester > 0),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS examiner_profiles (
            employee_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            department TEXT NOT NULL,
            designation TEXT NOT NULL,
            approval_status TEXT NOT NULL CHECK(approval_status IN ('Pending', 'Approved', 'Rejected')) DEFAULT 'Pending',
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS courses (
            course_id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            course_code TEXT NOT NULL UNIQUE,
            department TEXT NOT NULL,
            description TEXT
        );
        CREATE TABLE IF NOT EXISTS examinations (
            exam_id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            exam_name TEXT NOT NULL,
            exam_type TEXT NOT NULL,
            description TEXT,
            duration INTEGER NOT NULL CHECK(duration > 0),
            max_marks INTEGER NOT NULL CHECK(max_marks > 0),
            slot_creation_start TEXT NOT NULL,
            slot_creation_end TEXT NOT NULL,
            booking_start TEXT NOT NULL,
            booking_end TEXT NOT NULL,
            slot_creation_enabled INTEGER NOT NULL DEFAULT 0 CHECK(slot_creation_enabled IN(0, 1)),
            booking_enabled INTEGER NOT NULL DEFAULT 0 CHECK(booking_enabled IN(0, 1)),
            status TEXT NOT NULL CHECK(status IN ('Draft', 'Active', 'Completed', 'Cancelled')) DEFAULT 'Draft',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE RESTRICT,
            CHECK(slot_creation_start < slot_creation_end),
            CHECK(booking_start < booking_end),
            CHECK(slot_creation_end <= booking_start)
        );
        CREATE TABLE IF NOT EXISTS examiners (
            assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            examiner_id INTEGER NOT NULL,
            assigned_by INTEGER NOT NULL,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (exam_id, examiner_id),
            FOREIGN KEY (exam_id) REFERENCES examinations(exam_id) ON DELETE CASCADE,
            FOREIGN KEY (examiner_id) REFERENCES examiner_profiles(employee_id) ON DELETE CASCADE,
            FOREIGN KEY (assigned_by) REFERENCES users(user_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS rubrics (
            rubric_id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER UNIQUE NOT NULL,
            rubric_name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (exam_id) REFERENCES examinations(exam_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS rubric_criteria (
            criterion_id INTEGER PRIMARY KEY AUTOINCREMENT,
            rubric_id INTEGER NOT NULL,
            criterion_name TEXT NOT NULL,
            description TEXT,
            max_marks INTEGER NOT NULL CHECK(max_marks > 0),
            weightage REAL NOT NULL CHECK(weightage > 0 AND weightage <= 100),
            FOREIGN KEY (rubric_id) REFERENCES rubrics(rubric_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS exam_slots (
            slot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            examiner_id INTEGER NOT NULL,
            slot_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            capacity INTEGER NOT NULL CHECK(capacity > 0),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN(0, 1)),
            UNIQUE (slot_id, exam_id),
            FOREIGN KEY (exam_id) REFERENCES examinations(exam_id) ON DELETE RESTRICT,
            FOREIGN KEY (exam_id, examiner_id) REFERENCES examiners(exam_id, examiner_id) ON DELETE RESTRICT,
            CHECK(start_time < end_time)
        );
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_id INTEGER NOT NULL,
            exam_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            booking_status TEXT NOT NULL CHECK(booking_status IN ('Active', 'Cancelled', 'Completed', 'Rescheduled')) DEFAULT 'Active',
            booking_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (slot_id, exam_id) REFERENCES exam_slots(slot_id, exam_id) ON DELETE RESTRICT,
            FOREIGN KEY (student_id) REFERENCES student_profiles(student_id) ON DELETE RESTRICT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS unique_active_exam_booking
        ON bookings(student_id, exam_id)
        WHERE booking_status = 'Active';

        CREATE TABLE IF NOT EXISTS booking_history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            old_slot_id INTEGER,
            new_slot_id INTEGER,
            action TEXT NOT NULL CHECK(action IN ('Booked', 'Cancelled', 'Rescheduled')),
            changed_by INTEGER NOT NULL,
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings(booking_id) ON DELETE RESTRICT,
            FOREIGN KEY (old_slot_id) REFERENCES exam_slots(slot_id) ON DELETE SET NULL,
            FOREIGN KEY (new_slot_id) REFERENCES exam_slots(slot_id) ON DELETE SET NULL,
            FOREIGN KEY (changed_by) REFERENCES users(user_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS evaluations (
            evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL UNIQUE,
            examiner_id INTEGER NOT NULL,
            total_marks INTEGER NOT NULL CHECK(total_marks >= 0),
            feedback TEXT,
            submitted_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL CHECK(status IN ('Published', 'Submitted', 'Reviewed')) DEFAULT 'Submitted',
            FOREIGN KEY (booking_id) REFERENCES bookings(booking_id) ON DELETE RESTRICT,
            FOREIGN KEY (examiner_id) REFERENCES examiner_profiles(employee_id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS evaluation_scores (
            score_id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluation_id INTEGER NOT NULL,
            criterion_id INTEGER NOT NULL,
            marks_awarded REAL NOT NULL CHECK(marks_awarded >= 0),
            UNIQUE (evaluation_id, criterion_id),
            FOREIGN KEY (evaluation_id) REFERENCES evaluations(evaluation_id) ON DELETE CASCADE,
            FOREIGN KEY (criterion_id) REFERENCES rubric_criteria(criterion_id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_examinations_course
        ON examinations(course_id);

        CREATE INDEX IF NOT EXISTS idx_examiners_exam
        ON examiners(exam_id);

        CREATE INDEX IF NOT EXISTS idx_exam_slots_exam
        ON exam_slots(exam_id);

        CREATE INDEX IF NOT EXISTS idx_exam_slots_examiner
        ON exam_slots(examiner_id);

        CREATE INDEX IF NOT EXISTS idx_bookings_slot
        ON bookings(slot_id);

        CREATE INDEX IF NOT EXISTS idx_bookings_student
        ON bookings(student_id);

        CREATE INDEX IF NOT EXISTS idx_booking_history_booking
        ON booking_history(booking_id);

        CREATE INDEX IF NOT EXISTS idx_evaluations_examiner
        ON evaluations(examiner_id);

        CREATE INDEX IF NOT EXISTS idx_audit_logs_user
        ON audit_logs(user_id);

        CREATE INDEX IF NOT EXISTS idx_audit_logs_entity
        ON audit_logs(entity_type, entity_id);

    ''')

    connection.commit()
