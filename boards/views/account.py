# boards/views/account.py
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from boards.models import UserProfile


HANDLE_RE = re.compile(r"^[a-z0-9_\.]+$")


def _get_or_create_profile(user):
    prof, _ = UserProfile.objects.get_or_create(user=user)
    return prof


def _render_account_modal(request, errors=None, ok=None, active_tab="profile"):
    user = request.user
    prof = _get_or_create_profile(user)

    ctx = {
        "profile": prof,
        "active_tab": active_tab,
        "errors": errors or {},
        "ok": ok or {},
    }
    return render(request, "boards/user_modal.html", ctx)


@require_GET
@login_required
def account_modal(request):
    return _render_account_modal(request, active_tab=request.GET.get("tab") or "profile")


@require_POST
@login_required
def account_profile_update(request):
    user = request.user
    prof = _get_or_create_profile(user)

    display_name = (request.POST.get("display_name") or "").strip()
    handle = (request.POST.get("handle") or "").strip().lower()

    errors = {}

    # display_name é livre (só tamanho)
    if len(display_name) > 120:
        errors["display_name"] = "Nome muito longo (máx 120)."

    # handle: opcional, mas se vier tem que ser válido e único
    if handle:
        if len(handle) > 40:
            errors["handle"] = "Handle muito longo (máx 40)."
        elif not HANDLE_RE.match(handle):
            errors["handle"] = "Use apenas letras minúsculas, números, _ ou ."
        else:
            # único (exclui o próprio profile)
            qs = UserProfile.objects.filter(handle=handle).exclude(pk=prof.pk)
            if qs.exists():
                errors["handle"] = "Este handle já está em uso."

    if errors:
        return _render_account_modal(request, errors=errors, active_tab="profile")

    prof.display_name = display_name
    prof.handle = handle or None
    prof.save(update_fields=["display_name", "handle"])

    return _render_account_modal(
        request,
        ok={"profile": "Perfil atualizado."},
        active_tab="profile",
    )


@require_POST
@login_required
def account_password_change(request):
    user = request.user
    current = request.POST.get("current_password") or ""
    new1 = request.POST.get("new_password1") or ""
    new2 = request.POST.get("new_password2") or ""

    errors = {}

    if not user.check_password(current):
        errors["current_password"] = "Senha atual incorreta."

    if not new1 or len(new1) < 8:
        errors["new_password1"] = "A nova senha deve ter pelo menos 8 caracteres."

    if new1 != new2:
        errors["new_password2"] = "As senhas não conferem."

    if errors:
        return _render_account_modal(request, errors=errors, active_tab="password")

    user.set_password(new1)
    user.save(update_fields=["password"])

    # mantém o usuário logado após trocar a senha
    from django.contrib.auth import update_session_auth_hash
    update_session_auth_hash(request, user)

    return _render_account_modal(
        request,
        ok={"password": "Senha alterada com sucesso."},
        active_tab="password",
    )


@require_POST
@login_required
def account_avatar_update(request):
    prof = _get_or_create_profile(request.user)

    f = request.FILES.get("avatar")
    errors = {}

    if not f:
        errors["avatar"] = "Selecione uma imagem."

    # validações defensivas (sem “reinventar roda”, mas sem template do Django)
    if f:
        ctype = (getattr(f, "content_type", "") or "").lower()
        if not ctype.startswith("image/"):
            errors["avatar"] = "Arquivo inválido: envie uma imagem."
        elif f.size > 5 * 1024 * 1024:
            errors["avatar"] = "Imagem muito grande (limite 5MB)."

    if errors:
        return _render_account_modal(request, errors=errors, active_tab="avatar")

    prof.avatar = f
    prof.save(update_fields=["avatar"])

    resp = _render_account_modal(
        request,
        ok={"avatar": "Foto atualizada."},
        active_tab="avatar",
    )

    # dispara evento HTMX para o front atualizar a bolinha no header sem reload
    try:
        resp["HX-Trigger"] = f'{{"userAvatarUpdated": {{"url": "{prof.avatar.url}"}}}}'
    except Exception:
        pass

    return resp
