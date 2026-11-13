from getpass import getpass
import sqlite3
from werkzeug.security import generate_password_hash
from app import app
from app.database import get_db_connection

def create_admin():
    print("\nExamination Portal: Admin Setup\n")
    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip().lower()
    password = getpass("Admin password (minimum 1 characters): ")
    confirm = getpass("Confirm password: ")
    if not name or not email:
        print("Invalid name or email.")
        return
    # password is changed to 1 for development purposes can be changed to 8 characters by changing the below lines and doing the same in auth_routes.py as well
    if len(password) < 1:
        print("Password must contain at least 1 characters.")
        return
    if password != confirm:
        print("Passwords do not match.")
        return
    with app.app_context():
        db = get_db_connection()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing_admin = db.execute(
                "SELECT user_id FROM users WHERE role = 'Admin' LIMIT 1"
            ).fetchone()
            if existing_admin:
                db.rollback()
                print("An Admin account already exists. Setup cancelled.")
                return
            db.execute(
                """
                INSERT INTO users (name, email, password_hash, role)
                VALUES (?, ?, ?, 'Admin')
                """,
                (name, email, generate_password_hash(password))
            )
            db.commit()
            print("\nAdmin account created successfully.")
        except sqlite3.IntegrityError:
            db.rollback()
            print("That email address is already registered.")

if __name__ == "__main__":
    create_admin()
