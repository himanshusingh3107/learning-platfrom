import os

port = os.environ.get("PORT", "10000")
bind = f"0.0.0.0:{port}"
workers = 1
threads = 1
timeout = 120

def post_fork(server, worker):
    from app import db
    try:
        db.engine.dispose()
    except Exception:
        pass
