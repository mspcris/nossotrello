# boards/views/account.py
import re

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from boards.models import UserProfile


HANDLE_RE = re.compile(r"^[a-z0-9_\.]+$")


def _get_or_create_profile(user):
    prof, _ = UserProfile.objects.get_or_create(user=user)
    return prof


def _render_account_modal(request, errors=None, ok=None, active_tab="profile"):
    prof = _get_or_create_profile(request.user)

    ctx = {
        "profile": prof,
        "active_tab": active_tab,
        "errors": errors or {},
        "ok": ok or {},
        "avatar_presets": [
            "avatar1.jpeg",
            "avatar2.png",
            "avatar3.png",
            "avatar4.png",
            "avatar5.png",
            "avatar6.png",
            "avatar7.png",
            "avatar8.png",
            "avatar9.png",
            "avatar10.png",
            "avatar11.png",
        ],
    }
    return render(request, "boards/user_modal.html", ctx)


@require_GET
@login_required
def account_modal(request):
    return _render_account_modal(request, active_tab=request.GET.get("tab") or "profile")


@require_POST
@login_required
def account_profile_update(request):
    prof = _get_or_create_profile(request.user)

    display_name = (request.POST.get("display_name") or "").strip()
    handle = (request.POST.get("handle") or "").strip().lower()

    posto = (request.POST.get("posto") or "").strip()
    setor = (request.POST.get("setor") or "").strip()
    ramal = (request.POST.get("ramal") or "").strip()
    telefone = (request.POST.get("telefone") or "").strip()

    errors = {}

    if len(display_name) > 120:
        errors["display_name"] = "Nome muito longo (máx 120)."

    if handle:
        if len(handle) > 40:
            errors["handle"] = "Handle muito longo (máx 40)."
        elif not HANDLE_RE.match(handle):
            errors["handle"] = "Use apenas letras minúsculas, números, _ ou ."
        else:
            qs = UserProfile.objects.filter(handle=handle).exclude(pk=prof.pk)
            if qs.exists():
                errors["handle"] = "Este handle já está em uso."

    if len(posto) > 120:
        errors["posto"] = "Posto muito longo (máx 120)."
    if len(setor) > 120:
        errors["setor"] = "Setor muito longo (máx 120)."
    if len(ramal) > 20:
        errors["ramal"] = "Ramal muito longo (máx 20)."
    if len(telefone) > 30:
        errors["telefone"] = "Telefone muito longo (máx 30)."

    if errors:
        return _render_account_modal(request, errors=errors, active_tab="profile")

    prof.display_name = display_name
    prof.handle = handle or None
    prof.posto = posto
    prof.setor = setor
    prof.ramal = ramal
    prof.telefone = telefone

    prof.save(update_fields=["display_name", "handle", "posto", "setor", "ramal", "telefone"])

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

    if f:
        ctype = (getattr(f, "content_type", "") or "").lower()
        if not ctype.startswith("image/"):
            errors["avatar"] = "Arquivo inválido: envie uma imagem."
        elif f.size > 5 * 1024 * 1024:
            errors["avatar"] = "Imagem muito grande (limite 5MB)."

    if errors:
        return _render_account_modal(request, errors=errors, active_tab="avatar")

    prof.avatar = f
    prof.avatar_choice = ""  # se fizer upload, limpa preset (opcional, mas consistente)
    prof.save(update_fields=["avatar", "avatar_choice"])

    resp = _render_account_modal(
        request,
        ok={"avatar": "Foto atualizada."},
        active_tab="avatar",
    )

    try:
        resp["HX-Trigger"] = f'{{"userAvatarUpdated": {{"url": "{prof.avatar.url}"}}}}'
    except Exception:
        pass

    return resp


@require_GET
@login_required
def public_profile(request, handle):
    profile = get_object_or_404(UserProfile, handle=handle)
    return render(request, "boards/public_profile.html", {"profile": profile})


from django.templatetags.static import static as static_url
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from django.templatetags.static import static as static_url

@require_POST
@login_required
def account_avatar_choice_update(request):
    prof = _get_or_create_profile(request.user)

    choice = (request.POST.get("avatar_choice") or "").strip()
    if not choice:
        return _render_account_modal(
            request,
            errors={"avatar_choice": "Selecione um avatar."},
            active_tab="avatar",
        )

    allowed = {
        "avatar1.jpeg","avatar2.png","avatar3.png","avatar4.png","avatar5.png",
        "avatar6.png","avatar7.png","avatar8.png","avatar9.png","avatar10.png","avatar11.png",
    }
    if choice not in allowed:
        return _render_account_modal(
            request,
            errors={"avatar_choice": "Avatar inválido."},
            active_tab="avatar",
        )

    prof.avatar_choice = choice

    # se escolheu preset, limpa upload para padronizar o render
    if prof.avatar:
        prof.avatar = None

    prof.save(update_fields=["avatar_choice", "avatar"])

    resp = _render_account_modal(
        request,
        ok={"avatar": "Avatar atualizado."},
        active_tab="avatar",
    )

    # DISPARA EVENTO (mesmo padrão do upload), mas com URL do static
    try:
        url = static_url(f"images/avatar/{choice}")
        resp["HX-Trigger"] = f'{{"userAvatarUpdated": {{"url": "{url}"}}}}'
    except Exception:
        pass

    return resp
