"""Aplicação Celery do NossoTrello — a fila de tarefas em segundo plano.

Workers (docker-compose):
  worker          -Q default    e-mail, WhatsApp, notificações de seguidores
  worker-media    -Q media      ffmpeg, miniaturas, IA (pesado; não disputa com o resto)
  worker-ordered  -Q board_ops  UM consumidor só: operações do quadro em ordem (mover card)
  scheduler       celery beat   tarefas periódicas

Sem CELERY_BROKER_URL (dev local) nada disso é necessário: boards/services/jobs.py
executa pelo caminho antigo (thread ou direto).
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nossotrello.settings")

app = Celery("nossotrello")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
