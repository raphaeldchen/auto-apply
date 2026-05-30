from apscheduler.schedulers.blocking import BlockingScheduler
from pipeline.config import Config
from pipeline.db import init_db
from pipeline.runner import run_pipeline
from pipeline.notifier import print_digest

def start_scheduler(config: Config, db_path: str = "auto_apply.db") -> None:
    scheduler = BlockingScheduler()

    def daily_job():
        conn = init_db(db_path)
        try:
            result = run_pipeline(config, conn)
            print_digest(result)
        finally:
            conn.close()

    scheduler.add_job(daily_job, "cron", hour=8, minute=0)
    print("Scheduler started. Running daily at 08:00. Press Ctrl+C to stop.")
    scheduler.start()
