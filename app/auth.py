from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask import session
from app import db
from app.models import User


auth = Blueprint("auth", __name__)


@auth.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "trainee")

        # Validate role
        if role not in ["trainee", "trainer"]:
            flash("Invalid role.", "danger")
            return redirect(url_for("auth.signup"))

        # Validate fields
        if not name or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("auth.signup"))

        if len(name) > 100 or len(email) > 120:
            flash("Name or email is too long.", "danger")
            return redirect(url_for("auth.signup"))

        if len(password) < 8 or len(password) > 128:
            flash(
                "Password must contain 8 to 128 characters.",
                "danger"
            )
            return redirect(url_for("auth.signup"))

        # Check existing user
        existing_user = User.query.filter_by(
            email=email
        ).first()

        if existing_user:
            flash("Email already registered.", "danger")
            return redirect(url_for("auth.signup"))

        # Create user
        user = User(
            name=name,
            email=email,
            role=role,
        )

        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("Registration successful. You can now log in.", "success")

        return redirect(url_for("auth.login"))

    return render_template("signup.html")


@auth.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if len(email) > 120 or len(password) > 128:
            flash("Invalid email or password.", "danger")
            return redirect(url_for("auth.login"))

        user = User.query.filter_by(
            email=email
        ).first()

        if not user or not user.check_password(password):
            flash(
                "Invalid email or password.",
                "danger"
            )
            return redirect(url_for("auth.login"))

        session["user_id"] = user.id

        return redirect(url_for("main.index"))

    return render_template("login.html")


@auth.route("/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(url_for("main.index"))