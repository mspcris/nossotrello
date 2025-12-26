# boards/views/profiles.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from ..models import UserProfile


@login_required
def public_profile(request, handle: str):
    handle = (handle or "").strip().lstrip("@")
    prof = get_object_or_404(
        UserProfile.objects.select_related("user"),
        handle__iexact=handle,
    )

    u = prof.user
    display_name = (prof.display_name or u.get_full_name() or u.get_username() or "").strip()

    return render(
        request,
        "accounts/public_profile.html",  # usa o template que você já criou
        {"profile": prof, "user_obj": u, "display_name": display_name},
    )
