import logging
import requests
from django.core.management.base import BaseCommand
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler import util
from django_apscheduler.models import DjangoJobExecution

logger = logging.getLogger(__name__)

def send_daily_health_tip():
    """Send daily health tip to the API"""
    try:
        # Use the same domain to avoid CORS issues
        base_url = "https://web-production-8b01c.up.railway.app"
        response = requests.post(
            f"{base_url}/api/daily-tip",
            timeout=30
        )
        if response.status_code == 200:
            logger.info("✅ Daily health tip sent successfully via scheduler")
            print("✅ Daily health tip sent successfully")
        else:
            logger.error(f"❌ Failed to send daily tip: {response.status_code}")
            print(f"❌ Failed to send daily tip: {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Error sending daily tip: {str(e)}")
        print(f"❌ Error sending daily tip: {str(e)}")

@util.close_old_connections
def delete_old_job_executions(max_age=604_800):
    """
    Delete old job executions to prevent the database from filling up
    """
    DjangoJobExecution.objects.delete_old_job_executions(max_age)

class Command(BaseCommand):
    help = "Starts the APScheduler for daily health tips"
    
    def handle(self, *args, **options):
        scheduler = BackgroundScheduler()
        scheduler.add_jobstore(DjangoJobStore(), "default")
        
        # Add daily health tip job (runs at 9:00 AM daily)
        scheduler.add_job(
            send_daily_health_tip,
            trigger=CronTrigger(hour=9, minute=0),  # 9:00 AM UTC daily
            id="daily_health_tip",
            max_instances=1,
            replace_existing=True,
        )
        
        # Optional: Clean up old job executions weekly
        scheduler.add_job(
            delete_old_job_executions,
            trigger=CronTrigger(day_of_week="mon", hour="00", minute="00"),
            id="delete_old_job_executions",
            max_instances=1,
            replace_existing=True,
        )
        
        logger.info("Added daily health tip job: 9:00 AM UTC daily")
        print("Added daily health tip job: 9:00 AM UTC daily")
        
        try:
            logger.info("Starting scheduler...")
            print("Starting scheduler...")
            scheduler.start()
        except KeyboardInterrupt:
            logger.info("Stopping scheduler...")
            scheduler.shutdown()
            logger.info("Scheduler shut down successfully")
        except Exception as e:
            logger.error(f"Scheduler error: {str(e)}")
            print(f"Scheduler error: {str(e)}")
            scheduler.shutdown()