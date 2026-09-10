from app import create_app, db
from app.models import User


app = create_app()

with app.app_context():

    existing = User.query.filter_by(
        email="abcd@gmail.com"
    ).first()

    if existing:
        existing.role = "admin"
        existing.set_password("123456789")
        db.session.commit()
        print("Admin password reset successfully.")

    else:

        admin = User(
            name="System Administrator",
            email="abcd@gmail.com",
            role="admin",
        )

        admin.set_password("123456789")

        db.session.add(admin)
        db.session.commit()

        print("Admin created successfully.")