from django.contrib import admin
from .models import HealthTipDelivery

@admin.register(HealthTipDelivery)
class HealthTipDeliveryAdmin(admin.ModelAdmin):
    list_display = ['tip_content', 'delivery_time', 'context_id', 'task_id']
    list_filter = ['delivery_time']
    search_fields = ['tip_content', 'context_id']
