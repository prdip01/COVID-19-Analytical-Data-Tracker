"""
Gunicorn production server configuration for the COVID-19 Data Tracker.
"""

import multiprocessing
import os

# Port and interface to bind
bind = f"0.0.0.0:{os.getenv('PORT', '5001')}"

# Worker configuration
# In production, workers are calculated dynamically from CPU count (2 * cores + 1)
workers = int(os.getenv("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))

# We use the gthread worker class for efficient threaded request handling
# and native compatibility with Python 3.13.
worker_class = "gthread"
threads = 4

# Maximum time (seconds) a worker can spend responding to a request before being killed
timeout = 60

# Number of seconds to wait for subsequent requests on a Keep-Alive connection
keepalive = 2

# Logging configuration
loglevel = os.getenv("LOG_LEVEL", "info").lower()
accesslog = "-"   # Log access logs directly to stdout
errorlog = "-"    # Log error logs directly to stderr
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = "covid19_tracker_flask"
