"""Development settings."""
from .base import *

DEBUG = True
ALLOWED_HOSTS = ['*']

# In local development, if Redis is not running, we can also support LocMemCache fallback seamlessly
