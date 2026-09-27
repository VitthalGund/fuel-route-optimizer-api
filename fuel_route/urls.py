"""
URL configuration for fuel_route project.
"""
from django.contrib import admin
from django.urls import path, include

from api.views import PreviewView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', PreviewView.as_view(), name='home-preview'),
    path('preview/', PreviewView.as_view(), name='preview'),
    path('api/', include('api.urls')),
]
