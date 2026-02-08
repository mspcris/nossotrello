# boards/views/column_follow.py
import json
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from boards.models import Column, Card, CardFollow, ColumnFollow


@login_required
@require_POST
def toggle_column_follow(request, column_id):
    """
    Payload JSON:
      {
        "active": true/false,
        "include_new": true/false,
        "apply_to_existing": true/false,   # quando ativar
        "unfollow_existing": true/false    # quando desativar
      }
    """
    column = get_object_or_404(Column, id=column_id)
    board = column.board

    # leitura: manter igual ao resto do app (se board tem memberships, precisa estar nela)
    memberships_qs = board.memberships.all()
    if memberships_qs.exists() and not memberships_qs.filter(user=request.user).exists():
        return JsonResponse({"error": "Sem acesso."}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        data = {}

    active = bool(data.get("active", True))
    include_new = bool(data.get("include_new", True))
    apply_to_existing = bool(data.get("apply_to_existing", True))
    unfollow_existing = bool(data.get("unfollow_existing", True))

    # cards atuais (mesma coluna)
    # se você tiver flags is_deleted/is_archived e quiser filtrar, ajuste aqui.
    cards_qs = Card.objects.filter(column=column)

    with transaction.atomic():
        if active:
            cf, _ = ColumnFollow.objects.update_or_create(
                column=column,
                user=request.user,
                defaults={"include_new": include_new},
            )

            if apply_to_existing:
                card_ids = list(cards_qs.values_list("id", flat=True))
                if card_ids:
                    # cria CardFollow idempotente
                    CardFollow.objects.bulk_create(
                        [CardFollow(card_id=cid, user_id=request.user.id) for cid in card_ids],
                        ignore_conflicts=True,
                    )

        else:
            ColumnFollow.objects.filter(column=column, user=request.user).delete()

            if unfollow_existing:
                card_ids = list(cards_qs.values_list("id", flat=True))
                if card_ids:
                    CardFollow.objects.filter(user=request.user, card_id__in=card_ids).delete()

    # estado atual para UI
    current = ColumnFollow.objects.filter(column=column, user=request.user).first()
    is_active = bool(current)
    inc_new = bool(current.include_new) if current else False

    followed_count = CardFollow.objects.filter(
        user=request.user,
        card_id__in=cards_qs.values_list("id", flat=True),
    ).count()

    return JsonResponse(
        {
            "ok": True,
            "active": is_active,
            "include_new": inc_new,
            "followed_count": int(followed_count),
            "column_id": column.id,
        }
    )
