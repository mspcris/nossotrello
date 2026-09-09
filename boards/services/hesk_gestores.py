# boards/services/hesk_gestores.py
"""Quem é gerente de cada posto — lido do cadastro do Hesk.

Fonte: administrativo.camim.com.br → Configurações → Gestores dos postos
(tabelas dashboard_gestor, dashboard_gestorposto, dashboard_posto no banco
`hesk`, alias `DATABASES["hesk"]`, somente leitura). O Tarefas não tem cargo no
perfil; posto/setor do UserProfile são digitados pelo próprio usuário e não
servem como fonte.

Casamento com o quadro: nome do quadro == nome do posto, sem acento e sem
caixa ("ANCHIETA" == "Anchieta", "CAMPO GRANDE X" == "Campo Grande X").

Cache de 10 min por posto. Se o Hesk estiver fora, devolve a última leitura
boa (guardada por 7 dias) — nunca levanta exceção para quem chama.
"""
import logging
import unicodedata

from django.conf import settings
from django.core.cache import cache
from django.db import connections

logger = logging.getLogger(__name__)

_TTL = 600
_TTL_LAST_GOOD = 7 * 24 * 3600

_SQL = """
SELECT p.nome, g.nome, g.email, g.telefone
FROM dashboard_posto p
JOIN dashboard_gestorposto gp ON gp.posto_id = p.id
JOIN dashboard_gestor g ON g.id = gp.gestor_id
WHERE p.excluido_em IS NULL
  AND g.excluido_em IS NULL
  AND g.ativo
ORDER BY p.ordem, p.nome, g.nome
"""


def normalize(name: str) -> str:
    """'CAMPO GRANDE X' -> 'campo grande x'; 'Nilópolis' -> 'nilopolis'."""
    s = unicodedata.normalize("NFKD", (name or "").strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def available() -> bool:
    return "hesk" in getattr(settings, "DATABASES", {})


def _fetch_all() -> dict:
    """{posto_normalizado: [{"nome","email","telefone"}, ...]} direto do Hesk."""
    out: dict = {}
    with connections["hesk"].cursor() as cur:
        cur.execute(_SQL)
        for posto, nome, email, tel in cur.fetchall():
            key = normalize(posto)
            out.setdefault(key, []).append({
                "nome": (nome or "").strip(),
                "email": (email or "").strip().lower(),
                "telefone": (tel or "").strip(),
            })
    return out


def gestores_por_posto(force: bool = False) -> dict:
    """Mapa completo posto -> gestores, com cache e fallback para a última leitura boa."""
    if not available():
        return {}
    key = "hesk:gestores:v1"
    if not force:
        data = cache.get(key)
        if data is not None:
            return data
    try:
        data = _fetch_all()
        cache.set(key, data, _TTL)
        cache.set(key + ":last_good", data, _TTL_LAST_GOOD)
        return data
    except Exception:
        logger.exception("hesk_gestores: leitura do Hesk falhou; usando última leitura boa")
        return cache.get(key + ":last_good") or {}


def gestores_do_posto(nome_posto: str) -> list:
    """Gestores ativos do posto (lista de dicts nome/email/telefone). [] se não achar."""
    if not nome_posto:
        return []
    return list(gestores_por_posto().get(normalize(nome_posto), []))
