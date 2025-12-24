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

    users = (
        User.objects
        .filter(id__in=member_user_ids)
        .select_related("profile")  # ✅ aqui é "profile"
        .filter(
            Q(email__icontains=q_l) |
            Q(first_name__icontains=q_l) |
            Q(last_name__icontains=q_l) |
            Q(profile__handle__icontains=q_l) |         # ✅
            Q(profile__display_name__icontains=q_l)     # ✅
        )
        .order_by("profile__handle", "profile__display_name", "email")[:20]
    )

    results = []
    for u in users:
        p = getattr(u, "profile", None)  # ✅

        handle = (getattr(p, "handle", "") or "").strip()
        display_name = (getattr(p, "display_name", "") or "").strip()

        # value SEM '@' (evita @@ no dropdown do Quill)
        if handle:
            value = handle
        else:
            full = f"{(u.first_name or '').strip()} {(u.last_name or '').strip()}".strip()
            value = display_name or full or (u.email or f"user{u.id}")

        results.append({
            "id": u.id,
            "value": value,
            "email": (u.email or ""),
            "handle": handle,
            "display_name": display_name,
            "avatar_url": (p.avatar.url if (p and getattr(p, "avatar", None)) else ""),
        })

    return JsonResponse(results, safe=False)
