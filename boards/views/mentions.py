# boards/views/mentions.py
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q

from boards.models import BoardMembership, UserProfile


@login_required
def board_mentions(request, board_id: int):
    q = (request.GET.get("q") or "").strip()

    # ✅ Regra UX: só sugere depois de @ + 1 caractere
    if len(q) < 1:
        return JsonResponse([], safe=False)

    q_l = q.lower()

    # ✅ Somente membros do board
    member_user_ids = BoardMembership.objects.filter(
        board_id=board_id
    ).values_list("user_id", flat=True)

    profiles = (
        UserProfile.objects
        .select_related("user")
        .filter(user_id__in=member_user_ids)
        .filter(
            Q(handle__icontains=q_l) |
            Q(display_name__icontains=q_l) |
            Q(user__email__icontains=q_l) |
            Q(user__first_name__icontains=q_l) |
            Q(user__last_name__icontains=q_l)
        )
        .order_by("handle", "display_name", "user__email")[:20]
    )

    results = []
    for p in profiles:
        u = p.user

        # valor amigável (o que aparece na lista)
        if p.handle:
            value = f"@{p.handle}"
        else:
            full = f"{(u.first_name or '').strip()} {(u.last_name or '').strip()}".strip()
            value = p.display_name or full or (u.email or f"user{u.id}")

        results.append({
            "id": u.id,
            "value": value,  # quill-mention usa isso como label padrão
            "email": (u.email or ""),
            "handle": (p.handle or ""),
            "display_name": (p.display_name or ""),
            "avatar_url": (p.avatar.url if getattr(p, "avatar", None) else ""),
        })

    return JsonResponse(results, safe=False)
# End of file boards/views/mentions.py
