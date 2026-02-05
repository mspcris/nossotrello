# boards/services/notifications.py

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from boards.models import BoardMembership, Mention, UserProfile, Card
from tracktime.services.pressticket import send_text_message, PressTicketError

logger = logging.getLogger(__name__)


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

    # Abre o card já no contexto do Track-time (se seu frontend respeita tab=tracktime)
    tracktime_url = f"{card_url}&tab=tracktime"

    return CardSnapshot(
        card_id=card_id,
        board_id=board_id,
        title=(card.title or "").strip(),
        tags=(card.tags or "").strip(),
        description=(card.description or "").strip(),
        start_date=_fmt_date(card.start_date),
        due_warn_date=_fmt_date(card.due_warn_date),
        due_date=_fmt_date(card.due_date),
        card_url=card_url,
        tracktime_url=tracktime_url,
    )


def format_card_message(*, title_prefix: str, snap: CardSnapshot, extra_lines: list[str] | None = None) -> str:
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


def _user_allowed_for_card(*, user, prof: UserProfile, card: Card) -> bool:
    if not prof.notify_only_owned_or_mentioned:
        return True

    # dono do card
    if getattr(card, "created_by_id", None) == user.id:
        return True

    # mencionado no card (description/activity)
    return Mention.objects.filter(card=card, mentioned_user=user).exists()


def get_board_recipients_for_card(*, card: Card):
    board = card.column.board
    memberships = (
        BoardMembership.objects
        .filter(board=board)
        .select_related("user", "user__profile")
    )
    users = [m.user for m in memberships]
    return users


def send_whatsapp(*, user, phone_digits: str, body: str) -> None:
    base_url = (getattr(settings, "PRESSTICKET_BASE_URL", "") or "").strip()
    token = (getattr(settings, "PRESSTICKET_TOKEN", "") or "").strip()
    user_id = int(getattr(settings, "PRESSTICKET_USER_ID", 0) or 0)
    queue_id = int(getattr(settings, "PRESSTICKET_QUEUE_ID", 0) or 0)
    whatsapp_id = int(getattr(settings, "PRESSTICKET_WHATSAPP_ID", 0) or 0)

    logger.warning(
        "pressticket: sending kind=message number=%r base_url=%r user_id=%s queue_id=%s whatsapp_id=%s",
        phone_digits, base_url, user_id, queue_id, whatsapp_id
    )

    resp = send_text_message(
        base_url=base_url,
        token=token,
        number=phone_digits,
        body=body,
        user_id=user_id,
        queue_id=queue_id,
        whatsapp_id=whatsapp_id,
    )

    # Se a API sempre devolve {"error":{...}} mesmo em sucesso, não vamos “reclassificar”.
    # Só logamos algum identificador se existir.
    try:
        msg_id = (
            resp.get("error", {})
                .get("_data", {})
                .get("id", {})
                .get("_serialized", "")
        )
        if msg_id:
            logger.warning("pressticket: api ok msg_id=%r", msg_id)
    except Exception:
        pass

    logger.warning("pressticket: sent ok kind=message number=%r resp_keys=%s", phone_digits, list((resp or {}).keys())[:15])


def send_email_notification(*, to_email: str, subject: str, body: str) -> None:
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or "no-reply@localhost"
    send_mail(
        subject=subject,
        message=body,
        from_email=from_email,
        recipient_list=[to_email],
        fail_silently=False,
    )


def notify_users_for_card(
    *,
    card: Card,
    recipients: Iterable,
    subject: str,
    message: str,
    include_link_as_second_whatsapp_message: bool = True,
) -> None:
    snap = build_card_snapshot(card=card)

    for u in recipients:
        prof = _get_or_create_profile(u)

        if not _user_allowed_for_card(user=u, prof=prof, card=card):
            continue

        # WhatsApp
        if prof.notify_whatsapp:
            phone = (prof.telefone or "").strip()
            if phone:
                try:
                    send_whatsapp(user=u, phone_digits=phone, body=message)
                    if include_link_as_second_whatsapp_message:
                        send_whatsapp(user=u, phone_digits=phone, body=snap.tracktime_url)
                except PressTicketError:
                    logger.exception("pressticket: send failed (PressTicketError) user_id=%s card_id=%s", u.id, card.id)
                except Exception:
                    logger.exception("pressticket: send failed (unexpected) user_id=%s card_id=%s", u.id, card.id)

        # Email
        if prof.notify_email:
            to_email = (getattr(u, "email", "") or "").strip()
            if to_email:
                try:
                    # Email com link junto no corpo (não separado em 2 mensagens)
                    body = f"{message}\n\nLink: {snap.tracktime_url}\n"
                    send_email_notification(to_email=to_email, subject=subject, body=body)
                except Exception:
                    logger.exception("email: send failed user_id=%s card_id=%s", u.id, card.id)
