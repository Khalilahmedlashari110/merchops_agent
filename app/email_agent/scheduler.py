from apscheduler.schedulers.background import BackgroundScheduler

from app.email_agent.db_service import get_active_email_accounts
from app.email_agent.service import process_email_account


scheduler = BackgroundScheduler()


def poll_email_accounts_job():
    accounts = get_active_email_accounts()

    for account in accounts:
        try:
            process_email_account(account)
        except Exception as e:
            print("EMAIL AGENT JOB ERROR:", str(e))


def start_email_scheduler():
    if not scheduler.running:
        scheduler.add_job(
            poll_email_accounts_job,
            "interval",
            minutes=5,
            id="poll_email_accounts_job",
            replace_existing=True
        )
        scheduler.start()