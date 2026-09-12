import os
import secrets
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:

    turso_url = os.getenv("TURSO_DATABASE_URL")
    turso_auth_token = os.getenv("TURSO_AUTH_TOKEN")

    if turso_url and turso_auth_token:
        turso_host = turso_url.replace("https://", "").replace("http://", "").rstrip("/")
        SQLALCHEMY_DATABASE_URI = f"sqlite+libsql://{turso_host}?secure=true"
        SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {"auth_token": turso_auth_token}
        }
    else:
        SQLALCHEMY_DATABASE_URI = os.getenv(
            "DATABASE_URL",
            "sqlite:///learning_platform.db"
        )

    SECRET_KEY = os.getenv(
        "SECRET_KEY",
        secrets.token_hex(32)
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "vs6231588@gmail.com")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    ALLOWED_EXTENSIONS = {
        "jpg",
        "jpeg",
        "png",
        "gif",
        "webp"
    }

    # Maximum upload size = 50 MB
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024

    UPLOAD_FOLDER = os.path.join(
        os.path.dirname(__file__),
        "app",
        "uploads",
        "materials"
    )

    THUMBNAIL_UPLOAD_FOLDER = os.path.join(
        os.path.dirname(__file__),
        "app",
        "uploads",
        "thumbnails"
    )

    PROFILE_UPLOAD_FOLDER = os.path.join(
        os.path.dirname(__file__),
        "app",
        "uploads",
        "profiles"
    )

    CERTIFICATE_UPLOAD_FOLDER = os.path.join(
        os.path.dirname(__file__),
        "app",
        "uploads",
        "certificates"
    )