"""Página do usuário: ver minhas próprias publicações em análise/bloqueadas."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from boards.models import SocialPost, ModerationCase, BanLog


@login_required
def my_under_review(request):
    """Lista posts do usuário que NÃO estão clean + suas punições recebidas."""
    posts = list(
        SocialPost.objects
        .filter(user=request.user)
        .exclude(moderation_status=SocialPost.MOD_CLEAN)
        .order_by("-created_at")[:50]
    )
    cases = list(
        ModerationCase.objects
        .filter(author=request.user)
        .order_by("-created_at")[:50]
    )
    ban_logs = list(
        BanLog.objects
        .filter(user=request.user)
        .order_by("-applied_at")[:50]
    )
    return render(request, "boards/social_my_under_review.html", {
        "posts": posts,
        "cases": cases,
        "ban_logs": ban_logs,
    })
