"""Optional in-process scheduler (APScheduler) for deadline notifications.

It runs ONE background job every few minutes. Web requests never run it.

* Development: starts automatically (set SCHEDULER_ENABLED=false to turn it off).
* Production: off by default. Run `flask --app app notify-deadlines` every
  5 minutes from cron / Windows Task Scheduler / a worker instead, or set
  SCHEDULER_ENABLED=true for a single-process deployment.
* Several processes running it at once is harmless: the database's UNIQUE
  constraint on notifications stops duplicates.
"""
from datetime import datetime, timezone

from database import settings

SCAN_INTERVAL_MINUTES = 5


def init_scheduler(app):
    enabled = settings.env_flag("SCHEDULER_ENABLED", not app.config.get("IS_PRODUCTION"))
    if not enabled or app.config.get("TESTING") or app.config.get("APP_ENV") == "testing":
        return None
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        app.logger.warning("APScheduler is not installed (pip install \"APScheduler<4\"). "
                           "Deadline notifications will not be created automatically; "
                           "run `flask --app app notify-deadlines` instead.")
        return None

    import notifications

    def job():
        with app.app_context():
            try:
                created = notifications.run_deadline_scan()
                if created:
                    app.logger.info("Deadline scan created %s notification(s).", created)
            except Exception:  # noqa: BLE001
                app.logger.exception("Deadline scan failed")

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(job, "interval", minutes=SCAN_INTERVAL_MINUTES, id="deadline-scan",
                      max_instances=1, coalesce=True, replace_existing=True,
                      next_run_time=datetime.now(timezone.utc))  # also run once at start-up
    scheduler.start()
    app.extensions["deadline_scheduler"] = scheduler
    return scheduler
