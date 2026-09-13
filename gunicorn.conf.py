import os

env_port = os.environ.get("PORT")
ports = ["10000", "5000"]
if env_port:
    ports.insert(0, str(env_port))

bind = [f"0.0.0.0:{p}" for p in dict.fromkeys(ports)]
workers = 2
threads = 4
timeout = 120
keepalive = 65
