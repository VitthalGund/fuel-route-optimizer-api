from django.urls import path
from api.views import RouteView, HealthView

urlpatterns = [
    path('route/', RouteView.as_view(), name='route-optimizer'),
    path('health/', HealthView.as_view(), name='health-check'),
]
