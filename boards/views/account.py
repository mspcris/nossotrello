# boards/views/account.py
import re

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST
from boards.models import UserProfile
from pathlib import Path
from django.conf import settings
from django.templatetags.static import static as static_url



HANDLE_RE = re.compile(r"^[a-z0-9_\.]+$")


def _get_or_create_profile(user):
    prof, _ = UserProfile.objects.get_or_create(user=user)
    return prof


def _list_avatar_presets():
    # Preferência: pasta do projeto (onde você edita os arquivos)
    # Ajuste esse path se a sua estrutura for diferente.
    base_dir = Path(getattr(settings, "BASE_DIR", Path.cwd()))
    avatar_dir = base_dir / "boards" / "static" / "images" / "avatar"

    if not avatar_dir.exists():
        # fallback: tenta STATICFILES_DIRS (comum em dev)
        for d in getattr(settings, "STATICFILES_DIRS", []):
            p = Path(d) / "images" / "avatar"
            if p.exists():
                avatar_dir = p
                break

    if not avatar_dir.exists():
        return []

    allowed_ext = {".png", ".jpg", ".jpeg", ".webp"}
    files = []
    for f in avatar_dir.iterdir():
        if f.is_file() and f.suffix.lower() in allowed_ext:
            files.append(f.name)

    # ordena para ficar previsível
    files.sort(key=lambda x: x.lower())
    return files


def _render_account_modal(request, errors=None, ok=None, active_tab="profile"):
    prof = _get_or_create_profile(request.user)

    ctx = {
        "profile": prof,
        "active_tab": active_tab,
        "errors": errors or {},
        "ok": ok or {},
        "avatar_presets": _list_avatar_presets(),
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

    errors = {}
    update_fields = []

    # ------------------------------------------------------------
    # Preferência do "label" no header (clique no email)
    # ------------------------------------------------------------
    if "preferred_identity_label" in request.POST:
        pref = (request.POST.get("preferred_identity_label") or "").strip()

        allowed = {"display_name", "email", "handle"}
        if pref and pref not in allowed:
            errors["preferred_identity_label"] = "Preferência inválida."
        else:
            prof.preferred_identity_label = pref or "display_name"
            update_fields.append("preferred_identity_label")

    # ------------------------------------------------------------
    # Campos do perfil (só valida/atualiza se vierem no POST)
    # ------------------------------------------------------------
    if "display_name" in request.POST:
        display_name = (request.POST.get("display_name") or "").strip()
        if len(display_name) > 120:
            errors["display_name"] = "Nome muito longo (máx 120)."
        else:
            prof.display_name = display_name
            update_fields.append("display_name")

    if "handle" in request.POST:
        handle = (request.POST.get("handle") or "").strip().lower()

        if handle:
            if len(handle) > 40:
                errors["handle"] = "Handle muito longo (máx 40)."
            elif not HANDLE_RE.match(handle):
                errors["handle"] = "Use apenas letras minúsculas, números, _ ou ."
            else:
                qs = UserProfile.objects.filter(handle=handle).exclude(pk=prof.pk)
                if qs.exists():
                    errors["handle"] = "Este handle já está em uso."
        # se passou validação, aplica (ou None)
        if "handle" not in errors:
            prof.handle = handle or None
            update_fields.append("handle")

    if "posto" in request.POST:
        posto = (request.POST.get("posto") or "").strip()
        if len(posto) > 120:
            errors["posto"] = "Posto muito longo (máx 120)."
        else:
            prof.posto = posto
            update_fields.append("posto")

    if "setor" in request.POST:
        setor = (request.POST.get("setor") or "").strip()
        if len(setor) > 120:
            errors["setor"] = "Setor muito longo (máx 120)."
        else:
            prof.setor = setor
            update_fields.append("setor")

    if "ramal" in request.POST:
        ramal = (request.POST.get("ramal") or "").strip()
        if len(ramal) > 20:
            errors["ramal"] = "Ramal muito longo (máx 20)."
        else:
            prof.ramal = ramal
            update_fields.append("ramal")

    if "telefone" in request.POST:
        telefone = (request.POST.get("telefone") or "").strip()
        if len(telefone) > 30:
            errors["telefone"] = "Telefone muito longo (máx 30)."
        else:
            prof.telefone = telefone
            update_fields.append("telefone")
    # ------------------------------------------------------------
    # Preferência: Atividade fixa na lateral do modal
    # ------------------------------------------------------------
    # ------------------------------------------------------------
    # CHECKBOXES: desmarcado não vem no POST -> tem que virar False
    # Regra: se o form de perfil foi submetido, sempre recalcula os flags.
    # ------------------------------------------------------------
    prof.activity_sidebar = ("activity_sidebar" in request.POST)
    prof.activity_counts  = (request.POST.get("activity_counts") == "1")

    # ... depois de activity_sidebar / activity_counts

    raw = (request.POST.get("board_col_width") or "").strip()
    try:
        colw = int(raw)
    except ValueError:
        colw = prof.board_col_width or 240

    # limita faixa para não quebrar layout
    colw = max(200, min(420, colw))

    prof.board_col_width = colw
    update_fields.append("board_col_width")



    update_fields.append("activity_sidebar")
    update_fields.append("activity_counts")



    if errors:
        return _render_account_modal(request, errors=errors, active_tab="profile")

    if update_fields:
        prof.save(update_fields=sorted(set(update_fields)))

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
    prof.avatar_choice = None
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

    # segurança 1.0: impede path traversal (ex: ../../etc/passwd)
    choice = Path(choice).name

    # ✅ whitelist dinâmica: tudo que estiver na pasta vira permitido
    allowed = set(_list_avatar_presets())
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

    # dispara evento pro header/board atualizarem sem F5
    try:
        url = static_url(f"images/avatar/{choice}")
        resp["HX-Trigger"] = f'{{"userAvatarUpdated": {{"url": "{url}"}}}}'
    except Exception:
        pass

    return resp

from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

@require_POST
@login_required
def account_identity_label_update(request):
    prof = _get_or_create_profile(request.user)

    val = (request.POST.get("preferred_identity_label") or "display_name").strip()

    allowed = {k for k, _ in UserProfile.IDENTITY_LABEL_CHOICES}
    if val not in allowed:
        return HttpResponseBadRequest("invalid preferred_identity_label")

    prof.preferred_identity_label = val
    prof.save(update_fields=["preferred_identity_label"])
    return HttpResponse("", status=204)


