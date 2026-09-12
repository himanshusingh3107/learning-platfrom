import os

# Set the test database before importing the application configuration.
# Config is evaluated during the import, so setting this afterwards can make
# tests run against (and reset) the normal development database.
os.environ["DATABASE_URL"] = "sqlite:///test_course_features.db"

from app import create_app, db
from app.models import Course, CourseEnrollment, CourseMaterial, CourseProgress, User


def test_course_progress_tracks_material_completion():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        trainer = User(name="Alice Trainer", email="trainer@example.com", password_hash="pw", role="trainer")
        trainee = User(name="Bob Learner", email="learner@example.com", password_hash="pw", role="trainee")
        db.session.add_all([trainer, trainee])
        db.session.commit()

        course = Course(title="Python Intro", description="Learn Python basics.", trainer_id=trainer.id)
        db.session.add(course)
        db.session.commit()

        material_1 = CourseMaterial(
            title="Setup",
            filename="setup.txt",
            original_filename="setup.txt",
            file_type="txt",
            material_type="note",
            trainer_id=trainer.id,
            course_id=course.id,
        )
        material_2 = CourseMaterial(
            title="Loops",
            filename="loops.txt",
            original_filename="loops.txt",
            file_type="txt",
            material_type="note",
            trainer_id=trainer.id,
            course_id=course.id,
        )
        db.session.add_all([material_1, material_2])
        db.session.commit()

        enrollment = CourseEnrollment(course_id=course.id, trainee_id=trainee.id)
        db.session.add(enrollment)
        db.session.commit()

        db.session.add_all([
            CourseProgress(enrollment_id=enrollment.id, material_id=material_1.id, completed=True),
            CourseProgress(enrollment_id=enrollment.id, material_id=material_2.id, completed=False),
        ])
        db.session.commit()

        assert enrollment.progress_percentage() == 50
        assert course.get_progress_for_trainee(trainee.id) == 50

        admin = User(name="Admin", email="admin@example.com", password_hash="admin-password", role="admin")
        db.session.add(admin)
        db.session.commit()
        trainer_id = trainer.id
        course_id = course.id
        admin_id = admin.id
        db.session.remove()

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = admin_id
    response = client.post(f"/admin/delete-user/{trainer_id}", follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(User, trainer_id) is None
        assert db.session.get(Course, course_id) is None
        assert CourseEnrollment.query.count() == 0
        assert CourseProgress.query.count() == 0


def test_login_accepts_registered_user_credentials():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(name="Login User", email="login@example.com", role="trainee")
        user.set_password("correct-password")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    response = client.post(
        "/login",
        data={"email": "login@example.com", "password": "correct-password"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    with client.session_transaction() as session:
        assert session["user_id"] == user_id


def test_trainee_can_enroll_in_a_launched_course():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        trainer = User(name="Course Trainer", email="course-trainer@example.com", password_hash="pw", role="trainer")
        trainee = User(name="Course Trainee", email="course-trainee@example.com", password_hash="pw", role="trainee")
        db.session.add_all([trainer, trainee])
        db.session.commit()
        course = Course(title="Course Launch", trainer_id=trainer.id)
        db.session.add(course)
        db.session.commit()
        course_id = course.id
        trainee_id = trainee.id

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = trainee_id
    response = client.post(f"/courses/{course_id}/enroll", follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        assert CourseEnrollment.query.filter_by(course_id=course_id, trainee_id=trainee_id).count() == 1


def test_admin_signup_requires_super_admin_approval():
    app = create_app()
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()
        super_admin = User(
            name="Super Admin",
            email="super@example.com",
            password_hash="super-password",
            role="admin",
            is_active=True,
            is_super_admin=True,
        )
        db.session.add(super_admin)
        db.session.commit()
        super_admin_id = super_admin.id

    signup_response = client.post(
        "/signup",
        data={
            "name": "Pending Admin",
            "email": "pending-admin@example.com",
            "password": "pending-password",
            "role": "admin",
        },
        follow_redirects=False,
    )
    assert signup_response.headers["Location"].endswith("/account-setup")

    with app.app_context():
        pending_admin = User.query.filter_by(email="pending-admin@example.com").one()
        assert pending_admin.is_active is False
        pending_admin_id = pending_admin.id

    with client.session_transaction() as session:
        session["user_id"] = super_admin_id
    approval_response = client.post(f"/admin/approve-admin/{pending_admin_id}", follow_redirects=False)
    assert approval_response.status_code == 302

    with app.app_context():
        assert db.session.get(User, pending_admin_id).is_active is True
