from django.urls import path
from .views import A2AHealthView, HealthCheckView

urlpatterns = [
    path('a2a/health/', A2AHealthView.as_view(), name='a2a_health'),
    path('health/', HealthCheckView.as_view(), name='health_check'),
]