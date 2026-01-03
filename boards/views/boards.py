# boards/views/boards.py

import os
import uuid
import requests


from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import escape
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.urls import reverse
from django.db.models import Prefetch
from types import SimpleNamespace


from .helpers import (
    DEFAULT_WALLPAPER_FILENAME,
    _actor_label,
    _log_board,
    _log_card,
    get_or_create_user_default_organization,
)

from .helpers import Board, Column, Card, BoardMembership, Organization


# ======================================================================
# HOME (lista de boards)
# ======================================================================

def index(request):
    if request.user.is_authenticated:
        qs = BoardMembership.objects.filter(
            user=request.user,
            board__is_deleted=False,
        ).select_related("board")

        owned_ids = list(qs.filter(role=BoardMembership.Role.OWNER).values_list("board_id", flat=True))
        shared_ids = list(qs.exclude(role=BoardMembership.Role.OWNER).values_list("board_id", flat=True))

        owned_boards = (
            Board.objects.filter(id__in=owned_ids, is_deleted=False)
            .distinct()
            .order_by("-created_at")
        )

        shared_boards = (
            Board.objects.filter(id__in=shared_ids, is_deleted=False)
            .distinct()
            .order_by("-created_at")
        )

        owner_by_board = {}
        if shared_ids:
            owner_memberships = (
                BoardMembership.objects.filter(
                    board_id__in=shared_ids,
                    role=BoardMembership.Role.OWNER,
                )
                .select_related("user")
            )
            for m in owner_memberships:
                if m.board_id not in owner_by_board:
                    owner_by_board[m.board_id] = m.user

        for b in shared_boards:
            u = owner_by_board.get(b.id)
            b.owner_email = (u.email or u.get_username()) if u else ""

    else:
        owned_boards = Board.objects.filter(is_deleted=False).order_by("-created_at")
        shared_boards = Board.objects.none()

    home_bg_image = None
    if request.user.is_authenticated:
        org = get_or_create_user_default_organization(request.user)
        filename = (getattr(org, "home_wallpaper_filename", "") or "").strip()
        if filename:
            home_bg_image = filename

    return render(
        request,
        "boards/index.html",
        {
            "owned_boards": owned_boards,
            "shared_boards": shared_boards,
            "home_bg": True,
            "home_bg_image": home_bg_image,
        },
    )


# ======================================================================
# DETALHE DE UM BOARD
# ======================================================================

def board_detail(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    memberships_qs = board.memberships.select_related("user")

    my_membership = None
    can_leave_board = False
    can_share_board = False
    can_edit = False

    if memberships_qs.exists():
        if not request.user.is_authenticated:
            return HttpResponse("Você não tem acesso a este quadro.", status=403)

        my_membership = memberships_qs.filter(user=request.user).first()
        if not my_membership:
            return HttpResponse("Você não tem acesso a este quadro.", status=403)

        can_share_board = (my_membership.role == BoardMembership.Role.OWNER)
        can_edit = my_membership.role in {
            BoardMembership.Role.OWNER,
            BoardMembership.Role.EDITOR,
        }

        if my_membership.role != BoardMembership.Role.OWNER:
            can_leave_board = True
        else:
            owners_count = memberships_qs.filter(role=BoardMembership.Role.OWNER).count()
            can_leave_board = owners_count > 1
    else:
        if request.user.is_authenticated and (board.created_by_id == request.user.id or request.user.is_staff):
            can_share_board = True
            can_edit = True  # legado: criador/staff edita

    # ✅ SEMPRE definir columns (fora do if/else)
    columns = (
        board.columns.filter(is_deleted=False)
        .order_by("position")
        .prefetch_related(
            Prefetch(
                "cards",
                queryset=Card.objects.filter(is_deleted=False).order_by("position"),
            )
        )
    )

    # =========================
    # BOARD MEMBERS (para a barra de avatares)
    # =========================
    memberships = board.memberships.select_related("user").order_by("role", "user__username")

    board_members = []
    for m in memberships:
        u = m.user
        try:
            _ = u.profile  # tenta acessar
        except Exception:
            # fallback seguro só para o template
            u._state.fields_cache["profile"] = SimpleNamespace(avatar=None)

        board_members.append(u)

    return render(
        request,
        "boards/board_detail.html",
        {
            "board": board,
            "columns": columns,
            "board_members": board_members,
            "my_membership": my_membership,
            "can_leave_board": can_leave_board,
            "can_share_board": can_share_board,
            "can_edit": can_edit,
        },
    )


# ======================================================================
# SAIR DA BOARD
# ======================================================================

@require_POST
def board_leave(request, board_id):
    if not request.user.is_authenticated:
        return HttpResponse("Login necessário.", status=401)

    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    membership = BoardMembership.objects.filter(board=board, user=request.user).first()
    if not membership:
        return HttpResponse("Você não tem acesso a este quadro.", status=403)

    if membership.role == BoardMembership.Role.OWNER:
        owners_count = BoardMembership.objects.filter(board=board, role=BoardMembership.Role.OWNER).count()
        if owners_count <= 1:
            return HttpResponse("Você é o último DONO do quadro e não pode sair.", status=400)

    actor = _actor_label(request)
    membership.delete()

    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> saiu do quadro <strong>{escape(board.name)}</strong>.</p>",
    )

    redirect_url = reverse("boards:boards_index")

    if request.headers.get("HX-Request") == "true":
        resp = HttpResponse("")
        resp["HX-Redirect"] = redirect_url
        return resp

    return redirect(redirect_url)


# ======================================================================
# ADICIONAR BOARD
# ======================================================================

def add_board(request):
    from ..forms import BoardForm  # evita circular

    if request.method == "POST":
        form = BoardForm(request.POST)
        if not form.is_valid():
            return HttpResponse("Erro ao criar board", status=400)

        board = form.save(commit=False)

        if request.user.is_authenticated:
            board.created_by = request.user
            board.organization = get_or_create_user_default_organization(request.user)

        board.save()

        if request.user.is_authenticated:
            BoardMembership.objects.get_or_create(
                board=board,
                user=request.user,
                defaults={"role": BoardMembership.Role.OWNER},
            )

        actor = _actor_label(request)
        _log_board(
            board,
            request,
            f"<p><strong>{actor}</strong> criou o quadro <strong>{escape(board.name)}</strong>.</p>",
        )

        return HttpResponse(f'<script>window.location.href="/board/{board.id}/"</script>')

    return render(request, "boards/partials/add_board_form.html", {"form": BoardForm()})


# ======================================================================
# SOFT DELETE DE BOARD
# ======================================================================

def delete_board(request, board_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido.")

    try:
        board = Board.objects.get(id=board_id, is_deleted=False)
    except Board.DoesNotExist:
        return HttpResponseBadRequest("Quadro não encontrado.")

    actor = _actor_label(request)

    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> excluiu (soft delete) o quadro <strong>{escape(board.name)}</strong>.</p>",
    )

    now = timezone.now()
    board.is_deleted = True
    board.deleted_at = now
    board.save(update_fields=["is_deleted", "deleted_at"])

    Column.objects.filter(board=board, is_deleted=False).update(is_deleted=True, deleted_at=now)
    Card.objects.filter(column__board=board, is_deleted=False).update(is_deleted=True, deleted_at=now)

    return HttpResponse("")


# ======================================================================
# IMAGEM PRINCIPAL DO BOARD
# ======================================================================

def update_board_image(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    actor = _actor_label(request)

    if request.method == "GET":
        return render(request, "boards/partials/board_image_form.html", {"board": board})

    if request.method == "POST":
        if "image" in request.FILES and request.FILES["image"]:
            board.image = request.FILES["image"]
            board.save(update_fields=["image"])
            _log_board(board, request, f"<p><strong>{actor}</strong> atualizou a imagem principal do quadro.</p>")
            return HttpResponse('<script>location.reload()</script>')

        url = (request.POST.get("image_url") or "").strip()
        if url:
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    filename = url.split("/")[-1] or "board.jpg"
                    board.image.save(filename, ContentFile(r.content))
                    _log_board(board, request, f"<p><strong>{actor}</strong> atualizou a imagem principal do quadro via URL.</p>")
                    return HttpResponse('<script>location.reload()</script>')
            except Exception:
                pass

        return HttpResponse("<div class='text-red-600'>Erro ao carregar imagem.</div>", status=400)


@require_POST
def remove_board_image(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    actor = _actor_label(request)

    if board.image:
        board.image.delete(save=False)
        board.image = None
        board.save(update_fields=["image"])
        _log_board(board, request, f"<p><strong>{actor}</strong> removeu a imagem principal do quadro.</p>")

    return HttpResponse('<script>location.reload()</script>')


# ======================================================================
# RENOMEAR BOARD
# ======================================================================

@require_POST
def rename_board(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    actor = _actor_label(request)

    old_name = board.name
    name = request.POST.get("name", "").strip()
    if not name:
        return HttpResponse("Nome inválido", status=400)

    board.name = name
    board.save(update_fields=["name"])

    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> renomeou o quadro de <strong>{escape(old_name)}</strong> para <strong>{escape(name)}</strong>.</p>",
    )

    return HttpResponse("OK", status=200)


# ======================================================================
# WALLPAPER DO BOARD + CSS
# ======================================================================

def _default_wallpaper_url():
    from django.templatetags.static import static as static_url

    rel_static = f"images/{DEFAULT_WALLPAPER_FILENAME}"

    try:
        from django.contrib.staticfiles import finders
        found = finders.find(rel_static)
        if found:
            return static_url(rel_static)
    except Exception:
        pass

    try:
        rel_media = f"home_wallpapers/{DEFAULT_WALLPAPER_FILENAME}"
        if default_storage.exists(rel_media):
            return default_storage.url(rel_media)
    except Exception:
        pass

    return static_url(rel_static)


def update_board_wallpaper(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    actor = _actor_label(request)

    if request.method == "GET":
        return render(request, "boards/partials/wallpaper_form.html", {"board": board})

    if request.method == "POST":
        if "image" in request.FILES and request.FILES["image"]:
            board.background_image = request.FILES["image"]
            board.background_url = ""
            board.save(update_fields=["background_image", "background_url"])
            _log_board(board, request, f"<p><strong>{actor}</strong> atualizou o wallpaper do quadro (upload).</p>")
            return HttpResponse('<script>location.reload()</script>')

        url = (request.POST.get("image_url") or "").strip()
        if url:
            board.background_url = url
            board.background_image = None
            board.save(update_fields=["background_image", "background_url"])
            _log_board(board, request, f"<p><strong>{actor}</strong> atualizou o wallpaper do quadro (URL).</p>")
            return HttpResponse('<script>location.reload()</script>')

        return HttpResponse("Erro", status=400)


def board_wallpaper_css(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    if getattr(board, "background_image", None):
        img_url = board.background_image.url
    elif (getattr(board, "background_url", "") or "").strip():
        img_url = escape((getattr(board, "background_url", "") or "").strip())
    else:
        img_url = _default_wallpaper_url()

    css = f"""
    body {{
        background-image: url('{img_url}') !important;
        background-size: cover !important;
        background-position: center !important;
        background-attachment: fixed !important;
        background-repeat: no-repeat !important;
        background-color: transparent !important;
    }}
    """
    resp = HttpResponse(css, content_type="text/css")
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp


@require_POST
def remove_board_wallpaper(request, board_id):
    board = get_object_or_404(Board, id=board_id)
    actor = _actor_label(request)

    if board.background_image:
        board.background_image.delete(save=False)
        board.background_image = None

    board.background_url = ""
    board.save(update_fields=["background_image", "background_url"])

    _log_board(board, request, f"<p><strong>{actor}</strong> removeu o wallpaper do quadro.</p>")
    return HttpResponse('<script>location.reload()</script>')


# ======================================================================
# HOME WALLPAPER (Organization.home_wallpaper_filename) + upload/remoção
# ======================================================================

def home_wallpaper_css(request):
    url = _default_wallpaper_url()

    if request.user.is_authenticated:
        org = get_or_create_user_default_organization(request.user)
        filename = (getattr(org, "home_wallpaper_filename", "") or "").strip()

        if filename and filename != DEFAULT_WALLPAPER_FILENAME:
            rel = f"home_wallpapers/{filename}"
            try:
                if default_storage.exists(rel):
                    url = default_storage.url(rel)
            except Exception:
                pass

    css = f"""
    body {{
        background-image: url('{url}') !important;
        background-size: cover !important;
        background-position: center !important;
        background-attachment: fixed !important;
        background-repeat: no-repeat !important;
        background-color: transparent !important;
    }}
    """
    resp = HttpResponse(css, content_type="text/css")
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp["Pragma"] = "no-cache"
    resp["Expires"] = "0"
    return resp


def update_home_wallpaper(request):
    if request.method == "GET":
        return render(request, "boards/partials/home_wallpaper_form.html", {})

    if not request.user.is_authenticated:
        return HttpResponse("Login necessário.", status=401)

    org = get_or_create_user_default_organization(request.user)
    if not org:
        return HttpResponse("Organização não encontrada.", status=400)

    actor = _actor_label(request)

    def _anchor_board_for_org(_org):
        try:
            return Board.objects.filter(organization=_org, is_deleted=False).order_by("-id").first()
        except Exception:
            return None

    if "image" in request.FILES and request.FILES["image"]:
        file = request.FILES["image"]
        ext = os.path.splitext(file.name or "")[1] or ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
        rel = f"home_wallpapers/{filename}"

        default_storage.save(rel, file)

        old = (getattr(org, "home_wallpaper_filename", "") or "").strip()
        if old and old != DEFAULT_WALLPAPER_FILENAME:
            old_rel = f"home_wallpapers/{old}"
            try:
                if default_storage.exists(old_rel):
                    default_storage.delete(old_rel)
            except Exception:
                pass

        org.home_wallpaper_filename = filename
        org.save(update_fields=["home_wallpaper_filename"])

        board_anchor = _anchor_board_for_org(org)
        if board_anchor:
            _log_board(board_anchor, request, f"<p><strong>{actor}</strong> atualizou o wallpaper da HOME (upload).</p>")

        return HttpResponse('<script>location.reload()</script>')

    url = (request.POST.get("image_url") or "").strip()
    if url:
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200 and r.content:
                parsed_ext = os.path.splitext((url.split("?")[0] or "").strip())[1] or ".jpg"
                filename = f"{uuid.uuid4().hex}{parsed_ext}"
                rel = f"home_wallpapers/{filename}"

                default_storage.save(rel, ContentFile(r.content))

                old = (getattr(org, "home_wallpaper_filename", "") or "").strip()
                if old and old != DEFAULT_WALLPAPER_FILENAME:
                    old_rel = f"home_wallpapers/{old}"
                    try:
                        if default_storage.exists(old_rel):
                            default_storage.delete(old_rel)
                    except Exception:
                        pass

                org.home_wallpaper_filename = filename
                org.save(update_fields=["home_wallpaper_filename"])

                board_anchor = _anchor_board_for_org(org)
                if board_anchor:
                    _log_board(board_anchor, request, f"<p><strong>{actor}</strong> atualizou o wallpaper da HOME (URL).</p>")

                return HttpResponse('<script>location.reload()</script>')
        except Exception:
            pass

    return HttpResponse("Erro ao importar imagem", status=400)


@require_POST
def remove_home_wallpaper(request):
    if not request.user.is_authenticated:
        return HttpResponse("Login necessário.", status=401)

    org = get_or_create_user_default_organization(request.user)
    if not org:
        return HttpResponse("Organização não encontrada.", status=400)

    actor = _actor_label(request)

    filename = (getattr(org, "home_wallpaper_filename", "") or "").strip()

    if filename and filename != DEFAULT_WALLPAPER_FILENAME:
        rel = f"home_wallpapers/{filename}"
        try:
            if default_storage.exists(rel):
                default_storage.delete(rel)
        except Exception:
            pass

    org.home_wallpaper_filename = DEFAULT_WALLPAPER_FILENAME
    org.save(update_fields=["home_wallpaper_filename"])

    try:
        board_anchor = Board.objects.filter(organization=org, is_deleted=False).order_by("-id").first()
        if board_anchor:
            _log_board(board_anchor, request, f"<p><strong>{actor}</strong> removeu o wallpaper da HOME.</p>")
    except Exception:
        pass

    return HttpResponse('<script>location.reload()</script>')


# ======================================================================
# COMPARTILHAR BOARD
# ======================================================================

@require_http_methods(["GET", "POST"])
def board_share(request, board_id):
    if not request.user.is_authenticated:
        return HttpResponse("Login necessário.", status=401)

    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    memberships_qs = board.memberships.select_related("user")
    if memberships_qs.exists():
        if not memberships_qs.filter(user=request.user, role=BoardMembership.Role.OWNER).exists():
            return HttpResponse("Você não tem permissão para compartilhar este quadro.", status=403)
    else:
        if board.created_by_id != request.user.id and not request.user.is_staff:
            return HttpResponse("Você não tem permissão para compartilhar este quadro.", status=403)

    memberships = board.memberships.select_related("user").order_by("role", "user__username")

    if request.method == "GET":
        return render(request, "boards/partials/board_share_form.html", {"board": board, "memberships": memberships})

    actor = _actor_label(request)

    identifier = (request.POST.get("identifier") or "").strip()
    role = (request.POST.get("role") or BoardMembership.Role.VIEWER).strip().lower()

    if role not in {
        BoardMembership.Role.OWNER,
        BoardMembership.Role.EDITOR,
        BoardMembership.Role.VIEWER,
    }:
        role = BoardMembership.Role.VIEWER

    if not identifier:
        return render(
            request,
            "boards/partials/board_share_form.html",
            {"board": board, "memberships": memberships, "msg_error": "Informe e-mail ou username."},
            status=400,
        )

    User = get_user_model()
    target = User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier)).first()

    if not target:
        return render(
            request,
            "boards/partials/board_share_form.html",
            {"board": board, "memberships": memberships, "msg_error": "Usuário não encontrado."},
            status=404,
        )

    if target.id == request.user.id:
        return render(
            request,
            "boards/partials/board_share_form.html",
            {"board": board, "memberships": memberships, "msg_error": "Você já é membro deste quadro."},
            status=400,
        )

    obj, created = BoardMembership.objects.get_or_create(
        board=board,
        user=target,
        defaults={"role": role},
    )

    if not created and obj.role != role:
        obj.role = role
        obj.save(update_fields=["role"])

    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> compartilhou o quadro com <strong>{escape(target.email or target.get_username())}</strong> como <strong>{escape(role)}</strong>.</p>",
    )

    memberships = board.memberships.select_related("user").order_by("role", "user__username")

    return render(
        request,
        "boards/partials/board_share_form.html",
        {
            "board": board,
            "memberships": memberships,
            "msg_success": f"Compartilhado com {escape(target.get_username())} ({escape(target.email or '-')}).",
        },
        status=200,
    )


@require_POST
def board_share_remove(request, board_id, user_id):
    if not request.user.is_authenticated:
        return HttpResponse("Login necessário.", status=401)

    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    memberships_qs = board.memberships.select_related("user")
    if memberships_qs.exists():
        if not memberships_qs.filter(user=request.user, role=BoardMembership.Role.OWNER).exists():
            return HttpResponse("Você não tem permissão para remover acessos deste quadro.", status=403)
    else:
        if board.created_by_id != request.user.id and not request.user.is_staff:
            return HttpResponse("Você não tem permissão para remover acessos deste quadro.", status=403)

    actor = _actor_label(request)

    membership = BoardMembership.objects.filter(board=board, user_id=user_id).select_related("user").first()
    memberships = board.memberships.select_related("user").order_by("role", "user__username")

    if not membership:
        return render(
            request,
            "boards/partials/board_share_form.html",
            {"board": board, "memberships": memberships, "msg_error": "Acesso não encontrado."},
            status=404,
        )

    if membership.role == BoardMembership.Role.OWNER:
        owners_count = board.memberships.filter(role=BoardMembership.Role.OWNER).count()
        if owners_count <= 1:
            return render(
                request,
                "boards/partials/board_share_form.html",
                {"board": board, "memberships": memberships, "msg_error": "Não é possível remover o último DONO do quadro."},
                status=400,
            )

    removed_user = membership.user
    membership.delete()

    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> removeu o acesso de <strong>{escape(removed_user.email or removed_user.get_username())}</strong> do quadro.</p>",
    )

    memberships = board.memberships.select_related("user").order_by("role", "user__username")

    return render(
        request,
        "boards/partials/board_share_form.html",
        {"board": board, "memberships": memberships, "msg_success": f"Acesso removido: {escape(removed_user.get_username())}."},
        status=200,
    )


# ======================================================================
# USERS
# ======================================================================

@staff_member_required
def create_user(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        email = (request.POST.get("email") or "").strip()

        if form.is_valid():
            user = form.save(commit=False)
            if email:
                user.email = email
            user.save()
            return redirect("boards:boards_index")
    else:
        form = UserCreationForm()

    return render(request, "boards/create_user.html", {"form": form})



@login_required
def board_poll(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    client_version = int(request.GET.get("v", 0))

    if board.version == client_version:
        return JsonResponse({"changed": False})

    # 🔴 ISSO É O QUE FALTAVA
    columns = (
        board.columns
        .filter(is_deleted=False)
        .order_by("position")
        .prefetch_related(
            "cards",
        )
    )

    html = render_to_string(
        "boards/partials/columns_block.html",  # ⬅️ veja abaixo
        {"columns": columns},
        request=request,
    )

    return JsonResponse({
        "changed": True,
        "version": board.version,
        "html": html,
    })


@login_required
def toggle_aggregator_column(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    board.show_aggregator_column = not board.show_aggregator_column
    board.save(update_fields=["show_aggregator_column"])

    columns = (
        board.columns
        .filter(is_deleted=False)
        .order_by("position")
        .prefetch_related(
            Prefetch(
                "cards",
                queryset=Card.objects.filter(is_deleted=False).order_by("position"),
            )
        )
    )

    return render(
        request,
        "boards/partials/aggregator_toggle_response.html",
        {
            "board": board,
            "columns": columns,
        },
    )

