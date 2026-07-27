"""Atividade social: quem "sumiu" por inatividade de login.

Regra: contas sem login há mais de 30 dias somem socialmente — não aparecem
em listas de amigos, em pedidos de amizade, nem nos posts "X e Y agora são
amigos" do reel. As PUBLICAÇÕES continuam visíveis: isto é só uma regra de
exibição, não desativa a conta nem apaga o vínculo de amizade.

Dinâmico e auto-reversível: assim que a pessoa loga de novo (last_login
atualiza no login, inclusive via IDCamim), ela reaparece. Baseado em
User.last_login — Tarefas e Tarefas Social compartilham o mesmo login.

NULL last_login (nunca logou) conta como inativo.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

SOCIAL_INACTIVITY_DAYS = 30


def social_active_cutoff():
    """Instante-limite: quem logou antes disto está socialmente inativo."""
    return timezone.now() - timedelta(days=SOCIAL_INACTIVITY_DAYS)


def is_socially_active(user) -> bool:
    """True se o user logou nos últimos 30 dias. Sem last_login = inativo."""
    ll = getattr(user, "last_login", None)
    return bool(ll and ll >= social_active_cutoff())


def active_ids(user_ids) -> set:
    """Subconjunto de user_ids cujos donos logaram nos últimos 30 dias."""
    ids = {i for i in user_ids if i}
    if not ids:
        return set()
    User = get_user_model()
    return set(
        User.objects
        .filter(id__in=ids, last_login__gte=social_active_cutoff())
        .values_list("id", flat=True)
    )


def filter_active_users(qs):
    """Restringe um queryset de User aos ativos (login nos últimos 30 dias)."""
    return qs.filter(last_login__gte=social_active_cutoff())
