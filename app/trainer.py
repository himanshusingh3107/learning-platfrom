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
from app.models import (
    Course,
    CourseMaterial,
    UserActivity,
    ClassSchedule,
    Notification,
    TrainerFollow,
    CourseEnrollment,
    CourseProgress,
    CourseQuiz,
    CourseQuizQuestion,
    QuizAttempt,
    CoursePost,
)


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


@trainer.route("/my-courses")
@trainer.route("/courses", methods=["GET", "POST"])
def manage_courses():
    if current_user.role != "trainer":
        return "Access Denied", 403

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        tags = request.form.get("tags", "").strip()
        if not title or len(title) > 200:
            flash("Enter a course title with 200 characters or fewer.", "danger")
            return redirect(url_for("trainer.manage_courses"))
        if len(description) > 5000:
            flash("Course description must be 5,000 characters or fewer.", "danger")
            return redirect(url_for("trainer.manage_courses"))
        if len(tags) > 500:
            flash("Course tags must be 500 characters or fewer.", "danger")
            return redirect(url_for("trainer.manage_courses"))

        course = Course(
            title=title,
            description=description or None,
            tags=tags or None,
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


@trainer.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
def edit_course(course_id):
    if current_user.role != "trainer":
        return "Access Denied", 403

    course = Course.query.filter_by(
        id=course_id,
        trainer_id=current_user.id
    ).first_or_404()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        tags = request.form.get("tags", "").strip()
        if not title or len(title) > 200:
            flash("Enter a course title with 200 characters or fewer.", "danger")
            return redirect(url_for("trainer.edit_course", course_id=course.id))
        if len(description) > 5000:
            flash("Course description must be 5,000 characters or fewer.", "danger")
            return redirect(url_for("trainer.edit_course", course_id=course.id))
        if len(tags) > 500:
            flash("Course tags must be 500 characters or fewer.", "danger")
            return redirect(url_for("trainer.edit_course", course_id=course.id))

        course.title = title
        course.description = description or None
        course.tags = tags or None
        db.session.commit()
        flash("Course details updated successfully.", "success")
        return redirect(url_for("trainer.edit_course", course_id=course.id))

    course_materials = CourseMaterial.query.filter_by(
        course_id=course.id
    ).order_by(CourseMaterial.uploaded_at.desc()).all()

    available_materials = CourseMaterial.query.filter(
        CourseMaterial.trainer_id == current_user.id,
        (CourseMaterial.course_id.is_(None)) | (CourseMaterial.course_id != course.id)
    ).order_by(CourseMaterial.uploaded_at.desc()).all()

    quizzes = CourseQuiz.query.filter_by(
        course_id=course.id
    ).order_by(CourseQuiz.created_at.desc()).all()

    return render_template(
        "trainer_course_edit.html",
        course=course,
        course_materials=course_materials,
        available_materials=available_materials,
        quizzes=quizzes,
    )


@trainer.route("/courses/<int:course_id>/add-material", methods=["POST"])
def add_course_material(course_id):
    if current_user.role != "trainer":
        return "Access Denied", 403

    course = Course.query.filter_by(
        id=course_id,
        trainer_id=current_user.id
    ).first_or_404()

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    tags = ", ".join(
        tag.strip() for tag in request.form.get("tags", "").split(",") if tag.strip()
    )
    material_type = request.form.get("material_type", "note")
    file = request.files.get("file")
    thumbnail = request.files.get("thumbnail")

    if not title or len(title) > 200:
        flash("Material title is required and must be 200 characters or fewer.", "danger")
        return redirect(url_for("trainer.edit_course", course_id=course.id))

    if description and len(description) > 5000:
        flash("Description must be 5,000 characters or fewer.", "danger")
        return redirect(url_for("trainer.edit_course", course_id=course.id))

    if material_type not in {"note", "video"}:
        flash("Invalid material type.", "danger")
        return redirect(url_for("trainer.edit_course", course_id=course.id))

    if not file or file.filename == "":
        flash("Please select a file to upload.", "danger")
        return redirect(url_for("trainer.edit_course", course_id=course.id))

    if not allowed_file(file.filename):
        flash("This file type is not allowed.", "danger")
        return redirect(url_for("trainer.edit_course", course_id=course.id))

    extension = file.filename.rsplit(".", 1)[-1].lower()
    if material_type == "video" and extension not in {"mp4", "webm"}:
        flash("Video lectures must be MP4 or WEBM files.", "danger")
        return redirect(url_for("trainer.edit_course", course_id=course.id))
    if material_type == "note" and extension in {"mp4", "webm"}:
        flash("Choose Video Lecture for MP4 or WEBM files.", "danger")
        return redirect(url_for("trainer.edit_course", course_id=course.id))

    thumbnail_filename = None
    if thumbnail and thumbnail.filename:
        thumbnail_extension = thumbnail.filename.rsplit(".", 1)[-1].lower()
        if thumbnail_extension not in THUMBNAIL_EXTENSIONS or not thumbnail.mimetype.startswith("image/"):
            flash("Thumbnail must be a JPG, PNG, GIF, or WEBP image.", "danger")
            return redirect(url_for("trainer.edit_course", course_id=course.id))

        thumbnail_filename = f"{uuid.uuid4().hex}.{thumbnail_extension}"
        thumbnail_folder = current_app.config["THUMBNAIL_UPLOAD_FOLDER"]
        os.makedirs(thumbnail_folder, exist_ok=True)
        thumbnail.save(os.path.join(thumbnail_folder, thumbnail_filename))

    random_filename = f"{uuid.uuid4().hex}.{extension}"
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)
    file.save(os.path.join(upload_folder, random_filename))

    material = CourseMaterial(
        title=title,
        description=description or None,
        filename=random_filename,
        original_filename=file.filename,
        file_type=extension,
        material_type=material_type,
        tags=tags or None,
        trainer_id=current_user.id,
        course_id=course.id,
        thumbnail_filename=thumbnail_filename,
    )
    db.session.add(material)
    db.session.commit()

    label = "Video lecture" if material_type == "video" else "Course note"
    flash(f"{label} '{title}' added to course library.", "success")
    return redirect(url_for("trainer.edit_course", course_id=course.id))


@trainer.route("/courses/<int:course_id>/attach-material", methods=["POST"])
def attach_material_to_course(course_id):
    if current_user.role != "trainer":
        return "Access Denied", 403

    course = Course.query.filter_by(
        id=course_id,
        trainer_id=current_user.id
    ).first_or_404()

    material_id = request.form.get("material_id")
    if not material_id:
        flash("Select a material to add to this course.", "warning")
        return redirect(url_for("trainer.edit_course", course_id=course.id))

    material = CourseMaterial.query.filter_by(
        id=material_id,
        trainer_id=current_user.id
    ).first_or_404()

    material.course_id = course.id
    db.session.commit()
    label = "Video lecture" if material.material_type == "video" else "Course note"
    flash(f"{label} '{material.title}' added to {course.title}.", "success")
    return redirect(url_for("trainer.edit_course", course_id=course.id))


@trainer.route("/courses/<int:course_id>/materials/<int:material_id>/remove", methods=["POST"])
def remove_material_from_course(course_id, material_id):
    if current_user.role != "trainer":
        return "Access Denied", 403

    course = Course.query.filter_by(
        id=course_id,
        trainer_id=current_user.id
    ).first_or_404()

    material = CourseMaterial.query.filter_by(
        id=material_id,
        course_id=course.id,
        trainer_id=current_user.id
    ).first_or_404()

    material.course_id = None
    db.session.commit()
    flash(f"'{material.title}' removed from {course.title}. It remains in your general library.", "success")
    return redirect(url_for("trainer.edit_course", course_id=course.id))


@trainer.route("/courses/<int:course_id>/delete", methods=["POST"])
def delete_course(course_id):
    if current_user.role != "trainer":
        return "Access Denied", 403

    course = Course.query.filter_by(
        id=course_id,
        trainer_id=current_user.id
    ).first_or_404()

    course_title = course.title

    CourseMaterial.query.filter_by(course_id=course.id).update({"course_id": None})

    enrollment_ids = [
        enrollment_id for (enrollment_id,) in db.session.query(CourseEnrollment.id).filter_by(course_id=course.id).all()
    ]
    if enrollment_ids:
        CourseProgress.query.filter(CourseProgress.enrollment_id.in_(enrollment_ids)).delete(synchronize_session=False)
        CourseEnrollment.query.filter(CourseEnrollment.id.in_(enrollment_ids)).delete(synchronize_session=False)

    quiz_ids = [quiz_id for (quiz_id,) in db.session.query(CourseQuiz.id).filter_by(course_id=course.id).all()]
    if quiz_ids:
        QuizAttempt.query.filter(QuizAttempt.quiz_id.in_(quiz_ids)).delete(synchronize_session=False)
        CourseQuizQuestion.query.filter(CourseQuizQuestion.quiz_id.in_(quiz_ids)).delete(synchronize_session=False)
        CourseQuiz.query.filter(CourseQuiz.id.in_(quiz_ids)).delete(synchronize_session=False)

    posts = CoursePost.query.filter_by(course_id=course.id).all()
    for post in posts:
        post_path = os.path.join(current_app.config["UPLOAD_FOLDER"], post.image_filename)
        if os.path.isfile(post_path):
            os.remove(post_path)
        db.session.delete(post)

    db.session.delete(course)
    db.session.commit()
    flash(f"Course '{course_title}' deleted successfully.", "success")
    return redirect(url_for("trainer.manage_courses"))


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

    courses = Course.query.filter_by(
        trainer_id=current_user.id
    ).order_by(Course.title.asc()).all()
    selected_course_id = request.args.get("course_id", type=int)

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
        course_id = request.form.get("course_id", type=int)
        valid_course_id = None
        if course_id:
            matched_course = Course.query.filter_by(
                id=course_id,
                trainer_id=current_user.id
            ).first()
            if matched_course:
                valid_course_id = matched_course.id

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
            course_id=valid_course_id,
            thumbnail_filename=thumbnail_filename
        )

        db.session.add(material)
        db.session.commit()

        label = "Video lecture" if material_type == "video" else "Course note"
        if valid_course_id:
            flash(
                f"{label} uploaded and added to course library.",
                "success"
            )
            return redirect(
                url_for("trainer.edit_course", course_id=valid_course_id)
            )

        flash(
            "Course material uploaded successfully.",
            "success"
        )

        return redirect(
            url_for("trainer.library")
        )

    return render_template(
        "upload_material.html",
        courses=courses,
        selected_course_id=selected_course_id,
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
    return redirect(request.referrer or url_for("trainer.library"))


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


@trainer.route("/courses/<int:course_id>/quiz/create", methods=["POST"])
def create_quiz(course_id):
    if current_user.role != "trainer":
        return "Access Denied", 403

    course = Course.query.filter_by(
        id=course_id,
        trainer_id=current_user.id
    ).first_or_404()

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()

    if not title:
        flash("Quiz title is required.", "danger")
        return redirect(url_for("trainer.edit_course", course_id=course.id))

    quiz = CourseQuiz(
        course_id=course.id,
        trainer_id=current_user.id,
        title=title[:200],
        description=description or None
    )
    db.session.add(quiz)
    db.session.commit()
    flash(f"Quiz '{quiz.title}' created! Add your quiz questions below.", "success")
    return redirect(url_for("trainer.manage_quiz", quiz_id=quiz.id))


@trainer.route("/quiz/<int:quiz_id>/manage", methods=["GET", "POST"])
def manage_quiz(quiz_id):
    if current_user.role != "trainer":
        return "Access Denied", 403

    quiz = CourseQuiz.query.filter_by(
        id=quiz_id,
        trainer_id=current_user.id
    ).first_or_404()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        if not title:
            flash("Quiz title is required.", "danger")
        else:
            quiz.title = title[:200]
            quiz.description = description or None
            db.session.commit()
            flash("Quiz details updated successfully.", "success")
        return redirect(url_for("trainer.manage_quiz", quiz_id=quiz.id))

    questions = CourseQuizQuestion.query.filter_by(quiz_id=quiz.id).order_by(CourseQuizQuestion.id.asc()).all()
    attempts = QuizAttempt.query.filter_by(quiz_id=quiz.id).order_by(QuizAttempt.submitted_at.desc()).all()

    return render_template(
        "trainer_quiz_manage.html",
        quiz=quiz,
        course=quiz.course,
        questions=questions,
        attempts=attempts
    )


@trainer.route("/quiz/<int:quiz_id>/question/add", methods=["POST"])
def add_quiz_question(quiz_id):
    if current_user.role != "trainer":
        return "Access Denied", 403

    quiz = CourseQuiz.query.filter_by(
        id=quiz_id,
        trainer_id=current_user.id
    ).first_or_404()

    question_text = request.form.get("question", "").strip()
    option_a = request.form.get("option_a", "").strip()
    option_b = request.form.get("option_b", "").strip()
    option_c = request.form.get("option_c", "").strip()
    option_d = request.form.get("option_d", "").strip()
    correct_option = request.form.get("correct_option", "").strip().upper()

    if not question_text or not option_a or not option_b or not option_c or not option_d or correct_option not in ["A", "B", "C", "D"]:
        flash("All question fields and a valid correct option (A, B, C, or D) are required.", "danger")
        return redirect(url_for("trainer.manage_quiz", quiz_id=quiz.id))

    question = CourseQuizQuestion(
        quiz_id=quiz.id,
        question=question_text,
        option_a=option_a[:255],
        option_b=option_b[:255],
        option_c=option_c[:255],
        option_d=option_d[:255],
        correct_option=correct_option
    )
    db.session.add(question)
    db.session.commit()
    flash("Question added to quiz successfully.", "success")
    return redirect(url_for("trainer.manage_quiz", quiz_id=quiz.id))


@trainer.route("/quiz/question/<int:question_id>/delete", methods=["POST"])
def delete_quiz_question(question_id):
    if current_user.role != "trainer":
        return "Access Denied", 403

    question = CourseQuizQuestion.query.get_or_404(question_id)
    quiz = CourseQuiz.query.filter_by(id=question.quiz_id, trainer_id=current_user.id).first_or_404()

    quiz_id = quiz.id
    db.session.delete(question)
    db.session.commit()
    flash("Question removed from quiz.", "success")
    return redirect(url_for("trainer.manage_quiz", quiz_id=quiz_id))


@trainer.route("/quiz/<int:quiz_id>/delete", methods=["POST"])
def delete_quiz(quiz_id):
    if current_user.role != "trainer":
        return "Access Denied", 403

    quiz = CourseQuiz.query.filter_by(
        id=quiz_id,
        trainer_id=current_user.id
    ).first_or_404()

    course_id = quiz.course_id
    QuizAttempt.query.filter_by(quiz_id=quiz.id).delete(synchronize_session=False)
    CourseQuizQuestion.query.filter_by(quiz_id=quiz.id).delete(synchronize_session=False)
    db.session.delete(quiz)
    db.session.commit()
    flash("Quiz deleted successfully.", "success")
    return redirect(url_for("trainer.edit_course", course_id=course_id))
