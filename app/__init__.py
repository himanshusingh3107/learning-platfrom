from flask import Flask
from flask import session
from flask_sqlalchemy import SQLAlchemy
from config import Config
from sqlalchemy import inspect, text


db = SQLAlchemy()


class CurrentUser:
    @property
    def user(self):
        user_id = session.get("user_id")
        if not user_id:
            return None
        from app.models import User
        return db.session.get(User, user_id)

    @property
    def is_authenticated(self):
        return self.user is not None

    def __getattr__(self, name):
        user = self.user
        if user is None:
            raise AttributeError(name)
        return getattr(user, name)


current_user = CurrentUser()


def create_app():

    app = Flask(__name__, static_folder="../static")
    app.config.from_object(Config)

    # Initialize database
    db.init_app(app)

    @app.context_processor
    def expose_current_user():
        return {"current_user": current_user}

    # Import routes
    from app.auth import auth
    from app.routes import bp as main
    from app.trainer import trainer

    app.register_blueprint(auth)
    app.register_blueprint(main)
    app.register_blueprint(trainer)

    # Create database
    with app.app_context():
        db.create_all()
        _upgrade_existing_database()

    return app


def _upgrade_existing_database():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()

    if "user" in tables:
        columns = {column["name"] for column in inspector.get_columns("user")}
        if "profile_photo" not in columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE user "
                        "ADD COLUMN profile_photo VARCHAR(255)"
                    )
                )

        if "is_super_admin" not in columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE user ADD COLUMN is_super_admin BOOLEAN NOT NULL DEFAULT 0")
                )

        if "certificate_filename" not in columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE user "
                        "ADD COLUMN certificate_filename VARCHAR(255)"
                    )
                )

        if "certificate_original_filename" not in columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE user "
                        "ADD COLUMN certificate_original_filename VARCHAR(255)"
                    )
                )

        if "user_code" not in columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE user "
                        "ADD COLUMN user_code VARCHAR(20)"
                    )
                )

        if "location" not in columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE user ADD COLUMN location VARCHAR(120)"))

        if "interests" not in columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE user ADD COLUMN interests VARCHAR(500)"))

        for column, definition in {
            "birthday": "VARCHAR(20)",
            "qualification": "VARCHAR(200)",
            "work_experience": "VARCHAR(500)",
            "skills": "VARCHAR(500)",
            "security_question": "VARCHAR(255)",
            "security_answer": "VARCHAR(255)",
        }.items():
            if column not in columns:
                with db.engine.begin() as connection:
                    connection.execute(text(f"ALTER TABLE user ADD COLUMN {column} {definition}"))

        from app.models import User
        import uuid

        users_without_codes = User.query.filter_by(user_code=None).all()
        for user in users_without_codes:
            prefix = {
                "trainer": "TRN",
                "trainee": "TRA",
                "admin": "ADM"
            }.get(user.role, "USR")
            user.user_code = f"{prefix}-{uuid.uuid4().hex[:10].upper()}"

        if users_without_codes:
            db.session.commit()

    if "course_material" in tables:
        columns = {column["name"] for column in inspector.get_columns("course_material")}
        if "course_id" not in columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE course_material ADD COLUMN course_id INTEGER"))

        if "thumbnail_filename" not in columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE course_material ADD COLUMN thumbnail_filename VARCHAR(255)"))

        if "material_type" not in columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE course_material "
                        "ADD COLUMN material_type VARCHAR(20) NOT NULL DEFAULT 'note'"
                    )
                )

        if "tags" not in columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE course_material ADD COLUMN tags VARCHAR(500)"))

        if "location" not in columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE course_material ADD COLUMN location VARCHAR(120)"))

    if "course_post" in tables:
        columns = {column["name"] for column in inspector.get_columns("course_post")}
        if "tags" not in columns:
            with db.engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE course_post "
                        "ADD COLUMN tags VARCHAR(500)"
                    )
                )

    if "class_schedule" not in tables:
        with db.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE class_schedule ("
                "id INTEGER NOT NULL, trainer_id INTEGER NOT NULL, "
                "title VARCHAR(200) NOT NULL, description TEXT, "
                "scheduled_for DATETIME NOT NULL, created_at DATETIME, "
                "updated_at DATETIME, PRIMARY KEY (id), "
                "FOREIGN KEY(trainer_id) REFERENCES user (id)"
                ")"
            ))

    if "notification" not in tables:
        with db.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE notification ("
                "id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
                "title VARCHAR(200) NOT NULL, message TEXT NOT NULL, "
                "is_read BOOLEAN NOT NULL DEFAULT 0, created_at DATETIME, "
                "PRIMARY KEY (id), FOREIGN KEY(user_id) REFERENCES user (id)"
                ")"
            ))

    if "course" not in tables:
        with db.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE course ("
                "id INTEGER NOT NULL, "
                "title VARCHAR(200) NOT NULL, "
                "description TEXT, "
                "trainer_id INTEGER NOT NULL, "
                "created_at DATETIME, "
                "PRIMARY KEY (id), "
                "FOREIGN KEY(trainer_id) REFERENCES user (id)"
                ")"
            ))

    if "course_enrollment" not in tables:
        with db.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE course_enrollment ("
                "id INTEGER NOT NULL, "
                "course_id INTEGER NOT NULL, "
                "trainee_id INTEGER NOT NULL, "
                "created_at DATETIME, "
                "PRIMARY KEY (id), "
                "UNIQUE (course_id, trainee_id), "
                "FOREIGN KEY(course_id) REFERENCES course (id), "
                "FOREIGN KEY(trainee_id) REFERENCES user (id)"
                ")"
            ))

    if "course_progress" not in tables:
        with db.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE course_progress ("
                "id INTEGER NOT NULL, "
                "enrollment_id INTEGER NOT NULL, "
                "material_id INTEGER NOT NULL, "
                "completed BOOLEAN NOT NULL DEFAULT 0, "
                "completed_at DATETIME, "
                "PRIMARY KEY (id), "
                "UNIQUE (enrollment_id, material_id), "
                "FOREIGN KEY(enrollment_id) REFERENCES course_enrollment (id), "
                "FOREIGN KEY(material_id) REFERENCES course_material (id)"
                ")"
            ))

    if "course_quiz" not in tables:
        with db.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE course_quiz ("
                "id INTEGER NOT NULL, "
                "course_id INTEGER NOT NULL, "
                "trainer_id INTEGER NOT NULL, "
                "title VARCHAR(200) NOT NULL, "
                "description TEXT, "
                "created_at DATETIME, "
                "PRIMARY KEY (id), "
                "FOREIGN KEY(course_id) REFERENCES course (id), "
                "FOREIGN KEY(trainer_id) REFERENCES user (id)"
                ")"
            ))

    if "course_quiz_question" not in tables:
        with db.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE course_quiz_question ("
                "id INTEGER NOT NULL, "
                "quiz_id INTEGER NOT NULL, "
                "question TEXT NOT NULL, "
                "option_a VARCHAR(255) NOT NULL, "
                "option_b VARCHAR(255) NOT NULL, "
                "option_c VARCHAR(255) NOT NULL, "
                "option_d VARCHAR(255) NOT NULL, "
                "correct_option VARCHAR(10) NOT NULL, "
                "PRIMARY KEY (id), "
                "FOREIGN KEY(quiz_id) REFERENCES course_quiz (id)"
                ")"
            ))

    if "quiz_attempt" not in tables:
        with db.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE quiz_attempt ("
                "id INTEGER NOT NULL, "
                "quiz_id INTEGER NOT NULL, "
                "trainee_id INTEGER NOT NULL, "
                "score INTEGER NOT NULL DEFAULT 0, "
                "total_questions INTEGER NOT NULL DEFAULT 0, "
                "submitted_answers TEXT, "
                "submitted_at DATETIME, "
                "PRIMARY KEY (id), "
                "FOREIGN KEY(quiz_id) REFERENCES course_quiz (id), "
                "FOREIGN KEY(trainee_id) REFERENCES user (id)"
                ")"
            ))

    if "user_activity" in tables:
        columns = {column["name"] for column in inspector.get_columns("user_activity")}
        with db.engine.begin() as connection:
            if "query" in columns and "search_term" not in columns:
                connection.execute(
                    text("ALTER TABLE user_activity RENAME COLUMN query TO search_term")
                )
            elif "search_term" not in columns:
                connection.execute(
                    text("ALTER TABLE user_activity ADD COLUMN search_term VARCHAR(200)")
                )
