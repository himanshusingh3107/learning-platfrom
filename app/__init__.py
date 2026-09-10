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
