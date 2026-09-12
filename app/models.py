import uuid
from app import db
from sqlalchemy import UniqueConstraint, event
from werkzeug.security import generate_password_hash, check_password_hash


class User(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    user_code = db.Column(
        db.String(20),
        unique=True,
        nullable=True
    )

    name = db.Column(db.String(100), nullable=False)

    email = db.Column(
        db.String(120),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    role = db.Column(
        db.String(20),
        nullable=False,
        default="trainee"
    )

    is_active = db.Column(
        db.Boolean,
        default=True
    )

    is_super_admin = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    profile_photo = db.Column(
        db.String(255),
        nullable=True
    )

    certificate_filename = db.Column(db.String(255), nullable=True)
    certificate_original_filename = db.Column(db.String(255), nullable=True)

    location = db.Column(db.String(120), nullable=True)
    interests = db.Column(db.String(500), nullable=True)
    birthday = db.Column(db.String(20), nullable=True)
    qualification = db.Column(db.String(200), nullable=True)
    work_experience = db.Column(db.String(500), nullable=True)
    skills = db.Column(db.String(500), nullable=True)
    security_question = db.Column(db.String(255), nullable=True)
    security_answer = db.Column(db.String(255), nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash or not password:
            return False
        try:
            if check_password_hash(self.password_hash, password):
                return True
        except Exception:
            pass
        if self.password_hash == password:
            try:
                self.password_hash = generate_password_hash(password)
                db.session.commit()
            except Exception:
                pass
            return True
        return False


@event.listens_for(User, "before_insert")
def assign_user_code(mapper, connection, user):
    if not user.user_code:
        prefix = {
            "trainer": "TRN",
            "trainee": "TRA",
            "admin": "ADM"
        }.get(user.role, "USR")
        user.user_code = f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


class TrainerFollow(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    trainee_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    trainer_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    __table_args__ = (
        UniqueConstraint("trainee_id", "trainer_id", name="unique_trainer_follow"),
    )


class ClassSchedule(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    trainer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    scheduled_for = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    trainer = db.relationship("User", backref="scheduled_classes")


class Notification(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User", backref="notifications")


class CourseMaterial(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    tags = db.Column(db.String(500), nullable=True)
    location = db.Column(db.String(120), nullable=True)

    filename = db.Column(
        db.String(255),
        nullable=False
    )

    original_filename = db.Column(
        db.String(255),
        nullable=False
    )

    file_type = db.Column(
        db.String(20),
        nullable=False
    )

    material_type = db.Column(
        db.String(20),
        nullable=False,
        default="note"
    )

    thumbnail_filename = db.Column(db.String(255), nullable=True)

    uploaded_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    trainer_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id"),
        nullable=True
    )

    trainer = db.relationship(
        "User",
        backref="course_materials"
    )

    course = db.relationship(
        "Course",
        backref="materials"
    )


class Course(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    tags = db.Column(db.String(500), nullable=True)
    trainer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    trainer = db.relationship("User", backref="courses")

    def get_progress_for_trainee(self, trainee_id):
        enrollment = CourseEnrollment.query.filter_by(
            course_id=self.id,
            trainee_id=trainee_id
        ).first()
        if enrollment is None:
            return 0
        return enrollment.progress_percentage()


class CourseEnrollment(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    trainee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    course = db.relationship("Course", backref="enrollments")
    trainee = db.relationship("User", backref="course_enrollments")

    __table_args__ = (
        UniqueConstraint("course_id", "trainee_id", name="unique_course_enrollment"),
    )

    def progress_percentage(self):
        total_materials = CourseMaterial.query.filter_by(course_id=self.course_id).count()
        if total_materials == 0:
            return 0

        completed = CourseProgress.query.filter_by(
            enrollment_id=self.id,
            completed=True
        ).count()

        return round((completed / total_materials) * 100)


class CourseProgress(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey("course_enrollment.id"), nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey("course_material.id"), nullable=False)
    completed = db.Column(db.Boolean, default=False, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    enrollment = db.relationship("CourseEnrollment", backref="progress_entries")
    material = db.relationship("CourseMaterial", backref="progress_entries")

    __table_args__ = (
        UniqueConstraint("enrollment_id", "material_id", name="unique_course_progress"),
    )


class CourseQuiz(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    trainer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    course = db.relationship("Course", backref="quizzes")
    trainer = db.relationship("User", backref="course_quizzes")


class CourseQuizQuestion(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("course_quiz.id"), nullable=False)
    question = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(255), nullable=False)
    option_b = db.Column(db.String(255), nullable=False)
    option_c = db.Column(db.String(255), nullable=False)
    option_d = db.Column(db.String(255), nullable=False)
    correct_option = db.Column(db.String(10), nullable=False)

    quiz = db.relationship("CourseQuiz", backref="questions")


class QuizAttempt(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("course_quiz.id"), nullable=False)
    trainee_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    score = db.Column(db.Integer, nullable=False, default=0)
    total_questions = db.Column(db.Integer, nullable=False, default=0)
    submitted_answers = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(db.DateTime, server_default=db.func.now())

    quiz = db.relationship("CourseQuiz", backref="attempts")
    trainee = db.relationship("User", backref="quiz_attempts")


class UserActivity(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey("course_material.id"), nullable=True)
    activity_type = db.Column(db.String(20), nullable=False)
    search_term = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User", backref="activities")
    material = db.relationship("CourseMaterial", backref="activities")


class CoursePost(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    title = db.Column(
        db.String(200),
        nullable=False
    )

    description = db.Column(
        db.Text,
        nullable=True
    )

    tags = db.Column(
        db.String(500),
        nullable=True
    )

    image_filename = db.Column(
        db.String(255),
        nullable=False
    )

    course_id = db.Column(
        db.Integer,
        nullable=False
    )

    trainer_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    trainer = db.relationship(
        "User",
        backref="course_posts"
    )

    def __repr__(self):
        return f"<User {self.email}>"


class HelpDeskInquiry(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    trainee_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    admin_email = db.Column(
        db.String(120),
        nullable=False,
        default="vs6231588@gmail.com"
    )

    category = db.Column(
        db.String(50),
        nullable=False,
        default="General"
    )

    subject = db.Column(
        db.String(200),
        nullable=False
    )

    message = db.Column(
        db.Text,
        nullable=False
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="open"
    )

    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    trainee = db.relationship(
        "User",
        backref="help_desk_inquiries"
    )

    def __repr__(self):
        return f"<HelpDeskInquiry #{self.id} {self.subject}>"
