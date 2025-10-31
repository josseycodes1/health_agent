from django.urls import path
from . import views

urlpatterns = [
    path('a2a/health', views.A2AHealthView.as_view(), name='a2a_health'),
    path('daily-tip', views.DailyHealthTipView.as_view(), name='daily_tip'),
    path('health', views.HealthCheckView.as_view(), name='health_check'),
]