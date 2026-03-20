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

    if not board.memberships.filter(user=request.user).exists():
        return JsonResponse({"error": "forbidden"}, status=403)

    # ── Uma única query SQL raw substitui N+1 (1 query por card) ──────
    # LEFT JOIN com CardSeen para obter last_seen_at por card,
    # depois conta CardLog entries mais recentes, excluindo o próprio usuário.
    from django.db import connection
    user_id = request.user.id

    with connection.cursor() as cur:
        cur.execute("""
            SELECT c.id, COUNT(cl.id) AS cnt
            FROM boards_card c
            INNER JOIN boards_column col ON col.id = c.column_id
            LEFT JOIN boards_cardseen cs
                ON cs.card_id = c.id AND cs.user_id = %s
            LEFT JOIN boards_cardlog cl
                ON cl.card_id = c.id
               AND cl.created_at > COALESCE(cs.last_seen_at, '1970-01-01 00:00:00+00:00')
               AND (cl.actor_id IS NULL OR cl.actor_id != %s)
            WHERE col.board_id = %s
              AND c.is_deleted = 0
              AND col.is_deleted = 0
            GROUP BY c.id
            HAVING cnt > 0
        """, [user_id, user_id, board_id])
        result = {str(row[0]): row[1] for row in cur.fetchall()}

    return JsonResponse({"cards": result})

# END boards/views/polling.py
