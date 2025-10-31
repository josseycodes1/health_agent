import requests
from django.core.management.base import BaseCommand
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Send daily health tip to registered users'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--base-url',
            type=str,
            default='https://web-production-8b01c.up.railway.app',
            help='Base URL for the application'
        )
    
    def handle(self, *args, **options):
        base_url = options['base_url']
        
        try:
           
            response = requests.post(
                f"{base_url}/api/daily-tip",
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info("Daily health tip sent successfully")
                self.stdout.write(
                    self.style.SUCCESS('Daily health tip sent successfully')
                )
            else:
                logger.error(f"Failed to send daily tip: {response.status_code}")
                self.stdout.write(
                    self.style.ERROR(f'Failed to send daily tip: {response.status_code}')
                )
                
        except Exception as e:
            logger.error(f"Error sending daily tip: {str(e)}")
            self.stdout.write(
                self.style.ERROR(f'Error sending daily tip: {str(e)}')
            )