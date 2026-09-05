"""
Flask extension singletons.

Import these into the app factory and into models/services — never
instantiate them elsewhere to avoid circular imports.
"""

from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler

db = SQLAlchemy()
scheduler = BackgroundScheduler(daemon=True)
