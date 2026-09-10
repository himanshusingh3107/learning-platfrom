import os
import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_from_directory
from sqlalchemy import or_, select
from app import db, current_user
from app.models import (
    User, CourseMaterial, CoursePost, TrainerFollow,
    UserActivity
)

bp = Blueprint("main", __name__)

PROFILE_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}


def _terms(value):
    return {
        term.strip().lower()
        for term in (value or "").replace(",", " ").split()
        if term.strip()
    }


def allowed_file(filename):
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_EXTENSIONS"]


@bp.route("/")
def index():
    materials = []
    trainers = []
    material_filter = request.args.get("type", "all")
    search_query = request.args.get("q", "").strip()
    if material_filter not in {"notes", "videos", "all", "following"}:
        material_filter = "notes"

    if current_user.is_authenticated:
        query = CourseMaterial.query
        if material_filter == "following" and current_user.role == "trainee":
            followed_trainer_ids = select(TrainerFollow.trainer_id).filter_by(
                trainee_id=current_user.id
            )
            query = query.filter(CourseMaterial.trainer_id.in_(followed_trainer_ids))
        elif material_filter == "following":
            material_filter = "notes"

        if search_query:
            db.session.add(UserActivity(
                user_id=current_user.id,
                activity_type="search",
                search_term=search_query[:200]
            ))
            db.session.commit()
            search_pattern = f"%{search_query}%"
            trainers = User.query.filter(
                User.role == "trainer",
                or_(
                    User.name.ilike(search_pattern),
                    User.user_code.ilike(search_pattern)
                )
            ).order_by(User.name.asc()).all()
            query = query.join(User, CourseMaterial.trainer_id == User.id).filter(or_(
                CourseMaterial.title.ilike(search_pattern),
                CourseMaterial.description.ilike(search_pattern),
                CourseMaterial.tags.ilike(search_pattern),
                User.name.ilike(search_pattern),
                User.user_code.ilike(search_pattern)
            ))

        if material_filter == "notes":
            query = query.filter(
                (CourseMaterial.material_type == "note") |
                (CourseMaterial.material_type.is_(None))
            )
        elif material_filter == "videos":
            query = query.filter(CourseMaterial.material_type == "video")

        materials = query.order_by(CourseMaterial.uploaded_at.desc()).all()
        followed_ids = {
            trainer_id for (trainer_id,) in db.session.query(
                TrainerFollow.trainer_id
            ).filter_by(trainee_id=current_user.id).all()
        }
        activities = UserActivity.query.filter_by(
            user_id=current_user.id
        ).order_by(UserActivity.created_at.desc()).limit(100).all()
        interest_terms = _terms(current_user.interests)
        history_terms = set().union(*(
            _terms(activity.search_term)
            for activity in activities
            if activity.activity_type == "search"
        )) if activities else set()
        watched_ids = {
            activity.material_id for activity in activities
            if activity.activity_type == "watch" and activity.material_id
        }
        liked_ids = {
            activity.material_id for activity in activities
            if activity.activity_type == "like" and activity.material_id
        }
        engagement = {}
        for material in materials:
            engagement[material.id] = sum(
                1 for activity in material.activities
                if activity.activity_type in {"watch", "like"}
            )

        def recommendation_score(material):
            content_terms = _terms(
                f"{material.title} {material.description} {material.tags}"
            )
            score = len(content_terms & interest_terms) * 8
            score += len(content_terms & history_terms) * 5
            score += 7 if material.trainer_id in followed_ids else 0
            score += 5 if material.id in liked_ids else 0
            score += 3 if material.id in watched_ids else 0
            if current_user.location and material.location:
                score += 4 if current_user.location.lower() == material.location.lower() else 0
            score += min(engagement.get(material.id, 0), 10)
            return score

        materials.sort(
            key=lambda material: (
                recommendation_score(material),
                material.uploaded_at or datetime.min
            ),
            reverse=True
        )

    return render_template(
        "index.html",
        materials=materials,
        trainers=trainers,
        material_filter=material_filter,
        search_query=search_query
    )


@bp.route("/dashboard")
def dashboard():
    if not current_user.is_authenticated:
        flash("Please log in to open your dashboard.", "warning")
        return redirect(url_for("auth.login"))

    history = UserActivity.query.filter(
        UserActivity.user_id == current_user.id,
        UserActivity.activity_type.in_(["watch", "download"]),
        UserActivity.material_id.isnot(None)
    ).join(
        CourseMaterial,
        UserActivity.material_id == CourseMaterial.id
    ).order_by(
        UserActivity.created_at.desc()
    ).limit(5).all()

    return render_template(
        "dashboard.html",
        user=current_user,
        history=history
    )


@bp.route("/dashboard/history")
def history():
    if not current_user.is_authenticated:
        flash("Please log in to view your history.", "warning")
        return redirect(url_for("auth.login"))

    history_items = UserActivity.query.filter(
        UserActivity.user_id == current_user.id,
        UserActivity.activity_type.in_(["watch", "download"]),
        UserActivity.material_id.isnot(None)
    ).join(
        CourseMaterial,
        UserActivity.material_id == CourseMaterial.id
    ).order_by(
        UserActivity.created_at.desc()
    ).all()

    return render_template(
        "history.html",
        user=current_user,
        history=history_items
    )


@bp.route("/dashboard/history/<int:activity_id>/delete", methods=["POST"])
def delete_history_item(activity_id):
    activity = UserActivity.query.filter(
        UserActivity.id == activity_id,
        UserActivity.user_id == current_user.id,
        UserActivity.activity_type.in_(["watch", "download"])
    ).first_or_404()

    db.session.delete(activity)
    db.session.commit()
    flash("History item removed.", "success")
    return redirect(url_for("main.dashboard"))


@bp.route("/profile", methods=["GET", "POST"])
def profile():
    user = current_user.user
    if user is None:
        flash("Please log in to open your profile.", "warning")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        photo = request.files.get("photo")

        if not name or len(name) > 100:
            flash("Name is required and must be 100 characters or fewer.", "danger")
            return redirect(url_for("main.profile"))

        user.name = name
        user.location = request.form.get("location", "").strip()[:120] or None
        user.interests = request.form.get("interests", "").strip()[:500] or None
        old_photo = user.profile_photo

        if request.form.get("remove_photo") == "yes":
            user.profile_photo = None

        if photo and photo.filename:
            extension = photo.filename.rsplit(".", 1)[-1].lower()
            if extension not in PROFILE_IMAGE_EXTENSIONS or not photo.mimetype.startswith("image/"):
                flash("Please upload a JPG, PNG, GIF, or WEBP image.", "danger")
                return redirect(url_for("main.profile"))

            os.makedirs(current_app.config["PROFILE_UPLOAD_FOLDER"], exist_ok=True)
            filename = f"{user.id}_{uuid.uuid4().hex}.{extension}"
            photo.save(os.path.join(current_app.config["PROFILE_UPLOAD_FOLDER"], filename))
            user.profile_photo = filename

        photo_in_use = User.query.filter(
            User.profile_photo == old_photo,
            User.id != user.id
        ).first()
        if old_photo and old_photo != current_user.profile_photo and not photo_in_use:
            old_photo_path = os.path.join(
                current_app.config["PROFILE_UPLOAD_FOLDER"],
                old_photo
            )
            if os.path.exists(old_photo_path):
                os.remove(old_photo_path)

        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("main.profile"))

    follower_count = 0
    if current_user.role == "trainer":
        follower_count = TrainerFollow.query.filter_by(
            trainer_id=current_user.id
        ).count()

    return render_template(
        "profile.html",
        user=user,
        follower_count=follower_count
    )


@bp.route("/material/<int:material_id>/like", methods=["POST"])
def toggle_material_like(material_id):
    material = CourseMaterial.query.get_or_404(material_id)
    like = UserActivity.query.filter_by(
        user_id=current_user.id,
        material_id=material.id,
        activity_type="like"
    ).first()
    if like:
        db.session.delete(like)
        flash("Like removed.", "success")
    else:
        db.session.add(UserActivity(
            user_id=current_user.id,
            material_id=material.id,
            activity_type="like"
        ))
        flash("Added to your liked learning.", "success")
    db.session.commit()
    return redirect(request.referrer or url_for("main.index"))


@bp.route("/profile/photo/<filename>")
def profile_photo(filename):
    response = send_from_directory(
        current_app.config["PROFILE_UPLOAD_FOLDER"],
        filename
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/trainer/<int:trainer_id>")
def trainer_profile(trainer_id):
    trainer = User.query.filter_by(id=trainer_id, role="trainer").first_or_404()
    follower_count = TrainerFollow.query.filter_by(trainer_id=trainer.id).count()
    following = TrainerFollow.query.filter_by(
        trainee_id=current_user.id,
        trainer_id=trainer.id
    ).first() is not None
    return render_template(
        "trainer_profile.html",
        trainer=trainer,
        follower_count=follower_count,
        following=following
    )


@bp.route("/trainer/<int:trainer_id>/follow", methods=["POST"])
def toggle_trainer_follow(trainer_id):
    trainer = User.query.filter_by(id=trainer_id, role="trainer").first_or_404()

    if current_user.role != "trainee":
        flash("Only trainees can follow trainers.", "warning")
        return redirect(url_for("main.trainer_profile", trainer_id=trainer.id))

    if current_user.id == trainer.id:
        flash("You cannot follow yourself.", "warning")
        return redirect(url_for("main.trainer_profile", trainer_id=trainer.id))

    follow = TrainerFollow.query.filter_by(
        trainee_id=current_user.id,
        trainer_id=trainer.id
    ).first()

    if follow:
        db.session.delete(follow)
        flash(f"You unfollowed {trainer.name}.", "success")
    else:
        db.session.add(TrainerFollow(
            trainee_id=current_user.id,
            trainer_id=trainer.id
        ))
        flash(f"You are now following {trainer.name}.", "success")

    db.session.commit()
    return redirect(url_for("main.trainer_profile", trainer_id=trainer.id))


# --- Admin Routes ---

@bp.route("/admin/users")
def admin_users():
    if not current_user.is_authenticated or current_user.role != "admin":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    users = User.query.order_by(User.is_active.asc(), User.name.asc()).all()
    return render_template("admin_users.html", users=users)


@bp.route("/admin/approve-trainer/<int:user_id>", methods=["POST"])
def approve_trainer(user_id):
    if not current_user.is_authenticated or current_user.role != "admin":
        flash("Unauthorized action.", "danger")
        return redirect(url_for("auth.login"))

    trainer = User.query.filter_by(id=user_id, role="trainer").first_or_404()
    trainer.is_active = True
    db.session.commit()
    flash(f"Trainer '{trainer.name}' was approved.", "success")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/certificate/<int:user_id>")
def trainer_certificate(user_id):
    if not current_user.is_authenticated or current_user.role != "admin":
        flash("Unauthorized access.", "danger")
        return redirect(url_for("auth.login"))

    trainer = User.query.filter_by(id=user_id, role="trainer").first_or_404()
    if not trainer.certificate_filename:
        flash("This trainer has not uploaded a certificate.", "warning")
        return redirect(url_for("main.admin_users"))

    return send_from_directory(
        current_app.config["CERTIFICATE_UPLOAD_FOLDER"],
        trainer.certificate_filename,
        as_attachment=False,
        download_name=trainer.certificate_original_filename
    )


@bp.route("/admin/delete-user/<int:user_id>", methods=["POST"])
def delete_user(user_id):
    if not current_user.is_authenticated or current_user.role != "admin":
        flash("Unauthorized action.", "danger")
        return redirect(url_for("auth.login"))

    if current_user.id == user_id:
        flash("You cannot delete your own account.", "warning")
        return redirect(url_for("main.admin_users"))

    user_to_delete = User.query.get_or_404(user_id)

    # Clean up associated content before removing the user.
    CourseMaterial.query.filter_by(trainer_id=user_id).delete()
    CoursePost.query.filter_by(trainer_id=user_id).delete()
    UserActivity.query.filter_by(user_id=user_id).delete()
    TrainerFollow.query.filter(
        (TrainerFollow.trainer_id == user_id) |
        (TrainerFollow.trainee_id == user_id)
    ).delete(synchronize_session=False)

    db.session.delete(user_to_delete)
    db.session.commit()

    flash(f"User '{user_to_delete.name}' was removed successfully.", "success")
    return redirect(url_for("main.admin_users"))


# --- Photo Upload & Feed Routes ---

@bp.route("/course/<int:course_id>/upload", methods=["GET", "POST"])
def upload_photo(course_id):
    if current_user.role != "trainer":
        flash("Only trainers can upload content.", "danger")
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        tags = request.form.get("tags", "")
        file = request.files.get("photo")

        if not title or len(title.strip()) > 200:
            flash("A title of 200 characters or fewer is required.", "danger")
            return redirect(request.url)

        if description and len(description) > 5000:
            flash("Description is too long.", "danger")
            return redirect(request.url)

        tags = ", ".join(
            tag.strip() for tag in tags.split(",") if tag.strip()
        )
        if len(tags) > 500:
            flash("Tags are too long.", "danger")
            return redirect(request.url)

        if not file or file.filename == "":
            flash("Please select an image file.", "warning")
            return redirect(request.url)

        if file and allowed_file(file.filename):
            extension = file.filename.rsplit(".", 1)[1].lower()
            unique_filename = f"{current_user.id}_{uuid.uuid4().hex}.{extension}"

            upload_dir = current_app.config["UPLOAD_FOLDER"]
            os.makedirs(upload_dir, exist_ok=True)

            file.save(os.path.join(upload_dir, unique_filename))

            post = CoursePost(
                title=title,
                description=description,
                tags=tags or None,
                image_filename=unique_filename,
                course_id=course_id,
                trainer_id=current_user.id
            )
            db.session.add(post)
            db.session.commit()

            flash("Educational photo added to feed!", "success")
            return redirect(url_for("main.course_feed", course_id=course_id))

        flash("Invalid file extension.", "danger")

    return render_template("upload.html", course_id=course_id)


@bp.route("/course/<int:course_id>/feed")
def course_feed(course_id):
    posts = CoursePost.query.filter_by(course_id=course_id).order_by(db.func.random()).all()
    return render_template("feed.html", posts=posts, course_id=course_id)


@bp.route("/course-post/<int:post_id>/delete", methods=["POST"])
def delete_course_post(post_id):
    post = CoursePost.query.filter_by(
        id=post_id,
        trainer_id=current_user.id
    ).first_or_404()

    file_path = os.path.join(
        current_app.config["UPLOAD_FOLDER"],
        post.image_filename
    )
    if os.path.isfile(file_path):
        os.remove(file_path)

    course_id = post.course_id
    db.session.delete(post)
    db.session.commit()
    flash("Course post deleted successfully.", "success")
    return redirect(url_for("main.course_feed", course_id=course_id))