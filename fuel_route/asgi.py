"""
ASGI config for fuel_route project.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fuel_route.settings.development')
application = get_asgi_application()
