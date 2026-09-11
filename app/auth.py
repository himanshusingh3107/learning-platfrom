import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask import session
from app import db
from app.models import User


auth = Blueprint("auth", __name__)

CERTIFICATE_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}


@auth.route("/signup", methods=["GET", "POST"])
def signup():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "trainee")
        certificate = request.files.get("certificate")

        # Validate role
        if role not in ["trainee", "trainer", "admin"]:
            flash("Invalid role.", "danger")
            return redirect(url_for("auth.signup"))

        # Validate fields
        if not name or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("auth.signup"))

        if role == "trainer" and (not certificate or not certificate.filename):
            flash("Trainers must upload a certificate.", "danger")
            return redirect(url_for("auth.signup"))

        if role == "trainer":
            extension = certificate.filename.rsplit(".", 1)[-1].lower()
            if extension not in CERTIFICATE_EXTENSIONS:
                flash("Certificate must be a PDF, JPG, JPEG, or PNG file.", "danger")
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
            is_active=role != "trainer",
        )

        user.set_password(password)

        if role == "trainer":
            os.makedirs(current_app.config["CERTIFICATE_UPLOAD_FOLDER"], exist_ok=True)
            extension = certificate.filename.rsplit(".", 1)[-1].lower()
            user.certificate_filename = f"{uuid.uuid4().hex}.{extension}"
            user.certificate_original_filename = certificate.filename[:255]
            certificate.save(os.path.join(
                current_app.config["CERTIFICATE_UPLOAD_FOLDER"],
                user.certificate_filename
            ))

        db.session.add(user)
        db.session.commit()
        session["user_id"] = user.id
        return redirect(url_for("auth.account_setup"))

    return render_template("signup.html")


@auth.route("/account-setup", methods=["GET", "POST"])
def account_setup():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.signup"))

    user = User.query.get_or_404(user_id)
    if request.method == "POST":
        user.birthday = request.form.get("birthday", "").strip()[:20] or None
        user.qualification = request.form.get("qualification", "").strip()[:200] or None
        user.work_experience = request.form.get("work_experience", "").strip()[:500] or None
        user.interests = request.form.get("interests", "").strip()[:500] or None
        user.skills = request.form.get("skills", "").strip()[:500] or None
        user.security_question = request.form.get("security_question", "").strip()[:255] or None
        user.security_answer = request.form.get("security_answer", "").strip()[:255] or None
        db.session.commit()
        if user.role == "trainer":
            session.pop("user_id", None)
            flash("Your setup is complete. An admin must approve your trainer account before you can log in.", "success")
            return redirect(url_for("auth.login"))
        flash("Your account setup is complete.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("account_setup.html", user=user)


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

        if user.role == "trainer" and not user.is_active:
            flash("Your trainer account is waiting for admin approval.", "warning")
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