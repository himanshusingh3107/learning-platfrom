from app import create_app, db
from app.models import User, UserActivity, Notification


app = create_app()

with app.app_context():

    admin_email = "vs6231588@gmail.com"
    admin_password = "143Sakshi"

    # Clean up legacy default admin if exists
    legacy_admin = User.query.filter_by(email="abcd@gmail.com").first()
    if legacy_admin:
        UserActivity.query.filter_by(user_id=legacy_admin.id).delete()
        Notification.query.filter_by(user_id=legacy_admin.id).delete()
        db.session.delete(legacy_admin)
        db.session.commit()
        print("Removed legacy default admin abcd@gmail.com.")

    existing = User.query.filter_by(
        email=admin_email
    ).first()

    if existing:
        existing.role = "admin"
        existing.is_active = True
        existing.is_super_admin = True
        existing.set_password(admin_password)
        db.session.commit()
        print(f"Admin ({admin_email}) password updated successfully to {admin_password}.")

    else:
        admin = User(
            name="System Administrator",
            email=admin_email,
            role="admin",
            is_active=True,
            is_super_admin=True,
        )

        admin.set_password(admin_password)

        db.session.add(admin)
        db.session.commit()

        print(f"Admin ({admin_email}) created successfully with password {admin_password}.")
