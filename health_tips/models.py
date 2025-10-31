from django.db import models
import uuid

class HealthTipDelivery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tip_content = models.TextField()
    delivery_time = models.DateTimeField(auto_now_add=True)
    context_id = models.CharField(max_length=255, null=True, blank=True)
    task_id = models.CharField(max_length=255, null=True, blank=True)
    
    class Meta:
        db_table = 'health_tip_deliveries'
        ordering = ['-delivery_time']