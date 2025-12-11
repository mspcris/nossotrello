"""
Django settings for nossotrello project.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


# ============================================================
# BÁSICO
# ============================================================

SECRET_KEY = 'django-insecure-*g97-4tr#q7%rz+b%)i_dgnocxt17ziww%x=7=zea_n$#i9%mj'

DEBUG = True

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    'tarefas.camim.com.br',
]

CSRF_TRUSTED_ORIGINS = [
    'http://tarefas.camim.com.br',
    'http://tarefas.camim.com.br:8081',
    'https://tarefas.camim.com.br',
]



# ============================================================
# APLICAÇÕES
# ============================================================

INSTALLED_APPS = [
    # apps nativos
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # apps do projeto
    'boards',

    # integrações
    'django_htmx',

    # limpeza automática de arquivos (recomendado)
    'django_cleanup.apps.CleanupConfig',   # mantém media/ organizado
]


# ============================================================
# MIDDLEWARE
# ============================================================

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',

    # HTMX
    'django_htmx.middleware.HtmxMiddleware',

    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


ROOT_URLCONF = 'nossotrello.urls'


# ============================================================
# TEMPLATES
# ============================================================

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',

        # sua pasta global "templates/"
        'DIRS': [BASE_DIR / "templates"],

        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


WSGI_APPLICATION = 'nossotrello.wsgi.application'


# ============================================================
# BANCO DE DADOS
# ============================================================

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db' / 'db.sqlite3',
    }
}

# ============================================================
# VALIDADORES DE SENHA
# ============================================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ============================================================
# INTERNACIONALIZAÇÃO
# ============================================================

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_L10N = True
USE_TZ = True



# ============================================================
# STATIC E MEDIA
# ============================================================

# arquivos estáticos
STATIC_URL = 'static/'
STATICFILES_DIRS = [
    BASE_DIR / "static"
]
STATIC_ROOT = BASE_DIR / "staticfiles"

# uploads de arquivos e imagens
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ============================================================
# PADRÃO DJANGO
# ============================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
