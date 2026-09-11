import uuid
from app import db
from sqlalchemy import UniqueConstraint, event


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
        self.password_hash = password

    def check_password(self, password):
        return self.password_hash == password


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

    uploaded_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    trainer_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    trainer = db.relationship(
        "User",
        backref="course_materials"
    )


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
