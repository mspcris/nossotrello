# tracktime/services/notifications.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

import threading
from tracktime.services.evolution import send_text_message as evolution_send, EvolutionError

import html
import re
from django.utils.html import strip_tags

from boards.services.notifications import sanitize_card_description_to_text


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CardSnapshot:
    card_id: int
    board_id: int
    board_name: str
    column_name: str
    title: str
    tags: str
    description: str
    start_date: Optional[str]
    warn_date: Optional[str]
    due_date: Optional[str]
    card_url: str


def _safe_str(v) -> str:
    return (v or "").strip()


def _iso_or_none(dt) -> Optional[str]:
    if not dt:
        return None
    try:
        return dt.isoformat()
    except Exception:
        return None


_RE_DATA_IMG = re.compile(
    r"""<img\b[^>]*\bsrc=["']data:image/[^"']+["'][^>]*>""",
    flags=re.IGNORECASE,
)
_RE_DATA_ANY = re.compile(
    r"""data:image/[^;]+;base64,[a-z0-9+/=\s]+""",
    flags=re.IGNORECASE,
)

def sanitize_card_description_to_text(desc_html: str, *, limit: int = 450) -> str:
    """
    - remove imagens inline base64 (não vaza payload)
    - remove HTML
    - retorna texto puro, com limite
    """
    raw = (desc_html or "").strip()
    if not raw:
        return ""

    # remove <img src="data:image/...base64,...">
    raw = _RE_DATA_IMG.sub("", raw)

    # remove qualquer ocorrência remanescente de data:image...base64,...
    raw = _RE_DATA_ANY.sub("", raw)

    # HTML -> texto
    txt = strip_tags(raw)

    # decode entidades e normaliza espaços
    txt = html.unescape(txt)
    txt = re.sub(r"\s+\n", "\n", txt)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    txt = re.sub(r"[ \t]{2,}", " ", txt).strip()

    if limit and len(txt) > limit:
        txt = txt[:limit].rstrip() + "…"
    return txt




def snapshot_card(*, card, site_url: str) -> CardSnapshot:
    column = getattr(card, "column", None)
    board_id = getattr(column, "board_id", None) or 0
    board = getattr(column, "board", None)
    board_name = _safe_str(getattr(board, "name", ""))
    column_name = _safe_str(getattr(column, "name", ""))

    board_url = reverse("boards:board_detail", kwargs={"board_id": int(board_id or 0)})
    card_url = f"{board_url}?card={int(card.id)}"

    full_card_url = site_url.rstrip("/") + card_url

    return CardSnapshot(
        card_id=int(card.id),
        board_id=int(board_id or 0),
        board_name=board_name,
        column_name=column_name,
        title=_safe_str(getattr(card, "title", "")),
        tags=_safe_str(getattr(card, "tags", "")),
        description=sanitize_card_description_to_text(getattr(card, "description", "")),
        start_date=_iso_or_none(getattr(card, "start_date", None)),
        warn_date=_iso_or_none(getattr(card, "due_warn_date", None)),
        due_date=_iso_or_none(getattr(card, "due_date", None)),
        card_url=full_card_url,
    )


def _user_prefs(user) -> Tuple[bool, bool, str]:
    """
    returns: (allow_whatsapp, allow_email, phone_raw)
    """

    prof = getattr(user, "profile", None)
    allow_whatsapp = bool(getattr(prof, "notify_whatsapp", True)) if prof else True
    allow_email = bool(getattr(prof, "notify_email", True)) if prof else True
    phone = _safe_str(getattr(prof, "telefone", "")) if prof else ""
    return allow_whatsapp, allow_email, phone


def send_whatsapp(*, user, phone: str, kind: str, message: str) -> None:
    allow_whatsapp, _, phone_cfg = _user_prefs(user)

    if not allow_whatsapp:
        logger.info("notify: whatsapp skipped (user pref off) user_id=%s kind=%s", user.id, kind)
        return

    phone = _safe_str(phone or phone_cfg)
    if not phone:
        logger.info("notify: whatsapp skipped (no phone) user_id=%s kind=%s", user.id, kind)
        return

    phone_raw = phone
    phone = re.sub(r"\D+", "", phone_raw)

    if len(phone) in (10, 11):
        phone = "55" + phone

    if len(phone) not in (12, 13):
        logger.info("notify: whatsapp skipped (invalid phone) user_id=%s kind=%s raw=%r digits=%r", user.id, kind, phone_raw, phone)
        return

    base_url = _safe_str(getattr(settings, "EVOLUTION_BASE_URL", ""))
    api_key = _safe_str(getattr(settings, "EVOLUTION_API_KEY", ""))
    instance = _safe_str(getattr(settings, "EVOLUTION_INSTANCE", ""))

    if not (base_url and api_key and instance):
        logger.info("notify: whatsapp skipped (no evolution config) user_id=%s kind=%s", user.id, kind)
        return

    number = phone
    body = _safe_str(message)
    uid = getattr(user, "id", None)

    logger.info("evolution: sending kind=%s number=%r instance=%r user_id=%s", kind, number, instance, uid)

    def _send():
        try:
            evolution_send(
                base_url=base_url,
                api_key=api_key,
                instance=instance,
                number=number,
                body=body,
            )
            logger.info("evolution: sent ok kind=%s user_id=%s", kind, uid)
        except EvolutionError as e:
            logger.warning("evolution: send failed (EvolutionError) user_id=%s kind=%s: %s", uid, kind, e)
        except Exception as e:
            logger.warning("evolution: send failed user_id=%s kind=%s: %s", uid, kind, e)

    t = threading.Thread(target=_send, daemon=True)
    t.start()


def send_email_notify(*, user, subject: str, body: str) -> None:
    _, allow_email, _ = _user_prefs(user)
    if not allow_email:
        logger.info("notify: email skipped (user pref off) user_id=%s", user.id)
        return

    to_email = _safe_str(getattr(user, "email", ""))
    if not to_email:
        logger.info("notify: email skipped (no email) user_id=%s", user.id)
        return

    from_email = _safe_str(getattr(settings, "DEFAULT_FROM_EMAIL", "")) or None

    send_mail(
        subject=_safe_str(subject),
        message=_safe_str(body),
        from_email=from_email,
        recipient_list=[to_email],
        fail_silently=True,  # notificação não pode quebrar fluxo
    )


def notify_tracktime_extended(*, entry, request_user=None) -> None:
    """
    Dispara quando o usuário clica no link (+1h) e a sessão é estendida.
    """
    user = getattr(entry, "user", None)
    if not user:
        return

    site_url = _safe_str(getattr(settings, "SITE_URL", "")) or ""
    card = getattr(entry, "card", None)
    if not card:
        return

    snap = snapshot_card(card=card, site_url=site_url)

    # Link para abrir o board já com o card e tab tracktime (igual você quer)
    track_url = snap.card_url
    if "?" in track_url:
        track_url = track_url + "&tab=tracktime"
    else:
        track_url = track_url + "?tab=tracktime"

    title = snap.title or "Card"

    msg = (
        "⏱️ Track-time estendido (+1h)\n"
        f"Quadro: {snap.board_name}\n"
        f"Coluna: {snap.column_name}\n"
        f"Card: {title}\n"
        f"Tags: {snap.tags}\n"
        f"Descrição: {snap.description}\n"
        f"Data Início: {snap.start_date}\n"
        f"Data Aviso: {snap.warn_date}\n"
        f"Data Vencimento: {snap.due_date}\n"
    )

    # WhatsApp: 2 mensagens (texto + link puro)
    send_whatsapp(user=user, phone="", kind="extend_message", message=msg)
    send_whatsapp(user=user, phone="", kind="extend_url", message=track_url)

    # Email: assunto + corpo + link
    subj = f"[NossoTrello] Track-time estendido (+1h) — {title}"
    body = msg + "\nAbrir Track-time:\n" + track_url + "\n"
    send_email_notify(user=user, subject=subj, body=body)


def notify_card_deadline(*, user, card, kind: str) -> None:
    """
    kind:
      - warn_today
      - warn_minus_1
      - due_minus_1
      - due_today

    Cards marcados como entregue nunca recebem alertas de prazo.
    """
    # Guard: card entregue → silencioso
    if getattr(card, "is_delivered", False):
        logger.info(
            "notify: deadline skipped (card delivered) user_id=%s card_id=%s kind=%s",
            getattr(user, "id", None), getattr(card, "id", None), kind,
        )
        return

    site_url = _safe_str(getattr(settings, "SITE_URL", "")) or ""
    snap = snapshot_card(card=card, site_url=site_url)

    # abre board com card e já no tracktime
    track_url = snap.card_url
    if "?" in track_url:
        track_url = track_url + "&tab=tracktime"
    else:
        track_url = track_url + "?tab=tracktime"

    title = snap.title or "Card"

    kind_label = {
        "warn_today": "📣 Aviso do card (hoje)",
        "warn_minus_1": "📣 Aviso do card (amanhã)",
        "due_minus_1": "⏰ Vencimento do card (amanhã)",
        "due_today": "⏰ Vencimento do card (hoje)",
    }.get(kind, kind)

    msg = (
        f"{kind_label}\n"
        f"Quadro: {snap.board_name}\n"
        f"Coluna: {snap.column_name}\n"
        f"Card: {title}\n"
        f"Tags: {snap.tags}\n"
        f"Descrição: {snap.description}\n"
        f"Data Início: {snap.start_date}\n"
        f"Data Aviso: {snap.warn_date}\n"
        f"Data Vencimento: {snap.due_date}\n"
    )

    # WhatsApp: texto + link puro
    send_whatsapp(user=user, phone="", kind=f"card_{kind}_message", message=msg)
    send_whatsapp(user=user, phone="", kind=f"card_{kind}_url", message=track_url)

    subj = f"[NossoTrello] {kind_label} — {title}"
    body = msg + "\nAbrir card (Track-time):\n" + track_url + "\n"
    send_email_notify(user=user, subject=subj, body=body)
