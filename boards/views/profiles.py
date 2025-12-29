# boards/views/profiles.py
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.contrib.auth import get_user_model
from types import SimpleNamespace

from ..models import BoardMembership, UserProfile

User = get_user_model()


@login_required
def user_profile_readonly_modal(request, user_id: int):
    target_user = get_object_or_404(User, id=user_id)

    # 🔒 Segurança: só permite ver quem compartilha ao menos um board
    shared = BoardMembership.objects.filter(
        user=request.user,
        board__memberships__user=target_user,
    ).exists()

    if not shared and request.user != target_user and not request.user.is_staff:
        raise Http404("Perfil não encontrado")

    profile = UserProfile.objects.filter(user=target_user).first()

    if not profile:
        profile = SimpleNamespace(
            avatar=None,
            avatar_choice=None,
            display_name="",
            handle="",
            posto="",
            setor="",
            ramal="",
            telefone="",
        )

    # ✅ Nome a exibir
    display_name = (
        profile.display_name
        or target_user.get_full_name()
        or target_user.username
        or ""
    ).strip()

    # ✅ Email SEMPRE visível
    email_display = (target_user.email or "").strip()
    if not email_display:
        # fallback legado
        email_display = (target_user.username or "").strip()

    context = {
        "profile": profile,
        "user_obj": target_user,
        "display_name": display_name,
        "email_display": email_display,
        "is_me": request.user.id == target_user.id,
    }

    return render(
        request,
        "boards/user_profile_readonly_modal.html",
        context,
    )
