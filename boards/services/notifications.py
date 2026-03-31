# boards/services/notifications.py
from __future__ import annotations

import html
import logging
import re
import threading
from dataclasses import dataclass
from typing import Iterable, Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.html import strip_tags

from boards.models import BoardMembership, Mention, UserProfile, Card, CardFollow
from tracktime.services.evolution import send_text_message as evolution_send, EvolutionError

from django.utils import timezone
from django.db import transaction




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
    board_name: str
    column_name: str
    card_position: int
    title: str
    tags: str
    description: str
    start_date: str
    due_warn_date: str
    due_date: str
    delivered_at: str
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

    delivered_at = getattr(card, "delivered_at", None)
    delivered_at_str = delivered_at.strftime("%Y-%m-%d") if delivered_at else ""

    return CardSnapshot(
        card_id=card_id,
        board_id=board_id,
        board_name=(card.column.board.name or "").strip(),
        column_name=(card.column.name or "").strip(),
        card_position=int(card.position) + 1,
        title=(card.title or "").strip(),
        tags=(card.tags or "").strip(),
        description=sanitize_card_description_to_text(getattr(card, "description", "")),
        start_date=_fmt_date(card.start_date),
        due_warn_date=_fmt_date(card.due_warn_date),
        due_date=_fmt_date(card.due_date),
        delivered_at=delivered_at_str,
        card_url=card_url,
        tracktime_url=tracktime_url,
    )


def _wa_safe(text: str) -> str:
    """
    Evita quebrar a formatação do WhatsApp (negrito/itálico/etc.)
    Troca caracteres de markdown do WhatsApp por equivalentes unicode.
    """
    s = (text or "").strip()
    if not s:
        return ""
    # WhatsApp: *negrito* _itálico_ ~tachado~ `mono`
    return (
        s.replace("*", "∗")
         .replace("_", "‗")
         .replace("~", "˜")
         .replace("`", "ˋ")
    )


def _wa_bold(label: str) -> str:
    # garante que o label não quebre o markdown
    return f"*{_wa_safe(label)}*"


def format_card_message(*, title_prefix: str, snap: CardSnapshot, extra_lines: Optional[list[str]] = None) -> str:
    title = _wa_safe(title_prefix)

    card_title = _wa_safe(snap.title)
    tags = _wa_safe(snap.tags)
    desc = _wa_safe(snap.description)

    start_date = _wa_safe(snap.start_date)
    warn_date = _wa_safe(snap.due_warn_date)
    due_date = _wa_safe(snap.due_date)
    delivered_at = _wa_safe(getattr(snap, "delivered_at", ""))

    board_name = _wa_safe(getattr(snap, 'board_name', ''))
    column_name = _wa_safe(getattr(snap, 'column_name', ''))
    card_position = getattr(snap, 'card_position', None)

    lines = [
        # título em negrito para destacar o "tipo" da notificação
        f"{_wa_bold(title)}",
        f"{_wa_bold('Quadro:')} {board_name}" if board_name else None,
        f"{_wa_bold('Coluna:')} {column_name}" if column_name else None,
        f"{_wa_bold('Posição:')} #{card_position}" if card_position else None,
        f"{_wa_bold('Card:')} {card_title}",
        f"{_wa_bold('Tags:')} {tags}" if tags else f"{_wa_bold('Tags:')} (sem etiquetas)",
        f"{_wa_bold('Descrição:')} {desc}" if desc else f"{_wa_bold('Descrição:')} (vazia)",
        f"{_wa_bold('Data Início:')} {start_date}" if start_date else f"{_wa_bold('Data Início:')} (vazia)",
        f"{_wa_bold('Data Aviso:')} {warn_date}" if warn_date else f"{_wa_bold('Data Aviso:')} (vazia)",
        f"{_wa_bold('Data Vencimento:')} {due_date}" if due_date else f"{_wa_bold('Data Vencimento:')} (vazia)",
        f"{_wa_bold('Data Entrega:')} {delivered_at}" if delivered_at else f"{_wa_bold('Data Entrega:')} (vazia)",
    ]

    if extra_lines:
        # mantém extras, mas também protege caracteres especiais
        lines.extend([_wa_safe(x) for x in extra_lines if x])

    return "\n".join(x for x in lines if x is not None).strip()



def is_in_notification_window(profile: UserProfile, *, now=None) -> bool:
    """
    Retorna True se o horário atual está dentro da janela de notificação do usuário.
    Verifica dia da semana + faixa de horário.
    """
    if now is None:
        now = timezone.localtime()

    weekday = now.weekday()  # 0=Mon ... 6=Sun
    day_fields = [
        "notify_days_mon", "notify_days_tue", "notify_days_wed",
        "notify_days_thu", "notify_days_fri", "notify_days_sat", "notify_days_sun",
    ]
    if not getattr(profile, day_fields[weekday], False):
        return False

    current_time = now.time()
    start = getattr(profile, "notify_start_time", None)
    end = getattr(profile, "notify_end_time", None)

    if not start or not end:
        return True

    return start <= current_time <= end


def next_notification_window(profile: UserProfile, *, now=None):
    """
    Retorna o próximo datetime em que a janela de notificação abre.
    Retorna None se nenhum dia está habilitado.
    """
    import datetime as _dt
    if now is None:
        now = timezone.localtime()

    day_fields = [
        "notify_days_mon", "notify_days_tue", "notify_days_wed",
        "notify_days_thu", "notify_days_fri", "notify_days_sat", "notify_days_sun",
    ]

    start_time = getattr(profile, "notify_start_time", None) or _dt.time(8, 0)

    # Verifica se ainda dá para hoje (se dia habilitado e antes do start)
    today_wd = now.weekday()
    if getattr(profile, day_fields[today_wd], False):
        today_start = now.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
        if now < today_start:
            return today_start

    # Procura nos próximos 7 dias
    for offset in range(1, 8):
        candidate = now + _dt.timedelta(days=offset)
        wd = candidate.weekday()
        if getattr(profile, day_fields[wd], False):
            return candidate.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)

    return None


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


def send_whatsapp(*, user, phone_digits: str, body: str, sync: bool = False) -> None:
    """
    Envia mensagem WhatsApp via Evolution API.
    sync=True → envia no mesmo thread (bloqueia até completar).
    sync=False → envia em background thread (fire-and-forget).
    """
    base_url = (getattr(settings, "EVOLUTION_BASE_URL", "") or "").strip()
    api_key = (getattr(settings, "EVOLUTION_API_KEY", "") or "").strip()
    instance = (getattr(settings, "EVOLUTION_INSTANCE", "") or "").strip()

    if not (base_url and api_key and instance):
        logger.info("evolution: skipped (missing config) user_id=%s", getattr(user, "id", None))
        return

    user_id = getattr(user, "id", None)

    def _send():
        try:
            evolution_send(
                base_url=base_url,
                api_key=api_key,
                instance=instance,
                number=phone_digits,
                body=body,
            )
        except EvolutionError as e:
            logger.warning("evolution: send failed (EvolutionError) user_id=%s: %s", user_id, e)
        except Exception as e:
            logger.warning("evolution: send failed user_id=%s: %s", user_id, e)

    if sync:
        _send()
    else:
        t = threading.Thread(target=_send, daemon=True)
        t.start()


def send_email_notification(*, to_email: str, subject: str, body: str) -> None:
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or None

    def _send():
        send_mail(
            subject=(subject or "").strip(),
            message=(body or "").strip(),
            from_email=from_email,
            recipient_list=[to_email],
            fail_silently=True,
        )

    threading.Thread(target=_send, daemon=True).start()


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
    allow_when_delivered: bool = False,  # <-- NOVO
):
    if not recipients:
        return

    # Gate: se o card está entregue, não notifica nada (email/whatsapp),
    # exceto quando explicitamente permitido (notificação de Entrega).
    if getattr(card, "is_delivered", False) and not allow_when_delivered:
        return

    snap = snap or build_card_snapshot(card=card)
    link = snap.card_url  # usa sempre a URL do card (sem &tab=tracktime que ainda não tem handler)
    
    """
    Compliance com suas regras:
    - Notifica seguidores do card (público vem pronto em recipients) e/ou autor do track-time.
    - Nunca notifica o próprio em atividade normal (exclude_actor=True).
    - Para track-time, passe exclude_actor=False (autor deve ser notificado).
    - Flags/canais do usuário mandam (notify_email/notify_whatsapp).
    - Criado portão para não disparar mensagens quando o card já está entregue (allow_when_delivered=False), exceto para notificações de Entrega (allow_when_delivered=True).
    """

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
                send_whatsapp(user=u, phone_digits=phone_digits, body=message)
                if include_link_as_second_whatsapp_message:
                    send_whatsapp(user=u, phone_digits=phone_digits, body=link)

        # Email
        if getattr(prof, "notify_email", False):
            to_email = (getattr(u, "email", "") or "").strip()
            if to_email:
                try:
                    body = f"{message}\n\nLink: {link}\n"
                    send_email_notification(to_email=to_email, subject=subject, body=body)
                except Exception:
                    logger.exception("email: send failed user_id=%s card_id=%s", u.id, card.id)






@transaction.atomic
def mark_card_delivered(*, card: Card, actor: Optional[User]) -> Card:
    """
    Marca o card como entregue e paralisa notificação visual (cores/prazo)
    via due_notify=False. Mantém vencimento preenchido (não mexe em due_date).
    """
    if not getattr(card, "is_delivered", False):
        card.is_delivered = True
        card.delivered_at = timezone.now()
        card.delivered_by = actor if actor and getattr(actor, "id", None) else None

        # Desliga notificações por prazo/cores
        if hasattr(card, "due_notify"):
            card.due_notify = False

        card.save(update_fields=["is_delivered", "delivered_at", "delivered_by", "due_notify"])
    return card


def notify_delivery(*, card: Card, actor: Optional[User] = None) -> None:
    """
    Envia a notificação de Entrega para seguidores do card (CardFollow),
    com link como 2ª mensagem (como hoje).
    """
    snap = build_card_snapshot(card=card)

    title_prefix = "✅ Entrega do Card"
    message = format_card_message(title_prefix=title_prefix, snap=snap)

    recipients = get_card_followers(card=card)

    notify_users_for_card(
        card=card,
        recipients=recipients,
        subject=title_prefix,
        message=message,
        snap=snap,
        include_link_as_second_whatsapp_message=True,  
        exclude_actor=False,  
        actor=actor,
        allow_when_delivered=True,  
    )
