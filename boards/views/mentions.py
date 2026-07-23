from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q
from django.contrib.auth import get_user_model

from boards.models import BoardMembership


@login_required
def board_mentions(request, board_id: int):
    q = (request.GET.get("q") or "").strip()

    if len(q) < 1:
        return JsonResponse([], safe=False)

    q_l = q.lower()

    member_user_ids = BoardMembership.objects.filter(
        board_id=board_id
    ).values_list("user_id", flat=True)

    User = get_user_model()

    # Busca apenas por handle — única forma de @marcar
    users = (
        User.objects
        .filter(id__in=member_user_ids)
        .select_related("profile")
        .filter(profile__handle__icontains=q_l)
        .order_by("profile__handle")[:20]
    )

    results = []
    for u in users:
        p = getattr(u, "profile", None)
        handle = (getattr(p, "handle", "") or "").strip()
        if not handle:
            continue
        display_name = (getattr(p, "display_name", "") or "").strip()
        results.append({
            "id": u.id,
            "value": handle,
            "handle": handle,
            "display_name": display_name,
            "avatar_url": (getattr(p, "avatar_url", "") if p else ""),
        })

    return JsonResponse(results, safe=False)
