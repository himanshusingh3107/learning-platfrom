import os
import uuid
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    send_from_directory
)


from app import db, current_user
from app.models import Course, CourseMaterial, UserActivity, ClassSchedule, Notification, TrainerFollow


trainer = Blueprint(
    "trainer",
    __name__,
    url_prefix="/trainer"
)


ALLOWED_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "txt",
    "mp4",
    "webm"
}

THUMBNAIL_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}


def allowed_file(filename):

    if "." not in filename:
        return False

    extension = filename.rsplit(
        ".",
        1
    )[1].lower()

    return extension in ALLOWED_EXTENSIONS


def _schedule_datetime(value):
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


def _notify_followers(trainer_id, title, message):
    follower_ids = db.session.query(TrainerFollow.trainee_id).filter_by(
        trainer_id=trainer_id
    ).all()
    db.session.add_all(
        Notification(user_id=trainee_id, title=title, message=message)
        for (trainee_id,) in follower_ids
    )


@trainer.route("/courses", methods=["GET", "POST"])
def manage_courses():
    if current_user.role != "trainer":
        return "Access Denied", 403

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        if not title or len(title) > 200:
            flash("Enter a course title with 200 characters or fewer.", "danger")
            return redirect(url_for("trainer.manage_courses"))
        if len(description) > 5000:
            flash("Course description must be 5,000 characters or fewer.", "danger")
            return redirect(url_for("trainer.manage_courses"))

        course = Course(
            title=title,
            description=description or None,
            trainer_id=current_user.id,
        )
        db.session.add(course)
        db.session.flush()
        _notify_followers(
            current_user.id,
            "New course launched",
            f"{title} is now available to explore.",
        )
        db.session.commit()
        flash("Course launched and followers notified.", "success")
        return redirect(url_for("trainer.manage_courses"))

    courses = Course.query.filter_by(trainer_id=current_user.id).order_by(
        Course.created_at.desc()
    ).all()
    return render_template("trainer_courses.html", courses=courses)


@trainer.route("/classes", methods=["GET", "POST"])
def manage_classes():
    if current_user.role != "trainer":
        return "Access Denied", 403

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        scheduled_for = _schedule_datetime(request.form.get("scheduled_for"))
        if not title or len(title) > 200 or scheduled_for is None:
            flash("Enter a title and a valid class date and time.", "danger")
            return redirect(url_for("trainer.manage_classes"))

        class_schedule = ClassSchedule(
            trainer_id=current_user.id,
            title=title,
            description=description or None,
            scheduled_for=scheduled_for
        )
        db.session.add(class_schedule)
        db.session.flush()
        _notify_followers(
            current_user.id,
            "New class from your trainer",
            f"{title} is scheduled for {scheduled_for.strftime('%b %d at %I:%M %p')}."
        )
        db.session.commit()
        flash("Class published and followers notified.", "success")
        return redirect(url_for("trainer.manage_classes"))

    classes = ClassSchedule.query.filter_by(
        trainer_id=current_user.id
    ).order_by(ClassSchedule.scheduled_for.asc()).all()
    return render_template("trainer_classes.html", classes=classes)


@trainer.route("/classes/<int:class_id>/edit", methods=["GET", "POST"])
def edit_class(class_id):
    if current_user.role != "trainer":
        return "Access Denied", 403

    class_schedule = ClassSchedule.query.filter_by(
        id=class_id,
        trainer_id=current_user.id
    ).first_or_404()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        scheduled_for = _schedule_datetime(request.form.get("scheduled_for"))
        if not title or len(title) > 200 or scheduled_for is None:
            flash("Enter a title and a valid class date and time.", "danger")
            return redirect(url_for("trainer.edit_class", class_id=class_id))

        class_schedule.title = title
        class_schedule.description = request.form.get("description", "").strip() or None
        class_schedule.scheduled_for = scheduled_for
        _notify_followers(
            current_user.id,
            "Class updated by your trainer",
            f"{title} is now scheduled for {scheduled_for.strftime('%b %d at %I:%M %p')}."
        )
        db.session.commit()
        flash("Class updated and followers notified.", "success")
        return redirect(url_for("trainer.manage_classes"))

    return render_template("trainer_class_form.html", class_schedule=class_schedule)


@trainer.route("/classes/<int:class_id>/delete", methods=["POST"])
def delete_class(class_id):
    if current_user.role != "trainer":
        return "Access Denied", 403
    class_schedule = ClassSchedule.query.filter_by(id=class_id, trainer_id=current_user.id).first_or_404()
    _notify_followers(
        current_user.id,
        "Class cancelled by your trainer",
        f"{class_schedule.title} has been cancelled."
    )
    db.session.delete(class_schedule)
    db.session.commit()
    flash("Class cancelled and followers notified.", "success")
    return redirect(url_for("trainer.manage_classes"))


@trainer.route("/library")
def library():

    if current_user.role != "trainer":
        return "Access Denied", 403

    materials = CourseMaterial.query.filter_by(
        trainer_id=current_user.id
    ).order_by(
        CourseMaterial.uploaded_at.desc()
    ).all()

    return render_template(
        "trainer_library.html",
        materials=materials
    )


@trainer.route("/upload-material", methods=["GET", "POST"])
def upload_material():

    if current_user.role != "trainer":
        return "Access Denied", 403

    if request.method == "POST":

        title = request.form.get(
            "title",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        tags = ", ".join(
            tag.strip() for tag in request.form.get("tags", "").split(",")
            if tag.strip()
        )
        location = request.form.get("location", "").strip()[:120] or None

        material_type = request.form.get("material_type", "note")

        file = request.files.get("file")
        thumbnail = request.files.get("thumbnail")

        if not title or len(title) > 200:
            flash(
                "Material title is required and must be 200 characters or fewer.",
                "danger"
            )
            return redirect(
                url_for("trainer.upload_material")
            )

        if description and len(description) > 5000:
            flash(
                "Description is too long.",
                "danger"
            )

        if material_type not in {"note", "video"}:
            flash("Invalid material type.", "danger")
            return redirect(url_for("trainer.upload_material"))
            return redirect(
                url_for("trainer.upload_material")
            )

        if not file or file.filename == "":
            flash(
                "Please select a file.",
                "danger"
            )
            return redirect(
                url_for("trainer.upload_material")
            )

        if not allowed_file(file.filename):
            flash(
                "This file type is not allowed.",
                "danger"
            )
            return redirect(url_for("trainer.upload_material"))

        thumbnail_filename = None
        if thumbnail and thumbnail.filename:
            thumbnail_extension = thumbnail.filename.rsplit(".", 1)[-1].lower()
            if thumbnail_extension not in THUMBNAIL_EXTENSIONS or not thumbnail.mimetype.startswith("image/"):
                flash("Thumbnail must be a JPG, PNG, GIF, or WEBP image.", "danger")
                return redirect(url_for("trainer.upload_material"))

            thumbnail_filename = f"{uuid.uuid4().hex}.{thumbnail_extension}"
            thumbnail_folder = current_app.config["THUMBNAIL_UPLOAD_FOLDER"]
            os.makedirs(thumbnail_folder, exist_ok=True)
            thumbnail.save(os.path.join(thumbnail_folder, thumbnail_filename))

        extension = file.filename.rsplit(".", 1)[-1].lower()
        if material_type == "video" and extension not in {"mp4", "webm"}:
            flash("Video solutions must be MP4 or WEBM files.", "danger")
            return redirect(url_for("trainer.upload_material"))
        if material_type == "note" and extension in {"mp4", "webm"}:
            flash("Choose Video Solution for MP4 or WEBM files.", "danger")
            return redirect(url_for("trainer.upload_material"))
            return redirect(
                url_for("trainer.upload_material")
            )

        original_filename = (
            file.filename
        )

        extension = original_filename.rsplit(".", 1)[1].lower()

        # Generate a random filename
        random_filename = (
            f"{uuid.uuid4().hex}.{extension}"
        )

        upload_folder = current_app.config[
            "UPLOAD_FOLDER"
        ]

        os.makedirs(
            upload_folder,
            exist_ok=True
        )

        file.save(
            os.path.join(
                upload_folder,
                random_filename
            )
        )

        material = CourseMaterial(
            title=title,
            description=description,
            filename=random_filename,
            original_filename=original_filename,
            file_type=extension,
            material_type=material_type,
            tags=tags or None,
            location=location,
            trainer_id=current_user.id,
            thumbnail_filename=thumbnail_filename
        )

        db.session.add(material)
        db.session.commit()

        flash(
            "Course material uploaded successfully.",
            "success"
        )

        return redirect(
            url_for("trainer.library")
        )

    return render_template(
        "upload_material.html"
    )


@trainer.route("/material/<int:material_id>/delete", methods=["POST"])
def delete_material(material_id):
    if current_user.role != "trainer":
        return "Access Denied", 403

    material = CourseMaterial.query.filter_by(
        id=material_id,
        trainer_id=current_user.id
    ).first_or_404()

    file_path = os.path.join(
        current_app.config["UPLOAD_FOLDER"],
        material.filename
    )
    if os.path.isfile(file_path):
        os.remove(file_path)

    if material.thumbnail_filename:
        thumbnail_path = os.path.join(
            current_app.config["THUMBNAIL_UPLOAD_FOLDER"],
            material.thumbnail_filename
        )
        if os.path.isfile(thumbnail_path):
            os.remove(thumbnail_path)

    db.session.delete(material)
    db.session.commit()
    flash("Course note deleted successfully.", "success")
    return redirect(url_for("trainer.library"))


@trainer.route("/material/<int:material_id>")
def view_material(material_id):

    material = db.session.get(
        CourseMaterial,
        material_id
    )

    if not material:
        return "Material not found", 404

    if current_user.role == "trainee":
        db.session.add(UserActivity(
            user_id=current_user.id,
            material_id=material.id,
            activity_type="watch"
        ))
        db.session.commit()

    return render_template(
        "view_material.html",
        material=material
    )


@trainer.route("/download/<int:material_id>")
def download_material(material_id):

    material = db.session.get(
        CourseMaterial,
        material_id
    )

    if not material:
        return "Material not found", 404

    if current_user.role == "trainee" and (
        material.material_type == "video" or material.file_type == "pdf"
    ):
        activity_type = "watch" if material.material_type == "video" else "download"
        recent_activity = UserActivity.query.filter(
            UserActivity.user_id == current_user.id,
            UserActivity.material_id == material.id,
            UserActivity.activity_type == activity_type,
            UserActivity.created_at >= datetime.utcnow() - timedelta(minutes=5)
        ).first()
        if not recent_activity:
            db.session.add(UserActivity(
                user_id=current_user.id,
                material_id=material.id,
                activity_type=activity_type
            ))
            db.session.commit()

    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        material.filename,
        as_attachment=material.material_type != "video",
        download_name=material.original_filename
    )


@trainer.route("/thumbnail/<filename>")
def material_thumbnail(filename):
    return send_from_directory(
        current_app.config["THUMBNAIL_UPLOAD_FOLDER"],
        filename
    )


@trainer.route("/material/<int:material_id>/watch", methods=["POST"])
def record_video_watch(material_id):
    material = CourseMaterial.query.filter_by(
        id=material_id,
        material_type="video"
    ).first_or_404()

    if current_user.role != "trainee":
        return "Access Denied", 403

    db.session.add(UserActivity(
        user_id=current_user.id,
        material_id=material.id,
        activity_type="watch"
    ))
    db.session.commit()
    return "", 204
