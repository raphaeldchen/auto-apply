from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from pipeline.config import Config
from pipeline.db import init_db
from pipeline.runner import run_pipeline
from pipeline.notifier import print_digest

def start_scheduler(config: Config, db_path: str = "auto_apply.db") -> None:
    scheduler = BlockingScheduler()

    def poll_job():
        conn = init_db(db_path)
        try:
            result = run_pipeline(config, conn)
            print_digest(result)
        finally:
            conn.close()

    minutes = config.schedule.poll_interval_minutes
    scheduler.add_job(poll_job, "interval", minutes=minutes, next_run_time=datetime.now())
    print(f"Scheduler started. Polling now, then every {minutes} min. Press Ctrl+C to stop.")
    scheduler.start()
