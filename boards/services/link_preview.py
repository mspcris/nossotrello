"""Prévia de link (WhatsApp, Telegram, Slack…) para /board/<id>/?card=<id>.

O robô que monta a prévia não está logado — sem isto ele cai no login e a
prévia vira "NossoTrello — Acesso". Ele recebe uma página mínima só com as
tags og:.

Segurança: qualquer um finge ser o robô (é só o User-Agent). Por isso o título
do card SÓ aparece quando o link traz `s=` — HMAC do id do card com a
SECRET_KEY, que só quem enxerga o card recebe (modal, "Copiar link",
notificações). Sem `s` válido a prévia é genérica e não consulta o banco:
não dá pra varrer ids e nem saber se o card existe.
"""
import re

from django.conf import settings
from django.http import HttpResponse
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.html import escape

_SALT = "nossotrello.link-preview.card"
_SIG_LEN = 16

_BOT_UA = re.compile(
    r"whatsapp|facebookexternalhit|facebookcatalog|meta-externalagent|telegrambot|"
    r"slackbot|slack-imgproxy|discordbot|linkedinbot|twitterbot|skypeuripreview|"
    r"microsoftpreview|applebot|pinterest|embedly|iframely|vkshare|redditbot|"
    r"mattermost",
    re.I,
)
_BOARD_PATH = re.compile(r"^/board/(\d+)/$")


def card_sig(card_id) -> str:
    return salted_hmac(_SALT, str(int(card_id))).hexdigest()[:_SIG_LEN]


def card_sig_ok(card_id, sig) -> bool:
    if not sig:
        return False
    try:
        return constant_time_compare(card_sig(card_id), str(sig))
    except (TypeError, ValueError):
        return False


def card_share_query(card_id) -> str:
    """`card=<id>&s=<assinatura>` — pra montar link de card que vai ser repassado."""
    return f"card={int(card_id)}&s={card_sig(card_id)}"


def is_preview_bot(request) -> bool:
    return bool(_BOT_UA.search(request.META.get("HTTP_USER_AGENT", "")))


def _card_meta(card_id):
    from boards.models import Card

    card = (
        Card.objects.filter(
            pk=card_id,
            is_deleted=False,
            column__is_deleted=False,
            column__board__is_deleted=False,
        )
        .select_related("column__board")
        .only("title", "column__name", "column__board__name")
        .first()
    )
    if not card:
        return None
    title = " ".join((card.title or "").split())[:120] or f"Card #{card_id}"
    return title, f"Quadro {card.column.board.name} · {card.column.name}"


def preview_response(request):
    """HTML de prévia pro robô, ou None se a URL não é de quadro/card."""
    m = _BOARD_PATH.match(request.path or "")
    if not m:
        return None

    title = "NossoTrello — Tarefas Camim"
    desc = "Entre para ver este quadro."
    raw_card = request.GET.get("card", "")
    if raw_card.isdigit():
        card_id = int(raw_card)
        title = f"Card #{card_id} · NossoTrello"
        desc = "Entre para ver este card."
        if card_sig_ok(card_id, request.GET.get("s")):
            meta = _card_meta(card_id)
            if meta:
                title, desc = meta

    site = getattr(settings, "SITE_URL", "").rstrip("/") or f"{request.scheme}://{request.get_host()}"
    url = f"{site}{request.get_full_path()}"
    image = f"{site}{settings.STATIC_URL}images/social/camim_social_md.png"
    t, d, u, i = escape(title), escape(desc), escape(url), escape(image)
    html = (
        "<!doctype html><html lang=\"pt-br\"><head><meta charset=\"utf-8\">"
        f"<title>{t}</title>"
        f"<meta name=\"description\" content=\"{d}\">"
        f"<meta property=\"og:title\" content=\"{t}\">"
        f"<meta property=\"og:description\" content=\"{d}\">"
        f"<meta property=\"og:image\" content=\"{i}\">"
        f"<meta property=\"og:url\" content=\"{u}\">"
        "<meta property=\"og:type\" content=\"website\">"
        "<meta property=\"og:site_name\" content=\"NossoTrello\">"
        "<meta name=\"robots\" content=\"noindex, nofollow\">"
        f"</head><body><a href=\"{u}\">{t}</a></body></html>"
    )
    resp = HttpResponse(html, content_type="text/html; charset=utf-8")
    resp["Cache-Control"] = "private, max-age=300"
    resp["X-Robots-Tag"] = "noindex, nofollow"
    return resp
