# boards/views/polling.py

from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.templatetags.static import static as static_url
from django.utils import timezone

from ..models import Board, Column, Card, CardLog, CardSeen, CardFollow


def _user_avatar_url(u) -> str:
    prof = getattr(u, "profile", None)
    if prof and getattr(prof, "avatar", None):
        try:
            return prof.avatar.url
        except Exception:
            pass
    if prof and getattr(prof, "avatar_choice", ""):
        return static_url(f"images/avatar/{prof.avatar_choice}")
    return ""


@login_required
def board_poll(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    # ============================================================
    # Segurança: permissão de leitura (compatível + fallback seguro)
    # ============================================================
    if hasattr(board, "user_can_view"):
        if not board.user_can_view(request.user):
            return JsonResponse({"error": "forbidden"}, status=403)
    else:
        if not board.memberships.filter(user=request.user).exists():
            return JsonResponse({"error": "forbidden"}, status=403)

    # ============================================================
    # Versão que o cliente já possui
    # ============================================================
    try:
        client_version = int(request.GET.get("v", 0))
    except (TypeError, ValueError):
        client_version = 0

    if int(board.version or 0) == client_version:
        resp = JsonResponse({"version": board.version, "changed": False})
        resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp

    # ============================================================
    # Algo mudou -> re-renderiza colunas
    # ============================================================

    cards_qs = (
        Card.objects
        .filter(is_deleted=False)
        .select_related("column")  # ajuda template a acessar column sem N+1
        .order_by("position", "id")
    )

    columns = (
        Column.objects
        .filter(board=board, is_deleted=False)
        .annotate(card_count=Count("cards", distinct=True))
        .prefetch_related(Prefetch("cards", queryset=cards_qs))
        .order_by("position", "id")
    )

    # ============================================================
    # Reidratar estado de FOLLOW + previews (senão o poll “zera” UI)
    # ============================================================
    # Nota: o template do card espera:
    # - card.is_following
    # - card.followers_preview (list de dicts)
    # - card.followers_count (int)
    card_ids = []
    for col in columns:
        for c in col.cards.all():
            card_ids.append(c.id)

    if card_ids:
        followed_ids = set(
            CardFollow.objects
            .filter(user=request.user, card_id__in=card_ids)
            .values_list("card_id", flat=True)
        )

        by_card = defaultdict(list)
        counts = defaultdict(int)

        qs = (
            CardFollow.objects
            .filter(card_id__in=card_ids)
            .select_related("user", "user__profile")
            .order_by("card_id", "-created_at")
        )

        for f in qs:
            counts[f.card_id] += 1
            if len(by_card[f.card_id]) < 4:
                u = f.user
                name = (
                    getattr(getattr(u, "profile", None), "display_name", None)
                    or u.get_full_name()
                    or u.email
                )
                by_card[f.card_id].append(
                    {"name": name, "avatar_url": _user_avatar_url(u)}
                )

        for col in columns:
            for c in col.cards.all():
                c.is_following = (c.id in followed_ids)
                c.followers_preview = by_card.get(c.id, [])
                c.followers_count = counts.get(c.id, 0)

    # ============================================================
    # Render HTML
    # ============================================================
    html = render_to_string(
        "boards/partials/columns_list.html",
        {
            "columns": columns,
            "board": board,  # ✅ ESSENCIAL p/ manter a agregadora estável
        },
        request=request,
    )

    resp = JsonResponse(
        {
            "version": board.version,
            "changed": True,
            "html": html,
        }
    )
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@login_required
def unread_activity_per_card(request, board_id):
    board = get_object_or_404(Board, id=board_id)

    # segurança
    if not board.memberships.filter(user=request.user).exists():
        return JsonResponse({"error": "forbidden"}, status=403)

    cards = Card.objects.filter(
        column__board=board,
        is_deleted=False
    ).only("id")

    seen_map = {
        cs.card_id: cs.last_seen_at
        for cs in CardSeen.objects.filter(user=request.user, card__in=cards)
    }

    result = {}

    for card in cards:
        last_seen = seen_map.get(card.id, timezone.make_aware(timezone.datetime.min))

        count = (
            CardLog.objects
            .filter(card=card, created_at__gt=last_seen)
            .exclude(actor=request.user)
            .count()
        )

        if count > 0:
            result[str(card.id)] = count

    return JsonResponse({"cards": result})

# END boards/views/polling.py
