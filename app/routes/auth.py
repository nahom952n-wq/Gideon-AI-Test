"""Authentication routes for public ScholarMind users."""

from datetime import datetime
from functools import wraps

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func

from ..extensions import db
from ..models.user import User

bp = Blueprint("auth", __name__, url_prefix="/auth")


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or not user.is_active:
            session.pop("user_id", None)
            if request.is_json or request.path.startswith("/api/"):
                return {"error": "Authentication required."}, 401
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or not user.is_active:
            return redirect(url_for("auth.login", next=request.full_path))
        if not user.is_admin:
            return ("Forbidden", 403)
        return view(*args, **kwargs)
    return wrapped


@bp.app_context_processor
def inject_auth_user():
    return {"current_user": current_user()}


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        display_name = request.form.get("display_name", "").strip() or None

        if "@" not in email or len(email) < 5:
            flash("Enter a valid email address.", "danger")
            return render_template("auth/register.html")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return render_template("auth/register.html")
        if User.query.filter(func.lower(User.email) == email).first():
            flash("An account with that email already exists.", "warning")
            return render_template("auth/register.html")

        # Production admin bootstrap is explicit. Only the configured owner
        # email receives admin privileges; development keeps first-user convenience.
        configured_admin = current_app.config.get("ADMIN_EMAIL")
        is_admin = bool(configured_admin and email == configured_admin.strip().lower())
        if current_app.config.get("DEBUG", True) and User.query.count() == 0:
            is_admin = True
        user = User(email=email, display_name=display_name, is_admin=is_admin)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        session.clear()
        session["user_id"] = user.id
        flash("Welcome to ScholarMind AI.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter(func.lower(User.email) == email).first()
        if not user or not user.is_active or not user.check_password(password):
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html"), 401

        user.last_login_at = datetime.utcnow()
        db.session.commit()
        session.clear()
        session["user_id"] = user.id
        next_url = request.form.get("next") or request.args.get("next")
        if not next_url or not next_url.startswith("/"):
            next_url = url_for("dashboard.index")
        return redirect(next_url)

    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
