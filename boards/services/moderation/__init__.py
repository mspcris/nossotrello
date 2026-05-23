"""Pipeline de moderação de conteúdo da rede social.

Três camadas (de mais barata para mais cara):
  1. blocklist.py  — match determinístico contra termos banidos (BannedTerm).
  2. openai_client — moderação contextual via OpenAI Moderation API (gratuita).
  3. fila humana   — qualquer caso suspeito vira ModerationCase pendente
                     que aparece em /admin/moderation/queue/.

O `pipeline.check_or_block(...)` é o ponto de entrada usado nas views:
levanta `ContentBlocked` (Camada 1) ou agenda Camada 2 em background.
"""
from .pipeline import (  # noqa: F401
    ContentBlocked,
    check_or_block,
    schedule_layer2,
)
