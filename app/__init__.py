import os
import secrets
from pathlib import Path
from flask import Flask
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)

instance_dir = Path(app.instance_path)
instance_dir.mkdir(parents=True, exist_ok=True)
secret_key_file = instance_dir / "secret_key"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
if not app.config["SECRET_KEY"]:
    if secret_key_file.exists():
        app.config["SECRET_KEY"] = secret_key_file.read_text().strip()
    else:
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        secret_key_file.write_text(app.config["SECRET_KEY"])

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
csrf = CSRFProtect(app)

from app import routes
from app.auth_routes import auth

app.register_blueprint(auth)

from app.database import close_db_connection
app.teardown_appcontext(close_db_connection)
