from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import User

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        reg = request.form.get("registration_number", "").strip().upper()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not all([name, reg, email, password, confirm]):
            flash("Please complete all fields.", "danger")
        elif password != confirm:
            flash("Passwords do not match.", "danger")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("That email is already registered.", "danger")
        elif User.query.filter_by(registration_number=reg).first():
            flash("That registration number is already registered.", "danger")
        else:
            db.session.add(User(full_name=name, registration_number=reg, email=email,
                                password_hash=generate_password_hash(password), role="student"))
            db.session.commit()
            flash("Account created. You can now sign in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html")

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email, is_active=True).first()
        if user and user.check_password(password):
            login_user(user)
            flash("Welcome back.", "success")
            return redirect(url_for("main.dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("auth/login.html")

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have signed out.", "info")
    return redirect(url_for("auth.login"))
