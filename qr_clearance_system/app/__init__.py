from pathlib import Path

from config import Config
from flask import Flask

from .extensions import db, login_manager


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    from .auth import auth_bp
    from .main import main_bp
    from .models import Department, User
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.cli.command("init-db")
    def init_db():
        db.create_all()
        for name, code in [("Library", "LIB"), ("Finance", "FIN"), ("Hostel", "HOST"),
                           ("Sports", "SPORT"), ("Academic Faculty", "ACAD")]:
            if not Department.query.filter_by(code=code).first():
                db.session.add(Department(name=name, code=code))
        db.session.commit()
        print("Database initialized; departments are ready.")

    @app.cli.command("create-admin")
    def create_admin():
        import getpass

        from werkzeug.security import generate_password_hash
        db.create_all()
        email = input("Admin email: ").strip().lower()
        name = input("Admin full name: ").strip()
        password = getpass.getpass("Admin password: ")
        if not email or not name or len(password) < 8:
            print("Enter a name, valid email, and password of at least 8 characters.")
            return
        if User.query.filter_by(email=email).first():
            print("That email is already registered.")
            return
        db.session.add(User(full_name=name, email=email,
                            password_hash=generate_password_hash(password), role="admin"))
        db.session.commit()
        print("Administrator created.")
    return app
