"""
ScholarMind AI — Flask Application Factory.

Using the factory pattern allows different configurations per environment
and makes the app testable without global state.
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, request
from sqlalchemy import inspect
from .config import configs
from .extensions import db, scheduler


_SERVICES_STARTED = False


def create_app(env: str | None = None) -> Flask:
    """
    Create and configure the Flask application.

    Args:
        env: 'development' or 'production'. Falls back to FLASK_ENV env var.

    Returns:
        Configured Flask application instance.
    """
    env = env or os.environ.get("FLASK_ENV", "development")
    config_class = configs.get(env, configs["development"])
    config_class.ensure_dirs()

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config_class)

    _configure_logging(app)
    _init_extensions(app)
    _configure_cors(app)
    _register_blueprints(app)
    _register_context_processors(app)
    _register_error_handlers(app)

    with app.app_context():
        db.create_all()
        _ensure_application_opportunity_column(app)
        _ensure_multiuser_columns(app)
        _start_telegram_bot(app)
        app.logger.info("ScholarMind AI started (env=%s)", env)

    return app


def _ensure_multiuser_columns(app: Flask) -> None:
    """Add nullable ownership columns so existing databases can migrate safely."""
    migrations = {
        "user_profile": ("user_id", "INTEGER"),
        "chat_sessions": ("user_id", "INTEGER"),
        "applications": ("user_id", "INTEGER"),
    }
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    with db.engine.begin() as connection:
        for table, (column, sql_type) in migrations.items():
            if table not in tables:
                continue
            columns = {c["name"] for c in inspector.get_columns(table)}
            if column not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
                )


def _ensure_application_opportunity_column(app: Flask) -> None:
    """Add the generic opportunity link to databases created before Phase 3."""
    inspector = inspect(db.engine)
    if "applications" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("applications")}
    if "opportunity_id" not in columns:
        with db.engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE applications ADD COLUMN opportunity_id INTEGER"
            )


def _start_telegram_bot(app: Flask) -> None:
    """Start the optional Telegram Bot API worker after the database is ready."""
    try:
        from .models.api_key import ApiKeySetting
        from .services import telegram_bot_service

        token = ApiKeySetting.get("telegram_bot", "token") or app.config.get(
            "TELEGRAM_BOT_TOKEN"
        )
        enabled = ApiKeySetting.get("telegram_bot", "enabled") or app.config.get(
            "TELEGRAM_BOT_ENABLED", "false"
        )
        if token and str(enabled).lower() == "true":
            # The service is already idempotent for a running worker; do not
            # restart it merely because another app instance was constructed.
            if not telegram_bot_service.is_running():
                telegram_bot_service.start_bot(token, app)
                app.logger.info("Telegram Bot API worker started")
    except Exception as exc:
        app.logger.error("Telegram Bot API worker could not start: %s", exc)


def _configure_logging(app: Flask) -> None:
    """Set up rotating file loggers for each concern."""
    logs_dir = app.config["LOGS_DIR"]
    log_level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    )

    def _add_file_handler(logger_name: str, filename: str) -> logging.Logger:
        log = logging.getLogger(logger_name)
        # Flask's app factory can be called repeatedly (tests, desktop shell).
        # Avoid stacking duplicate file handlers on every app construction.
        if any(
            isinstance(handler, RotatingFileHandler)
            and getattr(handler, "baseFilename", None) == str(logs_dir / filename)
            for handler in log.handlers
        ):
            return log
        handler = RotatingFileHandler(
            logs_dir / filename, maxBytes=5 * 1024 * 1024, backupCount=3
        )
        handler.setFormatter(formatter)
        handler.setLevel(log_level)
        log.setLevel(log_level)
        log.addHandler(handler)
        return log

    for logger_name, filename in {
        "scholarmind.app": "app.log",
        "scholarmind.telegram": "telegram.log",
        "scholarmind.ai": "ai.log",
        "scholarmind.db": "database.log",
        "scholarmind.errors": "errors.log",
    }.items():
        _add_file_handler(logger_name, filename)

    if app.config.get("DEBUG") and not any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, RotatingFileHandler)
        for handler in logging.getLogger("scholarmind").handlers
    ):
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        stream.setLevel(log_level)
        logging.getLogger("scholarmind").addHandler(stream)

    app.logger.setLevel(log_level)


def _init_extensions(app: Flask) -> None:
    """Bind Flask extensions to the app and start shared background jobs once."""
    global _SERVICES_STARTED
    db.init_app(app)

    if not app.config.get("START_BACKGROUND_SERVICES", True):
        return

    if not scheduler.running:
        scheduler.start()

    if not _SERVICES_STARTED:
        _register_scheduler_jobs(app)
        _SERVICES_STARTED = True


def _configure_cors(app: Flask) -> None:
    """Allow the local Telegram Web client to call the local ScholarMind API."""
    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        if origin in {"http://localhost:1234", "http://127.0.0.1:1234"}:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Vary"] = "Origin"
        return response


def _register_scheduler_jobs(app: Flask) -> None:
    """Register recurring background jobs with APScheduler."""
    from .services.sync_service import sync_all_sources

    if not scheduler.get_job("sync_all_sources"):
        scheduler.add_job(
            id="sync_all_sources",
            func=sync_all_sources,
            args=[app],
            trigger="interval",
            minutes=15,
            misfire_grace_time=60,
        )
        app.logger.info("Scheduler: sync_all_sources registered (every 15 min)")

    if not scheduler.get_job("process_pending"):
        scheduler.add_job(
            id="process_pending",
            func=_run_enrichment,
            args=[app],
            trigger="interval",
            minutes=5,
            misfire_grace_time=30,
        )
        app.logger.info("Scheduler: process_pending registered (every 5 min)")


def _run_enrichment(app: Flask) -> None:
    """Scheduled job: drain pending raw items through the AI pipeline."""
    with app.app_context():
        from .services.enrichment_service import EnrichmentService
        log = logging.getLogger("scholarmind.ai")
        try:
            svc = EnrichmentService()
            count = svc.process_pending()
            if count:
                log.info("Scheduled enrichment: processed %d item(s)", count)
        except Exception as exc:
            log.exception("Scheduled enrichment failed: %s", exc)


def _register_blueprints(app: Flask) -> None:
    """Register all route blueprints."""
    from .routes.auth       import bp as auth_bp
    from .routes.auth       import bp as auth_bp
    from .routes.dashboard   import bp as dashboard_bp
    from .routes.scholarships import bp as scholarships_bp
    from .routes.sources     import bp as sources_bp
    from .routes.tracker     import bp as tracker_bp
    from .routes.profile     import bp as profile_bp
    from .routes.chat        import bp as chat_bp
    from .routes.feed        import bp as feed_bp
    from .routes.news        import bp as news_bp
    from .routes.backups     import bp as backups_bp
    from .routes.api         import bp as api_bp
    from .routes.settings    import bp as settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(scholarships_bp)
    app.register_blueprint(sources_bp)
    app.register_blueprint(tracker_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(feed_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(backups_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(settings_bp)


def _register_context_processors(app: Flask) -> None:
    """Inject variables available in every Jinja2 template."""
    from datetime import datetime, timezone

    @app.context_processor
    def inject_globals():
        return {
            "app_name": "ScholarMind AI",
            "current_year": datetime.now(timezone.utc).year,
        }


def _register_error_handlers(app: Flask) -> None:
    """Handle HTTP errors with styled pages."""
    from flask import render_template

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error("Internal server error: %s", e)
        return render_template("errors/500.html"), 500
