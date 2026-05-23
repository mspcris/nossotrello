"""Camada de banimento — aplica BanLog e atualiza UserProfile/SocialPost.

Cada função aqui:
  1. Persiste um BanLog (registro imutável de auditoria).
  2. Atualiza estado em UserProfile (social_blocked / account_blocked / idcamim_blocked).
  3. Envia email pro usuário (via emails.send_ban_email).
  4. Marca email_sent_at no BanLog.

Convenção: `applied_by=None` significa ação automática do sistema; caso contrário
é o admin que apertou o botão.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


def _profile(user):
    return getattr(user, "profile", None)


def _bump_counters(user, *, warn: bool = False, block: bool = False):
    prof = _profile(user)
    if prof is None:
        return
    fields = []
    if warn:
        prof.social_warn_count = (prof.social_warn_count or 0) + 1
        fields.append("social_warn_count")
    if block:
        prof.social_block_count = (prof.social_block_count or 0) + 1
        fields.append("social_block_count")
    prof.last_offense_at = timezone.now()
    fields.append("last_offense_at")
    prof.save(update_fields=fields)


def _send_and_mark(banlog, user, *, action, reason, terms_clause, effective_until):
    from .emails import send_ban_email
    send_ban_email(
        user=user, action=action, reason=reason,
        terms_clause=terms_clause, effective_until=effective_until,
    )
    banlog.email_sent_at = timezone.now()
    banlog.save(update_fields=["email_sent_at"])


def warn_user(*, user, reason: str, terms_clause: str = "", case=None, applied_by=None):
    from boards.models import BanLog
    banlog = BanLog.objects.create(
        user=user, action=BanLog.ACTION_WARN,
        reason=reason, terms_clause=terms_clause,
        case=case, applied_by=applied_by,
    )
    _bump_counters(user, warn=True)
    _send_and_mark(
        banlog, user, action=BanLog.ACTION_WARN,
        reason=reason, terms_clause=terms_clause, effective_until=None,
    )
    return banlog


def block_post(*, post, reason: str, terms_clause: str = "", case=None, applied_by=None):
    from boards.models import BanLog, SocialPost
    SocialPost.objects.filter(pk=post.pk).update(
        moderation_status=SocialPost.MOD_REMOVED,
        moderation_reason=reason[:160],
        moderation_clause=terms_clause[:20],
    )
    banlog = BanLog.objects.create(
        user=post.user, action=BanLog.ACTION_POST_BLOCK,
        reason=reason, terms_clause=terms_clause,
        case=case, applied_by=applied_by,
    )
    _bump_counters(post.user, block=True)
    _send_and_mark(
        banlog, post.user, action=BanLog.ACTION_POST_BLOCK,
        reason=reason, terms_clause=terms_clause, effective_until=None,
    )
    return banlog


def block_social(
    *, user, reason: str, terms_clause: str = "", case=None, applied_by=None,
    effective_until=None,
):
    from boards.models import BanLog
    prof = _profile(user)
    if prof is not None:
        prof.social_blocked = True
        prof.social_blocked_until = effective_until
        prof.social_blocked_reason = reason[:240]
        prof.save(update_fields=["social_blocked", "social_blocked_until", "social_blocked_reason"])
    banlog = BanLog.objects.create(
        user=user, action=BanLog.ACTION_SOCIAL_BLOCK,
        reason=reason, terms_clause=terms_clause,
        case=case, applied_by=applied_by, effective_until=effective_until,
    )
    _bump_counters(user, block=True)
    _send_and_mark(
        banlog, user, action=BanLog.ACTION_SOCIAL_BLOCK,
        reason=reason, terms_clause=terms_clause, effective_until=effective_until,
    )
    return banlog


def block_account(
    *, user, reason: str, terms_clause: str = "", case=None, applied_by=None,
    effective_until=None,
):
    from boards.models import BanLog
    prof = _profile(user)
    if prof is not None:
        prof.account_blocked = True
        prof.account_blocked_until = effective_until
        prof.save(update_fields=["account_blocked", "account_blocked_until"])
    # Também marca is_active=False pra cortar login local imediatamente
    user.is_active = False
    user.save(update_fields=["is_active"])
    banlog = BanLog.objects.create(
        user=user, action=BanLog.ACTION_ACCOUNT_BLOCK,
        reason=reason, terms_clause=terms_clause,
        case=case, applied_by=applied_by, effective_until=effective_until,
    )
    _bump_counters(user, block=True)
    _send_and_mark(
        banlog, user, action=BanLog.ACTION_ACCOUNT_BLOCK,
        reason=reason, terms_clause=terms_clause, effective_until=effective_until,
    )
    return banlog


def block_idcamim(*, user, reason: str, terms_clause: str = "", case=None, applied_by=None):
    """Chama a API do IDCamim para desativar a conta lá. Punição máxima."""
    from boards.models import BanLog
    from .camim_admin import deactivate_user

    prof = _profile(user)
    camim_sub = getattr(prof, "camim_sub", "") if prof else ""
    api_result = deactivate_user(camim_sub) if camim_sub else None

    if prof is not None:
        prof.idcamim_blocked = True
        prof.idcamim_blocked_at = timezone.now()
        prof.account_blocked = True
        prof.save(update_fields=["idcamim_blocked", "idcamim_blocked_at", "account_blocked"])
    user.is_active = False
    user.save(update_fields=["is_active"])

    api_note = ""
    if api_result is None:
        api_note = " (sem camim_sub — IDCamim não foi chamado, ação manual necessária)"
    elif not api_result.ok:
        api_note = f" (IDCamim API falhou: {api_result.status_code} {api_result.error[:120]})"

    banlog = BanLog.objects.create(
        user=user, action=BanLog.ACTION_IDCAMIM_BLOCK,
        reason=(reason + api_note).strip(),
        terms_clause=terms_clause,
        case=case, applied_by=applied_by,
    )
    _bump_counters(user, block=True)
    _send_and_mark(
        banlog, user, action=BanLog.ACTION_IDCAMIM_BLOCK,
        reason=reason, terms_clause=terms_clause, effective_until=None,
    )
    return banlog
