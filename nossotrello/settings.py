"""
Django settings for nossotrello project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega variáveis do .env do projeto e sobrescreve ambiente (VSCode/export)
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)


# ============================================================
# BÁSICO (via ENV, com fallback no PROD)
# ============================================================

def _env_bool(key: str, default: bool = False) -> bool:
    v = (os.getenv(key, "") or "").strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return default

def _env_csv(key: str, default_list: list[str]) -> list[str]:
    raw = (os.getenv(key, "") or "").strip()
    if not raw:
        return default_list
    return [x.strip() for x in raw.split(",") if x.strip()]

# Fallback = o que já existia no PROD (evita quebrar build/collectstatic)
SECRET_KEY = (os.getenv("DJANGO_SECRET_KEY") or "").strip() or "django-insecure-*g97-4tr#q7%rz+b%)i_dgnocxt17ziww%x=7=zea_n$#i9%mj"
DEBUG = _env_bool("DEBUG", default=False)

ALLOWED_HOSTS = _env_csv(
    "ALLOWED_HOSTS",
    default_list=["127.0.0.1", "localhost", "tarefas.camim.com.br"],
)

CSRF_TRUSTED_ORIGINS = _env_csv(
    "CSRF_TRUSTED_ORIGINS",
    default_list=[
        "https://tarefas.camim.com.br",
        "http://tarefas.camim.com.br",
        "http://tarefas.camim.com.br:8081",
    ],
)

# ============================================================
# BANCO (SQLite) — permite variar o nome via ENV
# ============================================================

SQLITE_NAME = (os.getenv("SQLITE_NAME") or "db.sqlite3").strip() or "db.sqlite3"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db" / SQLITE_NAME,
    }
}


# ============================================================
# APLICAÇÕES
# ============================================================

INSTALLED_APPS = [
    # apps do projeto
    'boards',

    # apps nativos
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

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

    # força login no app (exceto rotas liberadas)
    'nossotrello.middleware.LoginRequiredMiddleware',

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
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STATIC_ROOT = BASE_DIR / "staticfiles"

# uploads de arquivos e imagens
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ============================================================
# Limites de upload no Django (não resolve 413 do Nginx, mas evita gargalos no app)
# ============================================================

DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024   # 100MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024   # 100MB

# ============================================================
# PADRÃO DJANGO
# ============================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ============================================================
# AUTH / LOGIN
# ============================================================

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"


# ============================================================
# EMAIL (SMTP) — necessário para "Primeiro login" e "Esqueci senha"
# ============================================================

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")

EMAIL_HOST = (os.getenv("EMAIL_HOST") or "").strip()
EMAIL_PORT = int(os.getenv("EMAIL_PORT") or 587)

EMAIL_HOST_USER = (os.getenv("EMAIL_HOST_USER") or "").strip()
EMAIL_HOST_PASSWORD = (os.getenv("EMAIL_HOST_PASSWORD") or "").strip()

# defaults seguros: não liga nada “por padrão”
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = _env_bool("EMAIL_USE_SSL", default=False)

# TLS e SSL são mutuamente exclusivos (evita crash)
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    if EMAIL_PORT == 465:
        EMAIL_USE_TLS = False
    else:
        EMAIL_USE_SSL = False

DEFAULT_FROM_EMAIL = (os.getenv("DEFAULT_FROM_EMAIL") or "no-reply@clinicacamim.com.br").strip()

# ============================================================
# Domínios institucionais permitidos
# ============================================================

INSTITUTIONAL_EMAIL_DOMAINS = _env_csv(
    "INSTITUTIONAL_EMAIL_DOMAINS",
    default_list=[
        "clinicacamim.com.br",
        "camim.com.br",
        "egidesaude.com.br",
    ],
)


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
