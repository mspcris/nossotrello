# boards/views/mention.py
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import JsonResponse

@login_required
def board_mentions(request, board_id: int):
    q = (request.GET.get("q") or "").strip()

    User = get_user_model()

    qs = User.objects.filter(is_active=True)

    if q:
        qs = qs.filter(
            Q(username__icontains=q) |
            Q(email__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        )

    qs = qs.order_by("first_name", "username")[:20]

    results = []
    for u in qs:
        name = (f"{u.first_name} {u.last_name}").strip() or (u.username or u.email)
        results.append({"id": u.id, "value": name, "email": u.email})

    return JsonResponse(results, safe=False)
