"""
WSGI config for nossotrello project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from dotenv import load_dotenv
from django.core.wsgi import get_wsgi_application

# carrega variáveis do .env a partir da raiz do projeto
load_dotenv()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nossotrello.settings")

application = get_wsgi_application()
