import logging
import requests
from django.core.management.base import BaseCommand
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django_apscheduler.jobstores import DjangoJobStore
from django_apscheduler import util
from django_apscheduler.models import DjangoJobExecution

logger = logging.getLogger(__name__)

def send_morning_health_tip():
   
    try:
        base_url = "https://web-production-8b01c.up.railway.app"
        response = requests.post(
            f"{base_url}/api/daily-tip?time=morning",
            timeout=30
        )
        if response.status_code == 200:
            logger.info("Morning health tip sent successfully via scheduler")
            print("Morning health tip sent successfully")
        else:
            logger.error(f"Failed to send morning tip: {response.status_code}")
            print(f"Failed to send morning tip: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending morning tip: {str(e)}")
        print(f"Error sending morning tip: {str(e)}")

def send_afternoon_health_tip():
   
    try:
        base_url = "https://web-production-8b01c.up.railway.app"
        response = requests.post(
            f"{base_url}/api/daily-tip?time=afternoon",
            timeout=30
        )
        if response.status_code == 200:
            logger.info("Afternoon health tip sent successfully via scheduler")
            print("Afternoon health tip sent successfully")
        else:
            logger.error(f"Failed to send afternoon tip: {response.status_code}")
            print(f"Failed to send afternoon tip: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending afternoon tip: {str(e)}")
        print(f"Error sending afternoon tip: {str(e)}")

def send_evening_health_tip():
    
    try:
        base_url = "https://web-production-8b01c.up.railway.app"
        response = requests.post(
            f"{base_url}/api/daily-tip?time=evening",
            timeout=30
        )
        if response.status_code == 200:
            logger.info("Evening health tip sent successfully via scheduler")
            print("Evening health tip sent successfully")
        else:
            logger.error(f"Failed to send evening tip: {response.status_code}")
            print(f"Failed to send evening tip: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending evening tip: {str(e)}")
        print(f"Error sending evening tip: {str(e)}")

@util.close_old_connections
def delete_old_job_executions(max_age=604_800):
    
    DjangoJobExecution.objects.delete_old_job_executions(max_age)

class Command(BaseCommand):
    help = "Starts the APScheduler for daily health tips at 9am, 3pm, and 8pm"
    
    def handle(self, *args, **options):
        scheduler = BackgroundScheduler()
        scheduler.add_jobstore(DjangoJobStore(), "default")
        
       
        scheduler.add_job(
            send_morning_health_tip,
            trigger=CronTrigger(hour=9, minute=0),  
            id="morning_health_tip",
            max_instances=1,
            replace_existing=True,
        )
        
       
        scheduler.add_job(
            send_afternoon_health_tip,
            trigger=CronTrigger(hour=15, minute=0),  
            id="afternoon_health_tip",
            max_instances=1,
            replace_existing=True,
        )
        
        
        scheduler.add_job(
            send_evening_health_tip,
            trigger=CronTrigger(hour=20, minute=0),  
            id="evening_health_tip",
            max_instances=1,
            replace_existing=True,
        )
        
       
        scheduler.add_job(
            delete_old_job_executions,
            trigger=CronTrigger(day_of_week="mon", hour="00", minute="00"),
            id="delete_old_job_executions",
            max_instances=1,
            replace_existing=True,
        )
        
        logger.info("Added health tip jobs: 9:00 AM, 3:00 PM, and 8:00 PM UTC daily")
        print("Added health tip jobs: 9:00 AM, 3:00 PM, and 8:00 PM UTC daily")
        
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