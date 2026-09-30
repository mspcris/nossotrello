"""Conta desativada no IDCamim → some do Tarefas; reativada → volta.

Desativar (painel/help desk do IDCamim ou 30 dias sem login lá):
  - sai de todos os quadros dos OUTROS (BoardMembership não-owner), guardando
    cada vínculo em RevokedBoardMembership para poder devolver;
  - os quadros do próprio usuário (role owner) ficam intactos;
  - is_active=False: derruba a sessão (auth backend recusa inativo), bloqueia
    o login e tira o usuário das listas/perfis da rede social.

Reativar (o IDCamim deixou de listar como inativo, ou o usuário conseguiu logar
pelo IDCamim — prova de que está ativo lá): devolve os compartilhamentos que
ainda fazem sentido e volta is_active=True. Banimento da moderação
(account_blocked / idcamim_blocked) NUNCA é desfeito por aqui.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from boards.models import BoardMembership, RevokedBoardMembership, UserProfile

logger = logging.getLogger(__name__)


def _profile(user) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def is_moderation_banned(profile: UserProfile) -> bool:
    return bool(profile.account_blocked or profile.idcamim_blocked)


@transaction.atomic
def apply_idcamim_inactive(user) -> int:
    """Retira o usuário dos quadros dos outros e desativa a conta local.

    Idempotente. Retorna quantos compartilhamentos foram retirados agora.
    """
    profile = _profile(user)
    memberships = list(
        BoardMembership.objects
        .select_for_update()
        .filter(user=user)
        .exclude(role=BoardMembership.Role.OWNER)
    )
    for m in memberships:
        RevokedBoardMembership.objects.update_or_create(
            board_id=m.board_id,
            user=user,
            defaults={
                "role": m.role,
                "invited_at": m.invited_at,
                "accepted_at": m.accepted_at,
                "membership_created_at": m.created_at,
                "reason": "idcamim_inativo",
            },
        )
    if memberships:
        BoardMembership.objects.filter(id__in=[m.id for m in memberships]).delete()

    if not profile.idcamim_inativo:
        profile.idcamim_inativo = True
        profile.idcamim_inativo_em = timezone.now()
        profile.save(update_fields=["idcamim_inativo", "idcamim_inativo_em"])
    if user.is_active:
        user.is_active = False
        user.save(update_fields=["is_active"])

    logger.info(
        "idcamim_status: user=%s desativado no IDCamim — %d compartilhamento(s) retirado(s)",
        user.pk, len(memberships),
    )
    return len(memberships)


@transaction.atomic
def apply_idcamim_reactivated(user) -> int:
    """Devolve os compartilhamentos retirados e reativa a conta local.

    Só age em quem foi desativado por este fluxo (idcamim_inativo=True) e não
    está banido pela moderação. Retorna quantos compartilhamentos voltaram.
    """
    profile = _profile(user)
    if not profile.idcamim_inativo or is_moderation_banned(profile):
        return 0

    restored = 0
    for r in RevokedBoardMembership.objects.select_for_update().filter(user=user):
        # Quadro apagado de vez some pelo CASCADE; quadro arquivado/lixeira
        # volta igual (o vínculo só aparece se o quadro voltar).
        _, created = BoardMembership.objects.get_or_create(
            board_id=r.board_id,
            user=user,
            defaults={
                "role": r.role,
                "invited_at": r.invited_at,
                "accepted_at": r.accepted_at,
            },
        )
        restored += int(created)
        r.delete()

    profile.idcamim_inativo = False
    profile.idcamim_inativo_em = None
    profile.save(update_fields=["idcamim_inativo", "idcamim_inativo_em"])
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=["is_active"])

    logger.info(
        "idcamim_status: user=%s reativado no IDCamim — %d compartilhamento(s) devolvido(s)",
        user.pk, restored,
    )
    return restored
