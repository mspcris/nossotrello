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
from django.db.models import Max
from django.db.models.functions import Coalesce
from ..models import CardLog, BoardActivityReadState
from django.db import models
from django.db.models import Prefetch

from django.urls import reverse
from types import SimpleNamespace
from ..models import BoardGroup, BoardGroupItem
from django.db import transaction

import hashlib
import random

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail





from .helpers import (
    DEFAULT_WALLPAPER_FILENAME,
    _actor_label,
    _log_board,
    _log_card,
    get_or_create_user_default_organization,
)

from .helpers import Board, Column, Card, BoardMembership, Organization


def _get_home_org(request):
    if not request.user.is_authenticated:
        return None
    return get_or_create_user_default_organization(request.user)

def _get_or_create_favorites_group(user, org):
    obj = BoardGroup.objects.filter(user=user, organization=org, is_favorites=True).first()
    if obj:
        return obj
    # position 0: sempre topo
    return BoardGroup.objects.create(
        user=user,
        organization=org,
        name="Favoritos",
        position=0,
        is_favorites=True,
    )

def _user_accessible_board_ids(user):
    qs = BoardMembership.objects.filter(user=user, board__is_deleted=False)
    return list(qs.values_list("board_id", flat=True))



def _transfer_cache_key(board_id: int, from_user_id: int) -> str:
    return f"board:{int(board_id)}:transfer_owner:from:{int(from_user_id)}"

def _normalize_email(s: str) -> str:
    return (s or "").strip().lower()

def _hash_transfer_code(code: str) -> str:
    """
    Hash simples para não persistir o código puro.
    Usa SECRET_KEY como "pepper".
    """
    raw = f"{settings.SECRET_KEY}::{code}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def _gen_6digit_code() -> str:
    return f"{random.randint(0, 999999):06d}"

# ======================================================================
# HOME (lista de boards)
# ======================================================================

def index(request):
    if request.user.is_authenticated:
        qs = BoardMembership.objects.filter(
            user=request.user,
            board__is_deleted=False,
        ).select_related("board")
        favorites_group = None
        favorite_ids = set()
        groups_data = []

        owned_ids = list(qs.filter(role=BoardMembership.Role.OWNER).values_list("board_id", flat=True))
        shared_ids = list(qs.exclude(role=BoardMembership.Role.OWNER).values_list("board_id", flat=True))

        org = _get_home_org(request)
        favorites_group = _get_or_create_favorites_group(request.user, org)

        groups_qs = BoardGroup.objects.filter(
            user=request.user,
            organization=org,
        ).order_by("position", "id")

        # separa favoritos
        custom_groups = groups_qs.filter(is_favorites=False)

        accessible_ids = set(_user_accessible_board_ids(request.user))

        # pré-carrega itens e filtra boards que o user ainda acessa
        groups_data = []
        favorite_ids = set()

        # favoritos primeiro
        fav_items = (
            BoardGroupItem.objects.filter(group=favorites_group, board_id__in=accessible_ids)
            .select_related("board")
            .order_by("position", "id")
        )
        for it in fav_items:
            favorite_ids.add(it.board_id)

        # custom groups
        for g in custom_groups:
            items = (
                BoardGroupItem.objects.filter(group=g, board_id__in=accessible_ids)
                .select_related("board")
                .order_by("position", "id")
            )
            groups_data.append({"group": g, "items": items})


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
        "favorites_group": favorites_group,
        "favorites_group_items": fav_items,   
        "favorite_board_ids": list(favorite_ids),
        "custom_groups": groups_data,
        "owned_boards": owned_boards,
        "shared_boards": shared_boards,
        "home_bg": True,
        "home_bg_image": home_bg_image,
    },
)




@require_POST
@login_required
@transaction.atomic
def home_group_create(request):
    org = _get_home_org(request)
    name = (request.POST.get("name") or "").strip() or "Novo agrupamento"

    # Mesma “scope” usada no create (user + org + somente grupos customizados)
    qs = BoardGroup.objects.filter(
        user=request.user,
        organization=org,
        is_favorites=False,
    )

    # Próxima posição segura (evita NULL e respeita CHECK constraint do SQLite)
    next_pos = qs.aggregate(p=Coalesce(Max("position"), 0))["p"] + 1
    next_pos = int(next_pos)

    g = BoardGroup.objects.create(
        user=request.user,
        organization=org,
        name=name,
        position=next_pos,
        is_favorites=False,
    )

    html = render_to_string(
        "boards/partials/home_group_block.html",
        {"g": g, "items": [], "favorite_board_ids": []},
        request=request,
    )
    return HttpResponse(html)


@require_POST
@login_required
def home_group_rename(request, group_id):
    org = _get_home_org(request)
    g = get_object_or_404(BoardGroup, id=group_id, user=request.user, organization=org, is_favorites=False)

    name = (request.POST.get("name") or "").strip()
    if not name:
        return HttpResponse("Nome inválido", status=400)

    g.name = name
    g.save(update_fields=["name"])

    return HttpResponse("OK")


@require_POST
@login_required
def home_group_delete(request, group_id):
    org = _get_home_org(request)
    g = get_object_or_404(BoardGroup, id=group_id, user=request.user, organization=org, is_favorites=False)
    g.delete()
    return HttpResponse("")


@require_POST
@login_required
def home_group_item_add(request, group_id):
    org = _get_home_org(request)
    g = get_object_or_404(BoardGroup, id=group_id, user=request.user, organization=org)

    board_id = int(request.POST.get("board_id") or 0)
    if not board_id:
        return HttpResponse("board_id inválido", status=400)

    # valida acesso ao board
    if not BoardMembership.objects.filter(user=request.user, board_id=board_id, board__is_deleted=False).exists():
        return HttpResponse("Sem acesso ao quadro.", status=403)

    # posição: último
    last_pos = BoardGroupItem.objects.filter(group=g).aggregate(models.Max("position")).get("position__max") or 0
    obj, created = BoardGroupItem.objects.get_or_create(
        group=g,
        board_id=board_id,
        defaults={"position": last_pos + 1},
    )
    if not created:
        # já existe: não duplica
        return HttpResponse("OK")

    return HttpResponse("OK")


@require_POST
@login_required
def home_group_item_remove(request, group_id, board_id):
    org = _get_home_org(request)
    g = get_object_or_404(BoardGroup, id=group_id, user=request.user, organization=org)

    BoardGroupItem.objects.filter(group=g, board_id=board_id).delete()
    return HttpResponse("")


@require_POST
@login_required
def home_favorite_toggle(request, board_id):
    org = _get_home_org(request)
    fav = _get_or_create_favorites_group(request.user, org)

    board_id = int(board_id or 0)
    if not board_id:
        return HttpResponse("board_id inválido", status=400)

    if not BoardMembership.objects.filter(user=request.user, board_id=board_id, board__is_deleted=False).exists():
        return HttpResponse("Sem acesso ao quadro.", status=403)

    existing = BoardGroupItem.objects.filter(group=fav, board_id=board_id).first()
    if existing:
        existing.delete()
        return JsonResponse({"favorited": False})

    last_pos = BoardGroupItem.objects.filter(group=fav).aggregate(Max("position")).get("position__max") or 0
    BoardGroupItem.objects.create(group=fav, board_id=board_id, position=last_pos + 1)
    return JsonResponse({"favorited": True})



# ======================================================================
# DETALHE DE UM BOARD
# ======================================================================

def board_detail(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    columns = (
        board.columns
        .filter(is_deleted=False)
        .prefetch_related("cards")
        .order_by("position")
    )


    memberships_qs = board.memberships.select_related("user")

    # Usuário não logado, board já compartilhado → login
    if memberships_qs.exists() and not request.user.is_authenticated:
        login_url = reverse("boards:login")
        return redirect(f"{login_url}?next={request.path}")

    my_membership = None
    if request.user.is_authenticated:
        my_membership = memberships_qs.filter(user=request.user).first()

    # Se logado mas sem acesso → futuramente entra request-access
    if memberships_qs.exists() and request.user.is_authenticated and not my_membership:
        return HttpResponse("Você não tem acesso a este quadro.", status=403)

    # =========================
    # PERMISSÕES
    # =========================
    can_edit = bool(my_membership)
    can_share_board = bool(
        my_membership and my_membership.role == BoardMembership.Role.OWNER
    )
    can_leave_board = bool(
        my_membership and my_membership.role != BoardMembership.Role.OWNER
    )

    # =========================
    # BOARD MEMBERS (barra de avatares)
    # =========================
    memberships = memberships_qs.order_by("role", "user__username")

    board_members = []
    for m in memberships:
        u = m.user
        try:
            _ = u.profile
        except Exception:
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
@login_required
@transaction.atomic
def board_share(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    if request.method == "GET":
        return render(
        request,
        "boards/partials/board_share_form.html",
        {
            "board": board,
        },
    )

    my_membership = BoardMembership.objects.filter(
        board=board,
        user=request.user,
        role=BoardMembership.Role.OWNER,
    ).first()

    if not my_membership:
        return JsonResponse({"error": "Sem permissão para compartilhar este quadro."}, status=403)

    identifier = _normalize_email(request.POST.get("identifier"))
    role = request.POST.get("role") or BoardMembership.Role.MEMBER

    if "@" not in identifier:
        return JsonResponse({"error": "E-mail inválido."}, status=400)

    domain = identifier.split("@", 1)[1]
    allowed_domains = getattr(settings, "INSTITUTIONAL_EMAIL_DOMAINS", [])

    if domain not in allowed_domains:
        return JsonResponse({
            "error": "Este e-mail somente com autorização da direção da Camim."
        }, status=400)

    User = get_user_model()
    user = User.objects.filter(email__iexact=identifier).first()

    created_now = False
    if not user:
        user = User.objects.create(
            username=identifier,
            email=identifier,
            is_active=True,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        created_now = True

    membership, _ = BoardMembership.objects.get_or_create(
        board=board,
        user=user,
        defaults={"role": role},
    )

    if created_now:
        from . import FirstLoginPasswordResetForm

        form = FirstLoginPasswordResetForm(data={"email": user.email})
        if form.is_valid():
            form.save(
                request=request,
                use_https=request.is_secure(),
                from_email=settings.DEFAULT_FROM_EMAIL,
                email_template_name="registration/invite_board_email.txt",
                subject_template_name="registration/invite_board_subject.txt",
                extra_email_context={
                    "board": board,
                    "inviter": request.user,
                },
            )

    return JsonResponse({"success": True})


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
# TROCAR TITULARIDADE
# ======================================================================
@require_http_methods(["GET", "POST"])
@login_required
def transfer_owner_start(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    # Somente OWNER pode iniciar
    my = BoardMembership.objects.filter(board=board, user=request.user).first()
    if not my or my.role != BoardMembership.Role.OWNER:
        return HttpResponse("Você não tem permissão para transferir a titularidade deste quadro.", status=403)

    context = {
        "board": board,
        "step": 1,
        "email1": "",
        "email2": "",
    }

    if request.method == "GET":
        return render(request, "boards/partials/transfer_owner_modal.html", context)

    email1 = _normalize_email(request.POST.get("email1"))
    email2 = _normalize_email(request.POST.get("email2"))

    context["email1"] = email1
    context["email2"] = email2

    if not email1 or not email2:
        context["msg_error"] = "Informe os dois emails."
        return render(request, "boards/partials/transfer_owner_modal.html", context, status=400)

    if email1 != email2:
        context["msg_error"] = "Os emails não conferem."
        return render(request, "boards/partials/transfer_owner_modal.html", context, status=200)

    User = get_user_model()
    to_user = User.objects.filter(
    Q(email__iexact=email1) | Q(username__iexact=email1)
    ).first()
    if not to_user:
        context["msg_error"] = "Usuário não encontrado. Peça para ele criar conta antes."
        return render(request, "boards/partials/transfer_owner_modal.html", context, status=200)


    if to_user.id == request.user.id:
        context["msg_error"] = "Você já é o titular atual."
        return render(request, "boards/partials/transfer_owner_modal.html", context, status=200)

    # Gera código e guarda no cache por 10 min
    code = _gen_6digit_code()
    key = _transfer_cache_key(board.id, request.user.id)

    payload = {
        "to_user_id": int(to_user.id),
        "to_email": to_user.email or "",
        "code_hash": _hash_transfer_code(code),
        "attempts": 0,
        "created_at": timezone.now().isoformat(),
    }
    cache.set(key, payload, timeout=10 * 60)

        # Envia email para OWNER atual
    try:
        subject = f"Código para transferir titularidade — {board.name}"
        body = (
            f"Seu código para confirmar a transferência de titularidade do quadro \"{board.name}\" é: {code}\n\n"
            f"Esse código expira em 10 minutos."
        )

        # Resolve e-mail efetivo do usuário logado (OWNER atual)
        sender_email = (request.user.email or "").strip()
        if not sender_email:
            sender_email = (request.user.get_username() or "").strip()

        if not sender_email or "@" not in sender_email:
            cache.delete(key)
            context["msg_error"] = (
                "Seu usuário não possui e-mail válido cadastrado para receber o código. "
                "Atualize seu e-mail no perfil (ou peça ao admin)."
            )
            return render(request, "boards/partials/transfer_owner_modal.html", context, status=400)

        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[sender_email],
            fail_silently=False,
        )

    except Exception:
        cache.delete(key)
        context["msg_error"] = "Não foi possível enviar o email com o código. Tente novamente."
        return render(request, "boards/partials/transfer_owner_modal.html", context, status=500)

    # ✅ SUCESSO: avança para etapa 2 (input do código)
    context["step"] = 2
    context["msg_success"] = f"Código enviado para {sender_email}."
    return render(request, "boards/partials/transfer_owner_modal.html", context, status=200)




@require_POST
@login_required
def transfer_owner_confirm(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    # Somente OWNER pode confirmar
    my = BoardMembership.objects.filter(board=board, user=request.user).first()
    if not my or my.role != BoardMembership.Role.OWNER:
        return HttpResponse("Você não tem permissão para transferir a titularidade deste quadro.", status=403)

    code = (request.POST.get("code") or "").strip()
    if not code or len(code) != 6 or not code.isdigit():
        context = {"board": board, "step": 2, "msg_error": "Código inválido."}
        return render(request, "boards/partials/transfer_owner_modal.html", context, status=400)

    key = _transfer_cache_key(board.id, request.user.id)
    payload = cache.get(key)
    if not payload:
        context = {"board": board, "step": 1, "msg_error": "Solicitação expirada. Inicie novamente."}
        return render(request, "boards/partials/transfer_owner_modal.html", context, status=400)

    # Rate-limit simples por tentativas
    attempts = int(payload.get("attempts") or 0)
    if attempts >= 6:
        cache.delete(key)
        context = {"board": board, "step": 1, "msg_error": "Muitas tentativas. Inicie novamente."}
        return render(request, "boards/partials/transfer_owner_modal.html", context, status=429)

    expected = payload.get("code_hash") or ""
    if _hash_transfer_code(code) != expected:
        payload["attempts"] = attempts + 1
        cache.set(key, payload, timeout=10 * 60)
        context = {"board": board, "step": 2, "msg_error": "Código incorreto."}
        return render(request, "boards/partials/transfer_owner_modal.html", context, status=400)

    User = get_user_model()
    to_user_id = int(payload.get("to_user_id") or 0)
    to_user = User.objects.filter(id=to_user_id).first()
    if not to_user:
        cache.delete(key)
        context = {"board": board, "step": 1, "msg_error": "Usuário destino inválido. Inicie novamente."}
        return render(request, "boards/partials/transfer_owner_modal.html", context, status=400)

    actor = _actor_label(request)

    with transaction.atomic():
        # Revalida que ainda é OWNER (evita corrida)
        my2 = BoardMembership.objects.select_for_update().filter(board=board, user=request.user).first()
        if not my2 or my2.role != BoardMembership.Role.OWNER:
            cache.delete(key)
            return HttpResponse("Sua permissão mudou. Operação cancelada.", status=403)

        # Garante/promove destino a OWNER
        to_membership, created = BoardMembership.objects.get_or_create(
            board=board,
            user=to_user,
            defaults={"role": BoardMembership.Role.OWNER},
        )
        if not created and to_membership.role != BoardMembership.Role.OWNER:
            to_membership.role = BoardMembership.Role.OWNER
            to_membership.save(update_fields=["role"])

        # Rebaixa o OWNER atual
        my2.role = BoardMembership.Role.EDITOR
        my2.save(update_fields=["role"])

        # Garante que existe pelo menos 1 OWNER (o destino)
        owners_count = BoardMembership.objects.filter(board=board, role=BoardMembership.Role.OWNER).count()
        if owners_count <= 0:
            raise ValueError("Board ficou sem OWNER (violação de regra).")

        # Incrementa version para polling
        try:
            board.version = int(getattr(board, "version", 0) or 0) + 1
            board.save(update_fields=["version"])
        except Exception:
            # Se não existir version no model, não quebra a transação.
            pass

        _log_board(
            board,
            request,
            (
                f"<p><strong>{actor}</strong> transferiu a titularidade do quadro para "
                f"<strong>{escape(to_user.email or to_user.get_username())}</strong>.</p>"
            ),
        )

    # Consome a solicitação
    cache.delete(key)

    # Sucesso: fecha modal + reload (garante refletir permissões/menus)
    return HttpResponse(
        "<script>"
        "try{ if(window.Modal&&Modal.close){ Modal.close({clearBody:true,clearUrl:false}); } }catch(e){}"
        "try{ location.reload(); }catch(e){}"
        "</script>"
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




@login_required
@require_http_methods(["GET"])
def board_history_modal(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    memberships_qs = board.memberships.all()
    if memberships_qs.exists() and not memberships_qs.filter(user=request.user).exists():
        return HttpResponse("Você não tem acesso a este quadro.", status=403)

    # logs do quadro = todos CardLog dos cards do board
    logs = (
        CardLog.objects
        .filter(card__column__board=board, card__is_deleted=False)
        .select_related("card", "card__column")
        .order_by("-created_at")[:500]  # MVP: limita para não explodir o modal
    )

    # Ao abrir o histórico: marca como lido (zera contagem)
    now = timezone.now()
    st, _created = BoardActivityReadState.objects.get_or_create(board=board, user=request.user)
    st.last_seen_at = now
    st.save(update_fields=["last_seen_at", "updated_at"])

    return render(
        request,
        "boards/partials/board_history_modal.html",
        {"board": board, "logs": logs},
    )


@login_required
@require_http_methods(["GET"])
def board_history_unread_count(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    memberships_qs = board.memberships.all()
    if memberships_qs.exists() and not memberships_qs.filter(user=request.user).exists():
        return JsonResponse({"unread": 0})

    st = BoardActivityReadState.objects.filter(board=board, user=request.user).first()
    last_seen = st.last_seen_at if st and st.last_seen_at else None

    qs = CardLog.objects.filter(card__column__board=board, card__is_deleted=False)
    if last_seen:
        qs = qs.filter(created_at__gt=last_seen)

    return JsonResponse({"unread": int(qs.count())})


class BoardAccessRequest(models.Model):
    board = models.ForeignKey(
        "Board",
        on_delete=models.CASCADE,
        related_name="access_requests",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("board", "user")
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user} pediu acesso ao board {self.board}"


@login_required
@require_POST
def request_board_access(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    BoardAccessRequest.objects.get_or_create(
        board=board,
        user=request.user,
    )

    return JsonResponse({"success": True})


@login_required
@require_POST
def approve_board_access(request, board_id, user_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    my_membership = BoardMembership.objects.filter(
        board=board,
        user=request.user,
        role=BoardMembership.Role.OWNER,
    ).first()

    if not my_membership:
        return JsonResponse({"error": "Sem permissão."}, status=403)

    user = get_object_or_404(get_user_model(), id=user_id)

    BoardMembership.objects.get_or_create(
        board=board,
        user=user,
        defaults={"role": BoardMembership.Role.MEMBER},
    )

    BoardAccessRequest.objects.filter(board=board, user=user).delete()

    return JsonResponse({"success": True})
# ======================================================================