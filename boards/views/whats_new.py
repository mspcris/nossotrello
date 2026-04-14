# boards/views/whats_new.py
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from boards.models import WhatsNewItem, UserProfile


def _unseen_qs(profile):
    qs = WhatsNewItem.objects.filter(is_published=True)
    if profile.last_whatsnew_seen_at:
        qs = qs.filter(published_at__gt=profile.last_whatsnew_seen_at)
    return qs


@login_required
def whats_new_panel(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    items = list(
        WhatsNewItem.objects.filter(is_published=True).order_by("-published_at")[:30]
    )
    unseen_ids = set(
        _unseen_qs(profile).values_list("id", flat=True)
    )
    return render(
        request,
        "boards/whats_new_panel.html",
        {"items": items, "unseen_ids": unseen_ids},
    )


@login_required
@require_POST
def whats_new_mark_seen(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.last_whatsnew_seen_at = timezone.now()
    profile.save(update_fields=["last_whatsnew_seen_at"])
    return JsonResponse({"ok": True, "unseen": 0})
