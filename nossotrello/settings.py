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
SECRET_KEY = (os.getenv("DJANGO_SECRET_KEY") or "").strip()
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY não configurada")

DEBUG = _env_bool("DEBUG", default=False)

ALLOWED_HOSTS = _env_csv(
    "ALLOWED_HOSTS",
    default_list=["127.0.0.1", "localhost", "tarefas.camim.com.br",
                  "192.168.1.213","192.168.1.226",  "192.168.0.129",],

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
# BANCO — PostgreSQL (produção) / SQLite (dev fallback)
# ============================================================

_DB_ENGINE = (os.getenv("DB_ENGINE") or "").strip().lower()

if _DB_ENGINE == "postgresql" or os.getenv("DATABASE_URL", "").startswith("postgres"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": (os.getenv("DB_NAME") or "nossotrello").strip(),
            "USER": (os.getenv("DB_USER") or "nossotrello").strip(),
            "PASSWORD": (os.getenv("DB_PASSWORD") or "nossotrello_secret").strip(),
            "HOST": (os.getenv("DB_HOST") or "db").strip(),
            "PORT": (os.getenv("DB_PORT") or "5432").strip(),
            "CONN_MAX_AGE": 600,  # reutiliza conexões (10 min)
            "OPTIONS": {
                "connect_timeout": 10,
            },
        }
    }
else:
    SQLITE_NAME = (os.getenv("SQLITE_NAME") or "db.sqlite3").strip() or "db.sqlite3"
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db" / SQLITE_NAME,
            "OPTIONS": {
                "timeout": 30,
            },
        }
    }


# ============================================================
# APLICAÇÕES
# ============================================================

INSTALLED_APPS = [

    # Channels (WebSocket/ASGI) — precisa vir antes de staticfiles para o runserver
    'daphne',
    'channels',

    # apps do projeto tracktime
    'tracktime.apps.TracktimeConfig',

    # apps do projeto boards nossotrello
    'boards.apps.BoardsConfig',

    # API mobile (REST)
    'rest_framework',
    'rest_framework.authtoken',
    'api_mobile.apps.ApiMobileConfig',

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

    # força aceite dos Termos de Uso (após login)
    'nossotrello.middleware.TermsMiddleware',

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
                'boards.context_processors.user_profile_context',
                "boards.context_processors.brand_context",
                "boards.context_processors.whats_new_context",

            ],
        },
    },
]


WSGI_APPLICATION = 'nossotrello.wsgi.application'
ASGI_APPLICATION = 'nossotrello.asgi.application'


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

# uploads de arquivos e imagens
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Storage: banco de dados (PostgreSQL bytea) ou filesystem
# Controlado por env var — permite migração gradual
if _env_bool("USE_DB_STORAGE", default=False):
    STORAGES = {
        "default": {
            "BACKEND": "boards.storage.DatabaseStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }


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

AUTHENTICATION_BACKENDS = [
    "boards.auth_backends.UsernameOrEmailBackend",
]

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
# EMAIL — conta exclusiva da PARTE SOCIAL (KingHost)
# ============================================================
# Lido por boards/services/notifications.py via _build_social_email_connection().
# Não vira EMAIL_BACKEND global — só as 4 funções da social usam.
SOCIAL_EMAIL_HOST = (os.getenv("SOCIAL_EMAIL_HOST") or "").strip()
SOCIAL_EMAIL_PORT = int(os.getenv("SOCIAL_EMAIL_PORT") or 465)
SOCIAL_EMAIL_HOST_USER = (os.getenv("SOCIAL_EMAIL_HOST_USER") or "").strip()
SOCIAL_EMAIL_HOST_PASSWORD = (os.getenv("SOCIAL_EMAIL_HOST_PASSWORD") or "").strip()
SOCIAL_EMAIL_USE_SSL = _env_bool("SOCIAL_EMAIL_USE_SSL", default=True)
SOCIAL_EMAIL_USE_TLS = _env_bool("SOCIAL_EMAIL_USE_TLS", default=False)
SOCIAL_EMAIL_TIMEOUT = int(os.getenv("SOCIAL_EMAIL_TIMEOUT") or 30)
SOCIAL_DEFAULT_FROM_EMAIL = (
    os.getenv("SOCIAL_DEFAULT_FROM_EMAIL")
    or SOCIAL_EMAIL_HOST_USER
    or DEFAULT_FROM_EMAIL
).strip()

# TLS e SSL são mutuamente exclusivos
if SOCIAL_EMAIL_USE_TLS and SOCIAL_EMAIL_USE_SSL:
    if SOCIAL_EMAIL_PORT == 465:
        SOCIAL_EMAIL_USE_TLS = False
    else:
        SOCIAL_EMAIL_USE_SSL = False


# ============================================================
# WHATSAPP -
# ============================================================
import os

PRESSTICKET_TOKEN = os.getenv("PRESSTICKET_TOKEN", "").strip()
PRESSTICKET_BASE_URL = os.getenv("PRESSTICKET_BASE_URL", "https://api.atendimento.camim.com.br").strip()

PRESSTICKET_USER_ID = int(os.getenv("PRESSTICKET_USER_ID", "0") or 0)
PRESSTICKET_QUEUE_ID = int(os.getenv("PRESSTICKET_QUEUE_ID", "0") or 0)
PRESSTICKET_WHATSAPP_ID = int(os.getenv("PRESSTICKET_WHATSAPP_ID", "0") or 0)

EVOLUTION_BASE_URL = os.getenv("EVOLUTION_BASE_URL", "").strip()
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "").strip()
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "").strip()



# ============================================================
# Domínios institucionais permitidos
# ============================================================

INSTITUTIONAL_EMAIL_DOMAINS = _env_csv(
    "INSTITUTIONAL_EMAIL_DOMAINS",
    default_list=[
        "clinicacamim.com.br",
        "camim.com.br",
        "egidesaude.com.br",
        "arquitetodigital.com.br",
        "sabesistemas.com.br",
        "mrfsolution.com.br",
    ],
)

# ============================================================
# URL base pública do sistema (para links em e-mails / tarefas sem request)
# ============================================================
SITE_URL = (os.getenv("SITE_URL") or "http://localhost:8000").strip().rstrip("/")


# ============================================================
# IDCamim OAuth2/OIDC
# ============================================================
CAMIM_CLIENT_ID     = (os.getenv("CAMIM_CLIENT_ID") or "").strip()
CAMIM_CLIENT_SECRET = (os.getenv("CAMIM_CLIENT_SECRET") or "").strip()


# ============================================================
# GROQ AI API (mood check-in / chatbot motivacional)
# ============================================================
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()


# ============================================================
# CACHE (Redis) — necessário para fluxos multi-instância (homolog/prod)
# ============================================================

REDIS_URL = (os.getenv("REDIS_URL") or "").strip()

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,  # ex: redis://:senha@host:6379/1
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
            # evita colisão entre ambientes no mesmo Redis
            "KEY_PREFIX": (os.getenv("CACHE_KEY_PREFIX") or "nossotrello").strip(),
        }
    }
else:
    # fallback: mantém comportamento atual (1 processo ok, multi-processo não)
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "nossotrello-locmem",
        }
    }


# ============================================================
# DJANGO REST FRAMEWORK (API mobile)
# ============================================================
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}


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
    "loggers": {
        # pika é ultra-verboso em DEBUG; silencia para WARNING.
        "pika": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}


# ============================================================
# CHANNELS — Channel layer via Redis
# ------------------------------------------------------------
# O channel layer é o barramento que liga múltiplos processos
# daphne aos grupos de WebSocket. Reusa o mesmo Redis do cache,
# mas em um DB separado (db 2) para isolamento.
# ============================================================

def _channel_redis_url() -> str:
    raw = (os.getenv("REDIS_URL") or "").strip()
    if not raw:
        return "redis://redis:6379/2"
    # troca /<n> final pelo db 2 dedicado a channels
    if "/" in raw.rsplit("//", 1)[-1]:
        head, _tail = raw.rsplit("/", 1)
        return f"{head}/2"
    return raw.rstrip("/") + "/2"


CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [_channel_redis_url()],
            "capacity": 1500,
            "expiry": 60,
        },
    },
}


# ============================================================
# RabbitMQ — barramento pub/sub inter-serviço
# ------------------------------------------------------------
# Producer: Django web publica eventos quando algo muda.
# Consumer: `rabbit_bridge` (management command) consome e
# propaga para os grupos do Channels, que entregam por WebSocket.
# ============================================================
RABBITMQ_HOST = (os.getenv("RABBITMQ_HOST") or "").strip()
RABBITMQ_PORT = int((os.getenv("RABBITMQ_PORT") or "5672").strip())
RABBITMQ_USER = (os.getenv("RABBITMQ_USER") or "").strip()
RABBITMQ_PASSWORD = (os.getenv("RABBITMQ_PASSWORD") or "").strip()
RABBITMQ_VHOST = (os.getenv("RABBITMQ_VHOST") or "/").strip()
RABBITMQ_EXCHANGE = (os.getenv("RABBITMQ_EXCHANGE") or "nossotrello").strip()
RABBITMQ_ROUTING_KEY = (os.getenv("RABBITMQ_ROUTING_KEY") or f"{RABBITMQ_EXCHANGE}_router").strip()
RABBITMQ_CONSUMER_QUEUE = (os.getenv("RABBITMQ_CONSUMER_QUEUE") or "nossotrello-bridge").strip()

# Se o broker não estiver configurado o producer vira no-op (degrada suave).
PUBSUB_ENABLED = bool(RABBITMQ_HOST and RABBITMQ_USER)
