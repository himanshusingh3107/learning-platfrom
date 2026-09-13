import os
import json
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_from_directory, jsonify
from sqlalchemy import or_, select, text
from sqlalchemy.orm import joinedload
from app import db, current_user
from app.models import (
    User, CourseMaterial, CoursePost, TrainerFollow,
    UserActivity, ClassSchedule, Notification, Course, CourseEnrollment,
    CourseProgress, CourseQuiz, CourseQuizQuestion, QuizAttempt, HelpDeskInquiry
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


@bp.route("/api/version")
def version():
    return jsonify({"version": "8d6ff7d-v2", "status": "optimized"})


@bp.route("/")
def index():
    materials = []
    trainers = []
    courses = []
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
                User.is_active.is_(True),
                or_(
                    User.name.ilike(search_pattern),
                    User.user_code.ilike(search_pattern)
                )
            ).order_by(User.name.asc()).all()
            courses = Course.query.join(
                User, Course.trainer_id == User.id
            ).filter(or_(
                Course.title.ilike(search_pattern),
                Course.description.ilike(search_pattern),
                Course.tags.ilike(search_pattern),
                User.name.ilike(search_pattern),
                User.user_code.ilike(search_pattern)
            )).filter(User.is_active.is_(True)).order_by(Course.created_at.desc()).all()
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

        materials = query.options(joinedload(CourseMaterial.trainer)).order_by(CourseMaterial.uploaded_at.desc()).all()
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
        engagement_rows = db.session.query(
            UserActivity.material_id, db.func.count(UserActivity.id)
        ).filter(
            UserActivity.activity_type.in_(["watch", "like"]),
            UserActivity.material_id.isnot(None)
        ).group_by(UserActivity.material_id).all()
        engagement = dict(engagement_rows)

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
    else:
        liked_ids = set()

    return render_template(
        "index.html",
        materials=materials,
        trainers=trainers,
        courses=courses,
        material_filter=material_filter,
        search_query=search_query,
        liked_ids=liked_ids
    )


_admin_stats_cache = {"timestamp": 0, "stats": None}


@bp.route("/dashboard")
def dashboard():
    if not current_user.is_authenticated:
        flash("Please log in to open your dashboard.", "warning")
        return redirect(url_for("auth.login"))

    role = current_user.role

    history = []
    liked_notes = []
    liked_videos = []
    upcoming_classes = []
    notifications = []
    enrolled_courses = []
    explore_courses = []
    trainer_courses = []
    stats = {}

    if role == "trainer":
        trainer_courses = Course.query.filter_by(
            trainer_id=current_user.id
        ).order_by(Course.created_at.desc()).all()
        upcoming_classes = ClassSchedule.query.filter_by(
            trainer_id=current_user.id
        ).order_by(ClassSchedule.scheduled_for.asc()).limit(5).all()
        notifications = Notification.query.filter_by(
            user_id=current_user.id
        ).order_by(Notification.created_at.desc()).limit(5).all()

        stats_row = db.session.execute(text("""
            SELECT 
                (SELECT COUNT(*) FROM course_material),
                (SELECT COUNT(*) FROM user WHERE role = 'trainee')
        """)).fetchone()
        stats = {
            "courses": len(trainer_courses),
            "materials": stats_row[0] if stats_row else 0,
            "trainees": stats_row[1] if stats_row else 0,
        }

    elif role == "trainee":
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

        liked_materials = UserActivity.query.filter_by(
            user_id=current_user.id,
            activity_type="like"
        ).join(
            CourseMaterial,
            UserActivity.material_id == CourseMaterial.id
        ).order_by(
            UserActivity.created_at.desc()
        ).all()
        liked_notes = [activity.material for activity in liked_materials if activity.material.material_type != "video"]
        liked_videos = [activity.material for activity in liked_materials if activity.material.material_type == "video"]

        followed_trainer_ids = db.session.query(TrainerFollow.trainer_id).filter_by(
            trainee_id=current_user.id
        )
        upcoming_classes = ClassSchedule.query.filter(
            ClassSchedule.trainer_id.in_(followed_trainer_ids),
            ClassSchedule.scheduled_for >= datetime.utcnow()
        ).order_by(ClassSchedule.scheduled_for.asc()).limit(5).all()
        notifications = Notification.query.filter_by(
            user_id=current_user.id
        ).order_by(Notification.created_at.desc()).limit(5).all()

        enrolled_courses = (
            Course.query.join(CourseEnrollment, Course.id == CourseEnrollment.course_id)
            .filter(CourseEnrollment.trainee_id == current_user.id)
            .order_by(CourseEnrollment.created_at.desc())
            .all()
        )
        explore_courses = Course.query.order_by(Course.created_at.desc()).limit(6).all()

    else:
        # Admin and Super Admin
        now = datetime.utcnow().timestamp()
        if _admin_stats_cache["stats"] and (now - _admin_stats_cache["timestamp"] < 60):
            stats = _admin_stats_cache["stats"]
        else:
            stats_row = db.session.execute(text("""
                SELECT 
                    (SELECT COUNT(*) FROM course_material),
                    (SELECT COUNT(*) FROM user WHERE role = 'trainer'),
                    (SELECT COUNT(*) FROM user WHERE role = 'trainee'),
                    (SELECT COUNT(*) FROM user),
                    (SELECT COUNT(*) FROM course)
            """)).fetchone()
            stats = {
                "materials": stats_row[0] if stats_row else 0,
                "trainers": stats_row[1] if stats_row else 0,
                "trainees": stats_row[2] if stats_row else 0,
                "users": stats_row[3] if stats_row else 0,
                "courses": stats_row[4] if stats_row else 0,
            }
            _admin_stats_cache["timestamp"] = now
            _admin_stats_cache["stats"] = stats

    return render_template(
        "dashboard.html",
        user=current_user,
        history=history,
        stats=stats,
        liked_notes=liked_notes,
        liked_videos=liked_videos,
        upcoming_classes=upcoming_classes,
        notifications=notifications,
        explore_courses=explore_courses,
        enrolled_courses=enrolled_courses,
        trainer_courses=trainer_courses
    )


@bp.route("/notifications/read", methods=["POST"])
def mark_notifications_read():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return redirect(request.referrer or url_for("main.dashboard"))


@bp.route("/courses")
def courses():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    return redirect(url_for("main.index", type="all"))


@bp.route("/explore-courses")
def explore_courses():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    courses = Course.query.options(joinedload(Course.trainer)).order_by(Course.created_at.desc()).all()
    enrolled_course_ids = set()
    if current_user.role == "trainee":
        enrolled_course_ids = {
            course_id for (course_id,) in db.session.query(CourseEnrollment.course_id).filter_by(
                trainee_id=current_user.id
            ).all()
        }

    return render_template(
        "explore_courses.html",
        courses=courses,
        enrolled_course_ids=enrolled_course_ids,
    )


@bp.route("/courses/<int:course_id>/enroll", methods=["POST"])
def enroll_in_course(course_id):
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if current_user.role != "trainee":
        flash("Only trainees can enroll in courses.", "warning")
        return redirect(url_for("main.explore_courses"))

    course = db.session.get(Course, course_id)
    if course is None:
        return "Course not found", 404

    enrollment = CourseEnrollment.query.filter_by(
        course_id=course.id,
        trainee_id=current_user.id,
    ).first()
    if enrollment:
        flash("You are already enrolled in this course.", "warning")
    else:
        db.session.add(CourseEnrollment(
            course_id=course.id,
            trainee_id=current_user.id,
        ))
        db.session.commit()
        flash(f"You are enrolled in {course.title}.", "success")

    return redirect(url_for("main.course_detail", course_id=course.id))


@bp.route("/settings")
def settings():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    return render_template("settings.html")


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
    if not current_user.is_authenticated:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"error": "Unauthorized"}), 401
        flash("Please log in to like resources.", "warning")
        return redirect(url_for("auth.login"))

    material = CourseMaterial.query.get_or_404(material_id)
    like = UserActivity.query.filter_by(
        user_id=current_user.id,
        material_id=material.id,
        activity_type="like"
    ).first()

    if like:
        db.session.delete(like)
        is_liked = False
        message = "Like removed."
    else:
        db.session.add(UserActivity(
            user_id=current_user.id,
            material_id=material.id,
            activity_type="like"
        ))
        is_liked = True
        message = "Added to your liked learning."
    db.session.commit()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
        return jsonify({
            "success": True,
            "liked": is_liked,
            "material_id": material.id,
            "message": message
        })

    flash(message, "success")
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

    trainers = User.query.filter_by(role="trainer").order_by(
        User.is_active.asc(), User.name.asc()
    ).all()
    pending_admins = []
    if current_user.is_super_admin:
        pending_admins = User.query.filter_by(role="admin", is_active=False).order_by(
            User.name.asc()
        ).all()
    return render_template(
        "admin_users.html",
        users=trainers,
        pending_admins=pending_admins,
        is_super_admin=current_user.is_super_admin,
    )


@bp.route("/admin/notify-trainers", methods=["POST"])
def notify_trainers():
    if not current_user.is_authenticated or current_user.role != "admin":
        flash("Unauthorized action.", "danger")
        return redirect(url_for("auth.login"))

    title = request.form.get("title", "").strip()
    message = request.form.get("message", "").strip()
    if not title or not message or len(title) > 200 or len(message) > 2000:
        flash("Enter a title and message within the allowed length.", "danger")
        return redirect(url_for("main.admin_users"))

    trainers = User.query.filter_by(role="trainer", is_active=True).all()
    db.session.add_all(
        Notification(user_id=trainer.id, title=title, message=message)
        for trainer in trainers
    )
    db.session.commit()
    flash(f"Notification sent to {len(trainers)} active trainer(s).", "success")
    return redirect(url_for("main.admin_users"))


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


@bp.route("/admin/approve-admin/<int:user_id>", methods=["POST"])
def approve_admin(user_id):
    if (
        not current_user.is_authenticated
        or current_user.role != "admin"
        or not current_user.is_super_admin
    ):
        flash("Only a super admin can approve admin accounts.", "danger")
        return redirect(url_for("auth.login"))

    admin = User.query.filter_by(
        id=user_id,
        role="admin",
        is_super_admin=False,
    ).first_or_404()
    admin.is_active = True
    db.session.commit()
    flash(f"Admin '{admin.name}' was approved.", "success")
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

    # Clean up dependent records before removing the account.  In particular,
    # a course requires its trainer_id, so deleting its owner first would make
    # SQLAlchemy try to set course.trainer_id to NULL.
    course_ids = [course_id for (course_id,) in db.session.query(Course.id).filter_by(trainer_id=user_id).all()]
    own_enrollment_ids = [
        enrollment_id for (enrollment_id,) in db.session.query(CourseEnrollment.id).filter_by(trainee_id=user_id).all()
    ]
    course_enrollment_ids = []
    quiz_ids = []
    material_ids = [
        material_id for (material_id,) in db.session.query(CourseMaterial.id).filter_by(trainer_id=user_id).all()
    ]

    if course_ids:
        course_enrollment_ids = [
            enrollment_id for (enrollment_id,) in db.session.query(CourseEnrollment.id).filter(
                CourseEnrollment.course_id.in_(course_ids)
            ).all()
        ]
        quiz_ids = [
            quiz_id for (quiz_id,) in db.session.query(CourseQuiz.id).filter(
                CourseQuiz.course_id.in_(course_ids)
            ).all()
        ]
        material_ids.extend(
            material_id for (material_id,) in db.session.query(CourseMaterial.id).filter(
                CourseMaterial.course_id.in_(course_ids)
            ).all()
        )

    enrollment_ids = list(set(own_enrollment_ids + course_enrollment_ids))
    material_ids = list(set(material_ids))

    if enrollment_ids:
        CourseProgress.query.filter(CourseProgress.enrollment_id.in_(enrollment_ids)).delete(
            synchronize_session=False
        )
        CourseEnrollment.query.filter(CourseEnrollment.id.in_(enrollment_ids)).delete(
            synchronize_session=False
        )

    if quiz_ids:
        QuizAttempt.query.filter(QuizAttempt.quiz_id.in_(quiz_ids)).delete(synchronize_session=False)
        CourseQuizQuestion.query.filter(CourseQuizQuestion.quiz_id.in_(quiz_ids)).delete(
            synchronize_session=False
        )
        CourseQuiz.query.filter(CourseQuiz.id.in_(quiz_ids)).delete(synchronize_session=False)

    activity_filter = UserActivity.user_id == user_id
    if material_ids:
        activity_filter = activity_filter | UserActivity.material_id.in_(material_ids)
    UserActivity.query.filter(activity_filter).delete(synchronize_session=False)
    if material_ids:
        CourseMaterial.query.filter(CourseMaterial.id.in_(material_ids)).delete(
            synchronize_session=False
        )

    CoursePost.query.filter_by(trainer_id=user_id).delete()
    ClassSchedule.query.filter_by(trainer_id=user_id).delete()
    Notification.query.filter_by(user_id=user_id).delete()
    TrainerFollow.query.filter(
        (TrainerFollow.trainer_id == user_id) |
        (TrainerFollow.trainee_id == user_id)
    ).delete(synchronize_session=False)

    if course_ids:
        Course.query.filter(Course.id.in_(course_ids)).delete(synchronize_session=False)

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


@bp.route("/course/<int:course_id>")
def course_detail(course_id):
    if not current_user.is_authenticated:
        flash("Please log in to access this course.", "warning")
        return redirect(url_for("auth.login"))

    course = Course.query.get_or_404(course_id)
    materials = CourseMaterial.query.filter_by(course_id=course.id).order_by(CourseMaterial.id.asc()).all()
    feed_posts = CoursePost.query.filter_by(course_id=course.id).order_by(CoursePost.created_at.desc()).all()

    is_enrolled = False
    progress_map = {}
    progress_percentage = 0
    enrollment = None

    if current_user.role == "trainee":
        enrollment = CourseEnrollment.query.filter_by(
            course_id=course.id,
            trainee_id=current_user.id
        ).first()
        if enrollment:
            is_enrolled = True
            progress_entries = CourseProgress.query.filter_by(enrollment_id=enrollment.id).all()
            progress_map = {entry.material_id: entry.completed for entry in progress_entries}
            progress_percentage = enrollment.progress_percentage()
    else:
        is_enrolled = True

    item_id = request.args.get("item", type=int)
    active_material = None
    if item_id:
        active_material = next((m for m in materials if m.id == item_id), None)
    if not active_material and materials:
        active_material = materials[0]

    if current_user.role == "trainee" and active_material and active_material.material_type == "video":
        recent_act = UserActivity.query.filter(
            UserActivity.user_id == current_user.id,
            UserActivity.material_id == active_material.id,
            UserActivity.activity_type == "watch",
            UserActivity.created_at >= datetime.utcnow() - timedelta(minutes=5)
        ).first()
        if not recent_act:
            db.session.add(UserActivity(
                user_id=current_user.id,
                material_id=active_material.id,
                activity_type="watch"
            ))
            db.session.commit()

    completed_count = sum(1 for m in materials if progress_map.get(m.id))

    liked_ids = set()
    if current_user.is_authenticated:
        liked_ids = {
            act.material_id for act in UserActivity.query.filter_by(
                user_id=current_user.id,
                activity_type="like"
            ).filter(UserActivity.material_id.isnot(None)).all()
        }

    quizzes = CourseQuiz.query.filter_by(course_id=course.id).order_by(CourseQuiz.created_at.desc()).all()
    user_attempts = {}
    if current_user.is_authenticated and current_user.role == "trainee":
        quiz_ids = [q.id for q in quizzes]
        if quiz_ids:
            attempts = QuizAttempt.query.filter(
                QuizAttempt.trainee_id == current_user.id,
                QuizAttempt.quiz_id.in_(quiz_ids)
            ).order_by(QuizAttempt.submitted_at.desc()).all()
            for att in attempts:
                if att.quiz_id not in user_attempts or att.score > user_attempts[att.quiz_id].score:
                    user_attempts[att.quiz_id] = att

    prev_material = None
    next_material = None
    if active_material and active_material in materials:
        curr_idx = materials.index(active_material)
        if curr_idx > 0:
            prev_material = materials[curr_idx - 1]
        if curr_idx < len(materials) - 1:
            next_material = materials[curr_idx + 1]

    return render_template(
        "course_detail.html",
        course=course,
        materials=materials,
        active_material=active_material,
        prev_material=prev_material,
        next_material=next_material,
        feed_posts=feed_posts,
        quizzes=quizzes,
        user_attempts=user_attempts,
        is_enrolled=is_enrolled,
        enrollment=enrollment,
        progress_map=progress_map,
        progress_percentage=progress_percentage,
        completed_count=completed_count,
        liked_ids=liked_ids
    )


@bp.route("/course/<int:course_id>/quiz/<int:quiz_id>", methods=["GET", "POST"])
def take_quiz(course_id, quiz_id):
    if not current_user.is_authenticated:
        flash("Please log in to access course quizzes.", "warning")
        return redirect(url_for("auth.login"))

    course = Course.query.get_or_404(course_id)
    quiz = CourseQuiz.query.filter_by(id=quiz_id, course_id=course.id).first_or_404()
    questions = CourseQuizQuestion.query.filter_by(quiz_id=quiz.id).order_by(CourseQuizQuestion.id.asc()).all()

    if request.method == "POST":
        if current_user.role != "trainee":
            flash("Only trainees can submit quiz attempts.", "warning")
            return redirect(url_for("main.take_quiz", course_id=course.id, quiz_id=quiz.id))

        if not questions:
            flash("This quiz does not have any questions yet.", "warning")
            return redirect(url_for("main.course_detail", course_id=course.id))

        score = 0
        answers_map = {}
        for q in questions:
            selected = request.form.get(f"question_{q.id}", "").strip().upper()
            is_correct = (selected == q.correct_option.upper())
            if is_correct:
                score += 1
            answers_map[str(q.id)] = {
                "selected": selected,
                "correct": q.correct_option.upper(),
                "is_correct": is_correct
            }

        attempt = QuizAttempt(
            quiz_id=quiz.id,
            trainee_id=current_user.id,
            score=score,
            total_questions=len(questions),
            submitted_answers=json.dumps(answers_map)
        )
        db.session.add(attempt)
        db.session.commit()

        percentage = round((score / len(questions)) * 100) if questions else 0
        flash(f"Quiz submitted! You scored {score} out of {len(questions)} ({percentage}%).", "success")

        return render_template(
            "take_quiz.html",
            course=course,
            quiz=quiz,
            questions=questions,
            attempt=attempt,
            answers_map=answers_map,
            result_mode=True,
            percentage=percentage
        )

    # GET request
    latest_attempt = None
    answers_map = {}
    percentage = 0
    if current_user.role == "trainee":
        latest_attempt = QuizAttempt.query.filter_by(
            quiz_id=quiz.id,
            trainee_id=current_user.id
        ).order_by(QuizAttempt.submitted_at.desc()).first()
        if latest_attempt and latest_attempt.submitted_answers:
            try:
                answers_map = json.loads(latest_attempt.submitted_answers)
                percentage = round((latest_attempt.score / latest_attempt.total_questions) * 100) if latest_attempt.total_questions else 0
            except Exception:
                answers_map = {}

    review = request.args.get("review") == "true" and latest_attempt is not None

    return render_template(
        "take_quiz.html",
        course=course,
        quiz=quiz,
        questions=questions,
        attempt=latest_attempt,
        answers_map=answers_map,
        result_mode=review,
        percentage=percentage
    )


@bp.route("/course/<int:course_id>/material/<int:material_id>/progress", methods=["POST"])
def toggle_course_progress(course_id, material_id):
    if not current_user.is_authenticated:
        return jsonify({"error": "Unauthorized"}), 401
    if current_user.role != "trainee":
        return jsonify({"error": "Only trainees can update progress"}), 403

    enrollment = CourseEnrollment.query.filter_by(
        course_id=course_id,
        trainee_id=current_user.id
    ).first_or_404()

    material = CourseMaterial.query.filter_by(
        id=material_id,
        course_id=course_id
    ).first_or_404()

    progress = CourseProgress.query.filter_by(
        enrollment_id=enrollment.id,
        material_id=material.id
    ).first()

    if not progress:
        progress = CourseProgress(
            enrollment_id=enrollment.id,
            material_id=material.id,
            completed=True,
            completed_at=datetime.utcnow()
        )
        db.session.add(progress)
    else:
        progress.completed = not progress.completed
        progress.completed_at = datetime.utcnow() if progress.completed else None

    db.session.commit()

    total_materials = CourseMaterial.query.filter_by(course_id=course_id).count()
    completed_count = CourseProgress.query.filter_by(enrollment_id=enrollment.id, completed=True).count()
    percentage = round((completed_count / total_materials * 100)) if total_materials > 0 else 0

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
        return jsonify({
            "success": True,
            "completed": progress.completed,
            "completed_count": completed_count,
            "total_materials": total_materials,
            "progress_percentage": percentage
        })

    return redirect(url_for("main.course_detail", course_id=course_id, item=material.id))


@bp.route("/help-desk", methods=["GET", "POST"])
def help_desk():
    if not current_user.is_authenticated:
        flash("Please log in to access the Trainee Help Desk.", "warning")
        return redirect(url_for("auth.login"))

    if current_user.role != "trainee":
        flash("The Help Desk is available for trainees.", "info")
        return redirect(url_for("main.dashboard"))

    admin_email = current_app.config.get("ADMIN_EMAIL", "vs6231588@gmail.com")

    if request.method == "POST":
        category = request.form.get("category", "General").strip()[:50]
        subject = request.form.get("subject", "").strip()[:200]
        message = request.form.get("message", "").strip()

        if not subject or not message:
            flash("Please fill in both the subject and your message.", "danger")
            return redirect(url_for("main.help_desk"))

        if len(message) > 5000:
            flash("Message must be 5,000 characters or fewer.", "danger")
            return redirect(url_for("main.help_desk"))

        inquiry = HelpDeskInquiry(
            trainee_id=current_user.id,
            admin_email=admin_email,
            category=category,
            subject=subject,
            message=message,
            status="open"
        )
        db.session.add(inquiry)

        # Notify active admin users in-app
        admins = User.query.filter_by(role="admin", is_active=True).all()
        for admin in admins:
            db.session.add(Notification(
                user_id=admin.id,
                title=f"New Help Desk Ticket: {subject[:40]}",
                message=f"Trainee {current_user.name} ({current_user.email}) submitted a {category} ticket: {message[:120]}"
            ))

        db.session.commit()
        flash(f"Your inquiry has been submitted to the administrator ({admin_email}). We will get back to you shortly!", "success")
        return redirect(url_for("main.help_desk"))

    inquiries = HelpDeskInquiry.query.filter_by(
        trainee_id=current_user.id
    ).order_by(HelpDeskInquiry.created_at.desc()).all()

    return render_template(
        "help_desk.html",
        inquiries=inquiries,
        admin_email=admin_email
    )
