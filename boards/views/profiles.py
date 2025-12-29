# boards/views/profiles.py
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render

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
    """
    Renderiza um modal SOMENTE-LEITURA com dados do perfil de outro usuário.

    Regras de acesso (defensivas):
    - sempre requer login
    - só permite ver perfis de usuários que compartilham pelo menos 1 board
      com o usuário atual (evita enumerar usuários por ID)
    """
    target = get_object_or_404(
        UserProfile.objects.select_related("user"),
        user_id=user_id,
    )

    shared = BoardMembership.objects.filter(
        user=request.user,
        board__memberships__user_id=target.user_id,
    ).exists()

    if not shared and request.user.id != target.user_id and not request.user.is_staff:
        raise Http404("Perfil não encontrado")

    u = target.user
    display_name = (target.display_name or u.get_full_name() or u.get_username() or "").strip()

    ctx = {
        "profile": target,
        "user_obj": u,
        "display_name": display_name,
        "is_me": request.user.id == target.user_id,
    }

    return render(request, "boards/user_profile_readonly_modal.html", ctx)
