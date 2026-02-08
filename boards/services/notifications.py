# boards/services/notifications.py
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.html import strip_tags

from boards.models import BoardMembership, Mention, UserProfile, Card, CardFollow
from tracktime.services.pressticket import send_text_message, PressTicketError

logger = logging.getLogger(__name__)
User = get_user_model()

_RE_DATA_IMG = re.compile(
    r"""<img\b[^>]*\bsrc=["']data:image/[^"']+["'][^>]*>""",
    flags=re.IGNORECASE,
)
_RE_DATA_ANY = re.compile(
    r"""data:image/[^;]+;base64,[a-z0-9+/=\s]+""",
    flags=re.IGNORECASE,
)


def sanitize_card_description_to_text(desc_html: str, *, limit: int = 450) -> str:
    raw = (desc_html or "").strip()
    if not raw:
        return ""

    # segurança: remove payload base64 (evita vazamento em email/whats/log)
    raw = _RE_DATA_IMG.sub("", raw)
    raw = _RE_DATA_ANY.sub("", raw)

    txt = strip_tags(raw)
    txt = html.unescape(txt)
    txt = re.sub(r"[ \t]{2,}", " ", txt).strip()

    if limit and len(txt) > limit:
        txt = txt[:limit].rstrip() + "…"
    return txt


@dataclass(frozen=True)
class CardSnapshot:
    card_id: int
    board_id: int
    title: str
    tags: str
    description: str
    start_date: str
    due_warn_date: str
    due_date: str
    card_url: str
    tracktime_url: str


def _fmt_date(d) -> str:
    if not d:
        return ""
    return d.strftime("%Y-%m-%d")


def build_card_snapshot(*, card: Card) -> CardSnapshot:
    board_id = int(card.column.board_id)
    card_id = int(card.id)

    board_url = reverse("boards:board_detail", kwargs={"board_id": board_id})
    card_url = f"{settings.SITE_URL.rstrip('/')}{board_url}?card={card_id}"
    tracktime_url = f"{card_url}&tab=tracktime"

    return CardSnapshot(
        card_id=card_id,
        board_id=board_id,
        title=(card.title or "").strip(),
        tags=(card.tags or "").strip(),
        description=sanitize_card_description_to_text(getattr(card, "description", "")),
        start_date=_fmt_date(card.start_date),
        due_warn_date=_fmt_date(card.due_warn_date),
        due_date=_fmt_date(card.due_date),
        card_url=card_url,
        tracktime_url=tracktime_url,
    )


def format_card_message(*, title_prefix: str, snap: CardSnapshot, extra_lines: Optional[list[str]] = None) -> str:
    lines = [
        title_prefix,
        f"Card: {snap.title}",
        f"Tags: {snap.tags}" if snap.tags else "Tags: (sem etiquetas)",
        f"Descrição: {snap.description}" if snap.description else "Descrição: (vazia)",
        f"Data Início: {snap.start_date}" if snap.start_date else "Data Início: (vazia)",
        f"Data Aviso: {snap.due_warn_date}" if snap.due_warn_date else "Data Aviso: (vazia)",
        f"Data Vencimento: {snap.due_date}" if snap.due_date else "Data Vencimento: (vazia)",
    ]
    if extra_lines:
        lines.extend(extra_lines)
    return "\n".join(lines).strip()


def _get_or_create_profile(user) -> UserProfile:
    prof = getattr(user, "profile", None)
    if prof:
        return prof
    prof, _ = UserProfile.objects.get_or_create(user=user)
    return prof


def get_board_recipients_for_card(*, card: Card) -> list[User]:
    board = card.column.board
    memberships = (
        BoardMembership.objects
        .filter(board=board)
        .select_related("user", "user__profile")
    )
    return [m.user for m in memberships]


def get_card_followers(*, card: Card) -> list[User]:
    """
    Regra: seguidores do card (olho) são o público padrão para atividade/track-time (para terceiros).
    """
    qs = (
        User.objects
        .filter(card_follows__card_id=card.id, is_active=True)
        .select_related("profile")
        .distinct()
    )
    return list(qs)


def _user_is_follower(*, card: Card, user: User) -> bool:
    return CardFollow.objects.filter(card_id=card.id, user_id=user.id).exists()


def _user_was_mentioned_in_card(*, card: Card, user: User) -> bool:
    return Mention.objects.filter(card_id=card.id, mentioned_user_id=user.id).exists()


def _safe_digits_phone(phone_raw: str) -> str:
    phone_digits = re.sub(r"\D+", "", (phone_raw or "").strip())

    # Se não tiver DDI, assume BR
    if len(phone_digits) in (10, 11):
        phone_digits = "55" + phone_digits

    # 55 + DDD + 8/9
    if len(phone_digits) not in (12, 13):
        return ""
    return phone_digits


def send_whatsapp(*, user, phone_digits: str, body: str) -> None:
    base_url = (getattr(settings, "PRESSTICKET_BASE_URL", "") or "").strip()
    token = (getattr(settings, "PRESSTICKET_TOKEN", "") or "").strip()
    user_id = int(getattr(settings, "PRESSTICKET_USER_ID", 0) or 0)
    queue_id = int(getattr(settings, "PRESSTICKET_QUEUE_ID", 0) or 0)
    whatsapp_id = int(getattr(settings, "PRESSTICKET_WHATSAPP_ID", 0) or 0)

    if not (base_url and token and user_id and queue_id and whatsapp_id):
        logger.info("pressticket: skipped (missing config) user_id=%s", getattr(user, "id", None))
        return

    resp = send_text_message(
        base_url=base_url,
        token=token,
        number=phone_digits,
        body=body,
        user_id=user_id,
        queue_id=queue_id,
        whatsapp_id=whatsapp_id,
    )

    try:
        msg_id = (
            (resp or {}).get("error", {})
            .get("_data", {})
            .get("id", {})
            .get("_serialized", "")
        )
        if msg_id:
            logger.info("pressticket: ok msg_id=%r user_id=%s", msg_id, getattr(user, "id", None))
    except Exception:
        pass


def send_email_notification(*, to_email: str, subject: str, body: str) -> None:
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or None
    send_mail(
        subject=(subject or "").strip(),
        message=(body or "").strip(),
        from_email=from_email,
        recipient_list=[to_email],
        fail_silently=True,  # notificação não pode derrubar fluxo
    )


def notify_users_for_card(
    *,
    card: Card,
    recipients: Iterable[User],
    subject: str,
    message: str,
    snap: Optional[CardSnapshot] = None,
    include_link_as_second_whatsapp_message: bool = False,
    exclude_actor: bool = True,
    actor: Optional[User] = None,
):
    """
    Compliance com suas regras:
    - Notifica seguidores do card (público vem pronto em recipients) e/ou autor do track-time.
    - Nunca notifica o próprio em atividade normal (exclude_actor=True).
    - Para track-time, passe exclude_actor=False (autor deve ser notificado).
    - Flags/canais do usuário mandam (notify_email/notify_whatsapp).
    """
    if not recipients:
        return

    snap = snap or build_card_snapshot(card=card)
    link = snap.tracktime_url or snap.card_url

    for u in recipients:
        if not u:
            continue

        if exclude_actor and actor and getattr(u, "id", None) == getattr(actor, "id", None):
            continue

        prof = _get_or_create_profile(u)

        # WhatsApp
        if getattr(prof, "notify_whatsapp", False):
            phone_digits = _safe_digits_phone(getattr(prof, "telefone", ""))
            if phone_digits:
                try:
                    send_whatsapp(user=u, phone_digits=phone_digits, body=message)
                    if include_link_as_second_whatsapp_message:
                        send_whatsapp(user=u, phone_digits=phone_digits, body=link)
                except PressTicketError:
                    logger.exception("pressticket: send failed (PressTicketError) user_id=%s card_id=%s", u.id, card.id)
                except Exception:
                    logger.exception("pressticket: send failed (unexpected) user_id=%s card_id=%s", u.id, card.id)

        # Email
        if getattr(prof, "notify_email", False):
            to_email = (getattr(u, "email", "") or "").strip()
            if to_email:
                try:
                    body = f"{message}\n\nLink: {link}\n"
                    send_email_notification(to_email=to_email, subject=subject, body=body)
                except Exception:
                    logger.exception("email: send failed user_id=%s card_id=%s", u.id, card.id)
