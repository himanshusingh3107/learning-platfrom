import io
import os

# Set the test database before importing the application configuration.
# Config is evaluated during the import, so setting this afterwards can make
# tests run against (and reset) the normal development database.
os.environ["DATABASE_URL"] = "sqlite:///test_course_features.db"

from app import create_app, db
from app.models import Course, CourseEnrollment, CourseMaterial, CourseProgress, User, CourseQuiz, CourseQuizQuestion, QuizAttempt


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


def test_admin_cannot_be_created_via_signup():
    app = create_app()
    client = app.test_client()
    with app.app_context():
        db.drop_all()
        db.create_all()

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
    assert signup_response.headers["Location"].endswith("/signup")

    with app.app_context():
        assert User.query.filter_by(email="pending-admin@example.com").first() is None


def test_super_admin_can_approve_admin():
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
        pending_admin = User(
            name="Pending Admin",
            email="pending-admin@example.com",
            password_hash="pending-password",
            role="admin",
            is_active=False,
            is_super_admin=False,
        )
        db.session.add_all([super_admin, pending_admin])
        db.session.commit()
        super_admin_id = super_admin.id
        pending_admin_id = pending_admin.id

    with client.session_transaction() as session:
        session["user_id"] = super_admin_id
    approval_response = client.post(f"/admin/approve-admin/{pending_admin_id}", follow_redirects=False)
    assert approval_response.status_code == 302

    with app.app_context():
        assert db.session.get(User, pending_admin_id).is_active is True


def test_nav_search_matches_trainers_courses_and_video_metadata():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        trainer = User(
            name="Python Mentor", email="mentor@example.com", password_hash="pw",
            role="trainer", is_active=True,
        )
        trainee = User(
            name="Searcher", email="searcher@example.com", password_hash="pw",
            role="trainee", is_active=True,
        )
        db.session.add_all([trainer, trainee])
        db.session.commit()
        course = Course(
            title="Python Foundations", description="Start programming",
            tags="python, beginner", trainer_id=trainer.id,
        )
        video = CourseMaterial(
            title="Loop walkthrough", description="A clear explanation",
            tags="python, loops", filename="loops.mp4", original_filename="loops.mp4",
            file_type="mp4", material_type="video", trainer_id=trainer.id,
        )
        db.session.add_all([course, video])
        db.session.commit()
        trainee_id = trainee.id

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = trainee_id
    response = client.get("/?q=python")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Python Mentor" in page
    assert "Python Foundations" in page
    assert "Loop walkthrough" in page


def test_trainer_dashboard_has_my_courses_option_and_list():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        trainer = User(
            name="Alice Trainer",
            email="alice@example.com",
            password_hash="pw",
            role="trainer",
            is_active=True,
        )
        db.session.add(trainer)
        db.session.commit()
        course = Course(
            title="Django Web Development",
            description="Build apps with Django.",
            tags="django, python",
            trainer_id=trainer.id,
        )
        db.session.add(course)
        db.session.commit()
        trainer_id = trainer.id

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = trainer_id

    response = client.get("/dashboard")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "My Courses" in page
    assert "Django Web Development" in page
    assert "Edit &amp; Library" in page or "Edit & Library" in page


def test_trainer_can_edit_course_and_manage_library():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        trainer = User(
            name="Bob Trainer",
            email="bob@example.com",
            password_hash="pw",
            role="trainer",
            is_active=True,
        )
        db.session.add(trainer)
        db.session.commit()
        course = Course(
            title="Flask Basics",
            description="Intro to Flask.",
            tags="flask",
            trainer_id=trainer.id,
        )
        db.session.add(course)
        db.session.commit()
        course_id = course.id
        trainer_id = trainer.id

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = trainer_id

    # 1. Edit course details
    edit_page_response = client.get(f"/trainer/courses/{course_id}/edit")
    assert edit_page_response.status_code == 200
    assert "Flask Basics" in edit_page_response.get_data(as_text=True)

    update_response = client.post(
        f"/trainer/courses/{course_id}/edit",
        data={
            "title": "Flask Advanced",
            "description": "Deep dive into Flask.",
            "tags": "flask, advanced",
        },
        follow_redirects=True,
    )
    assert update_response.status_code == 200
    with app.app_context():
        updated_course = db.session.get(Course, course_id)
        assert updated_course.title == "Flask Advanced"
        assert updated_course.description == "Deep dive into Flask."

    # 2. Add note to course library
    add_note_response = client.post(
        f"/trainer/courses/{course_id}/add-material",
        data={
            "title": "Flask Routing Note",
            "material_type": "note",
            "description": "How URL routing works.",
            "tags": "routing",
            "file": (io.BytesIO(b"Notes about routing"), "routing.txt"),
        },
        follow_redirects=True,
    )
    assert add_note_response.status_code == 200
    with app.app_context():
        note = CourseMaterial.query.filter_by(title="Flask Routing Note").first()
        assert note is not None
        assert note.course_id == course_id
        assert note.material_type == "note"
        note_id = note.id

    # 3. Add video lecture to course library
    add_lecture_response = client.post(
        f"/trainer/courses/{course_id}/add-material",
        data={
            "title": "Routing Lecture Video",
            "material_type": "video",
            "description": "Video walkthrough.",
            "file": (io.BytesIO(b"dummy mp4 video content"), "routing.mp4"),
        },
        follow_redirects=True,
    )
    assert add_lecture_response.status_code == 200
    with app.app_context():
        lecture = CourseMaterial.query.filter_by(title="Routing Lecture Video").first()
        assert lecture is not None
        assert lecture.course_id == course_id
        assert lecture.material_type == "video"

    # 4. Attach an unassigned material from trainer library to course
    with app.app_context():
        unassigned_material = CourseMaterial(
            title="General Python Tips",
            filename="tips.txt",
            original_filename="tips.txt",
            file_type="txt",
            material_type="note",
            trainer_id=trainer_id,
            course_id=None,
        )
        db.session.add(unassigned_material)
        db.session.commit()
        unassigned_id = unassigned_material.id

    attach_response = client.post(
        f"/trainer/courses/{course_id}/attach-material",
        data={"material_id": unassigned_id},
        follow_redirects=True,
    )
    assert attach_response.status_code == 200
    with app.app_context():
        assert db.session.get(CourseMaterial, unassigned_id).course_id == course_id

    # 5. Remove note from course library (unlinks without deleting file)
    remove_response = client.post(
        f"/trainer/courses/{course_id}/materials/{note_id}/remove",
        follow_redirects=True,
    )
    assert remove_response.status_code == 200
    with app.app_context():
        removed_note = db.session.get(CourseMaterial, note_id)
        assert removed_note is not None
        assert removed_note.course_id is None

    # 6. Delete course
    delete_response = client.post(
        f"/trainer/courses/{course_id}/delete",
        follow_redirects=True,
    )
    assert delete_response.status_code == 200
    with app.app_context():
        assert db.session.get(Course, course_id) is None


def test_trainer_quiz_organization_and_trainee_attempt():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        trainer = User(name="Quiz Trainer", email="quiz-trainer@example.com", password_hash="pw", role="trainer")
        trainee = User(name="Quiz Trainee", email="quiz-trainee@example.com", password_hash="pw", role="trainee")
        db.session.add_all([trainer, trainee])
        db.session.commit()

        course = Course(title="Python Testing Course", description="Test quizzes.", trainer_id=trainer.id)
        db.session.add(course)
        db.session.commit()

        enrollment = CourseEnrollment(course_id=course.id, trainee_id=trainee.id)
        db.session.add(enrollment)
        db.session.commit()

        course_id = course.id
        trainer_id = trainer.id
        trainee_id = trainee.id

    client = app.test_client()

    # 1. Trainer creates a quiz
    with client.session_transaction() as session:
        session["user_id"] = trainer_id

    create_quiz_res = client.post(
        f"/trainer/courses/{course_id}/quiz/create",
        data={"title": "Syntax & Semantics Quiz", "description": "Short quiz on python basics"},
        follow_redirects=True,
    )
    assert create_quiz_res.status_code == 200

    with app.app_context():
        quiz = CourseQuiz.query.filter_by(course_id=course_id).first()
        assert quiz is not None
        assert quiz.title == "Syntax & Semantics Quiz"
        quiz_id = quiz.id

    # 2. Trainer adds 2 multiple choice questions
    q1_res = client.post(
        f"/trainer/quiz/{quiz_id}/question/add",
        data={
            "question": "Which keyword is used for conditional execution?",
            "option_a": "if",
            "option_b": "for",
            "option_c": "while",
            "option_d": "def",
            "correct_option": "A",
        },
        follow_redirects=True,
    )
    assert q1_res.status_code == 200

    q2_res = client.post(
        f"/trainer/quiz/{quiz_id}/question/add",
        data={
            "question": "Which built-in function returns the length of an object?",
            "option_a": "count()",
            "option_b": "size()",
            "option_c": "len()",
            "option_d": "length()",
            "correct_option": "C",
        },
        follow_redirects=True,
    )
    assert q2_res.status_code == 200

    with app.app_context():
        questions = CourseQuizQuestion.query.filter_by(quiz_id=quiz_id).order_by(CourseQuizQuestion.id.asc()).all()
        assert len(questions) == 2
        q1_id = questions[0].id
        q2_id = questions[1].id

    # 3. Trainer views quiz management interface
    manage_res = client.get(f"/trainer/quiz/{quiz_id}/manage")
    assert manage_res.status_code == 200
    assert b"Syntax &amp; Semantics Quiz" in manage_res.data or b"Syntax & Semantics Quiz" in manage_res.data

    # 4. Trainee visits course detail and quizzes tab
    with client.session_transaction() as session:
        session["user_id"] = trainee_id

    detail_res = client.get(f"/course/{course_id}")
    assert detail_res.status_code == 200
    assert b"Syntax &amp; Semantics Quiz" in detail_res.data or b"Syntax & Semantics Quiz" in detail_res.data

    # 5. Trainee opens take_quiz page
    quiz_page_res = client.get(f"/course/{course_id}/quiz/{quiz_id}")
    assert quiz_page_res.status_code == 200
    assert b"Which keyword is used for conditional execution?" in quiz_page_res.data

    # 6. Trainee submits answers (Q1=A correct, Q2=A incorrect -> 1/2)
    submit_res = client.post(
        f"/course/{course_id}/quiz/{quiz_id}",
        data={
            f"question_{q1_id}": "A",
            f"question_{q2_id}": "A",
        },
        follow_redirects=True,
    )
    assert submit_res.status_code == 200
    with app.app_context():
        attempt = QuizAttempt.query.filter_by(quiz_id=quiz_id, trainee_id=trainee_id).first()
        assert attempt is not None
        assert attempt.score == 1
        assert attempt.total_questions == 2

    # 7. Trainee retakes quiz and gets 2/2 (100%)
    retake_res = client.post(
        f"/course/{course_id}/quiz/{quiz_id}",
        data={
            f"question_{q1_id}": "A",
            f"question_{q2_id}": "C",
        },
        follow_redirects=True,
    )
    assert retake_res.status_code == 200
    with app.app_context():
        latest = QuizAttempt.query.filter_by(quiz_id=quiz_id, trainee_id=trainee_id).order_by(QuizAttempt.id.desc()).first()
        assert latest.score == 2

    # 8. Trainer views quiz attempts table
    with client.session_transaction() as session:
        session["user_id"] = trainer_id

    manage_after_res = client.get(f"/trainer/quiz/{quiz_id}/manage")
    assert manage_after_res.status_code == 200
    assert b"Quiz Trainee" in manage_after_res.data
    assert b"2 / 2" in manage_after_res.data


if __name__ == "__main__":
    import inspect
    tests = [obj for name, obj in inspect.getmembers(inspect.getmodule(test_course_progress_tracks_material_completion))
             if inspect.isfunction(obj) and name.startswith("test_")]
    print(f"Running {len(tests)} test functions...")
    for t in tests:
        t()
        print(f"PASS: {t.__name__}")
    print("All tests passed successfully!")


