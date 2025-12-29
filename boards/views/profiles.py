# boards/views/profiles.py
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from types import SimpleNamespace
from django.contrib.auth.models import User  # se estiver usando o User padrão

from ..models import BoardMembership, UserProfile


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
        "boards/public_profile.html",  # usa o template que você já criou
        {"profile": prof, "user_obj": u, "display_name": display_name},
    )



@login_required
def user_profile_readonly_modal(request, user_id: int):
    target_user = get_object_or_404(User, id=user_id)

    # evita enumerar usuários por ID: só vê quem compartilha board
    shared = BoardMembership.objects.filter(
        user=request.user,
        board__memberships__user_id=target_user.id,
    ).exists()

    if not shared and request.user.id != target_user.id and not request.user.is_staff:
        raise Http404("Perfil não encontrado")

    profile = UserProfile.objects.filter(user=target_user).first()
    if not profile:
        profile = SimpleNamespace(
            avatar=None,
            display_name="",
            handle="",
            posto="",
            setor="",
            ramal="",
            telefone="",
        )

    display_name = (getattr(profile, "display_name", "") or target_user.get_full_name() or "").strip()
    if not display_name:
        # fallback forte: username > email
        display_name = (target_user.get_username() or target_user.email or "").strip()

    ctx = {
        "profile": profile,
        "user_obj": target_user,
        "display_name": display_name,
        "email": (target_user.email or "").strip(),
        "username": (target_user.get_username() or "").strip(),
        "is_me": request.user.id == target_user.id,
    }
    return render(request, "boards/user_profile_readonly_modal.html", ctx)
