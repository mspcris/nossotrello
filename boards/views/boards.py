# boards/views/boards.py

import os
import uuid
import requests
import hashlib
import random
import logging
from types import SimpleNamespace

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import send_mail
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.db import models, transaction
from django.db.models import Q, Max, Prefetch
from django.db.models.functions import Coalesce
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.html import escape
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_POST, require_http_methods

from ..models import (
    Board,
    Column,
    Card,
    BoardMembership,
    Organization,
    CardLog,
    BoardActivityReadState,
    BoardGroup,
    BoardGroupItem,
    BoardAccessRequest,
    CardSeen,
    CardFollow,
)

from .helpers import (
    DEFAULT_WALLPAPER_FILENAME,
    _actor_label,
    _log_board,
    _log_card,
    get_or_create_user_default_organization,
)

logger = logging.getLogger(__name__)








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

        owned_ids = list(qs.filter(role=BoardMembership.Role.OWNER).values_list("board_id", flat=True))
        shared_ids = list(qs.exclude(role=BoardMembership.Role.OWNER).values_list("board_id", flat=True))

        org = _get_home_org(request)
        favorites_group = _get_or_create_favorites_group(request.user, org)

        groups_qs = BoardGroup.objects.filter(
            user=request.user,
            organization=org,
        ).order_by("position", "id")

        custom_groups = groups_qs.filter(is_favorites=False)
        accessible_ids = set(_user_accessible_board_ids(request.user))

        # favoritos primeiro
        favorite_ids = set()
        fav_items = (
            BoardGroupItem.objects.filter(group=favorites_group, board_id__in=accessible_ids)
            .select_related("board")
            .order_by("position", "id")
        )
        for it in fav_items:
            favorite_ids.add(it.board_id)

        # custom groups
        groups_data = []
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
        favorites_group = None
        fav_items = []
        favorite_ids = set()
        groups_data = []
        owned_boards = Board.objects.filter(is_deleted=False).order_by("-created_at")
        shared_boards = Board.objects.none()

    home_bg_image = None
    if request.user.is_authenticated:
        org2 = get_or_create_user_default_organization(request.user)
        filename = (getattr(org2, "home_wallpaper_filename", "") or "").strip()
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

    qs = BoardGroup.objects.filter(
        user=request.user,
        organization=org,
        is_favorites=False,
    )

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

    if not BoardMembership.objects.filter(user=request.user, board_id=board_id, board__is_deleted=False).exists():
        return HttpResponse("Sem acesso ao quadro.", status=403)

    last_pos = BoardGroupItem.objects.filter(group=g).aggregate(models.Max("position")).get("position__max") or 0
    obj, created = BoardGroupItem.objects.get_or_create(
        group=g,
        board_id=board_id,
        defaults={"position": last_pos + 1},
    )
    if not created:
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
        .order_by("position")
        .prefetch_related(
            Prefetch(
                "cards",
                queryset=Card.objects.filter(is_archived=False).order_by("position", "id"),
            )
        )
    )


    memberships_qs = board.memberships.select_related("user")

    my_membership = None
    invited_membership = None

    if request.user.is_authenticated:
        my_membership = memberships_qs.filter(user=request.user).first()

        # aceita convite pendente no primeiro acesso
        if my_membership and my_membership.accepted_at is None:
            my_membership.accepted_at = timezone.now()
            my_membership.save(update_fields=["accepted_at"])

    else:
        email = (request.GET.get("email") or "").strip().lower()

        if email:
            invited_membership = memberships_qs.filter(
                user__email__iexact=email,
                accepted_at__isnull=True,
            ).first()

        # board compartilhado, mas não é convidado válido
        if memberships_qs.exists() and not invited_membership:
            login_url = reverse("boards:login")
            return redirect(f"{login_url}?next={request.path}")

        # convite pendente → tela especial
        if invited_membership:
            return render(
                request,
                "boards/board_invited.html",
                {
                    "board": board,
                    "invited_email": invited_membership.user.email,
                },
            )

    # logado mas sem acesso
    if memberships_qs.exists() and request.user.is_authenticated and not my_membership:
        owner_membership = memberships_qs.filter(role=BoardMembership.Role.OWNER).select_related("user").first()
        owner_user = owner_membership.user if owner_membership else None

        return render(
            request,
            "boards/board_no_access.html",
            {
                "board": board,
                "owner_user": owner_user,
            },
            status=403,
        )

    # regra de edição: somente OWNER/EDITOR (e staff sempre)
    can_edit = bool(
        request.user.is_authenticated
        and (
            getattr(request.user, "is_staff", False)
            or (
                my_membership
                and my_membership.role in {
                    BoardMembership.Role.OWNER,
                    BoardMembership.Role.EDITOR,
                }
            )
        )
    )

    can_share_board = bool(my_membership and my_membership.role == BoardMembership.Role.OWNER)
    can_leave_board = bool(my_membership and my_membership.role != BoardMembership.Role.OWNER)

    memberships = memberships_qs.order_by("role", "user__username")

    board_members = []
    for m in memberships:
        u = m.user
        try:
            _ = u.profile
        except Exception:
            u._state.fields_cache["profile"] = SimpleNamespace(avatar=None)

        board_members.append(u)

    pending_access_requests = []
    if can_share_board:
        pending_access_requests = (
            BoardAccessRequest.objects
            .filter(board=board)
            .select_related("user", "user__profile")
            .order_by("-created_at")
        )

    # ============================================================
    # UNREAD ACTIVITY COUNT (pré-carregamento da board)
    # ============================================================
    unread_activity_count = 0

    if request.user.is_authenticated:
        st = BoardActivityReadState.objects.filter(
            board=board,
            user=request.user,
        ).first()

        last_seen = st.last_seen_at if st and st.last_seen_at else None

        qs = CardLog.objects.filter(
            card__column__board=board,
            card__is_deleted=False,
        )

        if last_seen:
            qs = qs.filter(created_at__gt=last_seen)

        # ignora ações do próprio usuário
        actor_label = _actor_label(request)
        if actor_label:
            qs = qs.exclude(content__icontains=actor_label)

        unread_activity_count = qs.count()

    # ============================================================
    # UNREAD POR CARD (BOOTSTRAP INICIAL)
    # ============================================================
    unread_by_card = {}

    if request.user.is_authenticated:
        data = (
            qs.values("card_id")
            .annotate(c=models.Count("id"))
            .values_list("card_id", "c")
        )
        unread_by_card = {card_id: c for card_id, c in data}
    # ============================================================
    # FOLLOWING POR CARD (BOOTSTRAP INICIAL)
    # ============================================================
    followed_ids = set()
    if request.user.is_authenticated:
        followed_ids = set(
            CardFollow.objects
            .filter(user=request.user, card__column__board=board)
            .values_list("card_id", flat=True)
        )

    # ============================================================
    # FOLLOWERS (QUEM SEGUE) POR CARD — BOOTSTRAP INICIAL
    # Regra: NÃO incluir o próprio request.user (não ocupa espaço)
    # ============================================================
    followers_by_card = {}
    followers_count_by_card = {}

    if request.user.is_authenticated:
        try:
            qs_follows = (
                CardFollow.objects
                .filter(card__column__board=board)
                .select_related("user", "user__profile")
                .order_by("id")  # ordem estável pro stack
            )

            for cf in qs_follows:
                u = cf.user

                # regra: não mostrar "eu mesmo" no stack
                if int(u.id) == int(request.user.id):
                    continue

                cid = int(cf.card_id)

                # avatar
                avatar_url = None
                try:
                    prof = getattr(u, "profile", None)
                    av = getattr(prof, "avatar", None) if prof else None
                    if av and getattr(av, "name", ""):
                        avatar_url = av.url
                except Exception:
                    avatar_url = None


                # nome exibível
                try:
                    prof = getattr(u, "profile", None)
                    display_name = (getattr(prof, "display_name", "") or "").strip()
                except Exception:
                    display_name = ""

                name = (
                    display_name
                    or (u.get_full_name() or "").strip()
                    or (u.username or "").strip()
                    or (u.email or "").strip()
                    or "Usuário"
                )

                followers_by_card.setdefault(cid, []).append({
                    "id": int(u.id),
                    "name": name,
                    "avatar_url": avatar_url,
                })

            followers_count_by_card = {cid: len(lst) for cid, lst in followers_by_card.items()}

        except Exception:
            followers_by_card = {}
            followers_count_by_card = {}

    # ============================================================
    # FIX: INJETAR NO OBJETO CARD ANTES DO 1º RENDER
    # (assim o template do card já nasce com o número, sem esperar poll/js)
    # ============================================================
    try:
        for col in columns:
            for c in col.cards.all():
                c.unread_count = int(unread_by_card.get(c.id, 0) or 0)
                c.is_following = (c.id in followed_ids)

                preview = followers_by_card.get(c.id, []) or []
                c.followers_preview = preview[:4]
                c.followers_count = int(followers_count_by_card.get(c.id, 0) or 0)
    except Exception:
        pass

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
            "pending_access_requests": pending_access_requests,
            "unread_activity_count": unread_activity_count,
            "unread_by_card": unread_by_card,
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

    return HttpResponseBadRequest("Método inválido.")


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

    return HttpResponseBadRequest("Método inválido.")


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
@login_required
@transaction.atomic
def board_share(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    def render_modal(status=200, **ctx):
        memberships = (
            board.memberships
            .select_related("user")
            .order_by("role", "user__username")
        )
        base_ctx = {
            "board": board,
            "memberships": memberships,
        }
        base_ctx.update(ctx)
        return render(
            request,
            "boards/partials/board_share_form.html",
            base_ctx,
            status=status,
        )

    # GET: abre modal
    if request.method == "GET":
        return render_modal()

    # POST: somente OWNER compartilha
    my_membership = BoardMembership.objects.filter(
        board=board,
        user=request.user,
        role=BoardMembership.Role.OWNER,
    ).first()

    if not my_membership:
        return render_modal(status=403, msg_error="Sem permissão para compartilhar este quadro.")

    identifier = _normalize_email(request.POST.get("identifier"))
    if not identifier or "@" not in identifier:
        return render_modal(status=400, msg_error="E-mail inválido.")

    # Role
    role = (request.POST.get("role") or "").strip().lower()
    if role not in {BoardMembership.Role.EDITOR, BoardMembership.Role.VIEWER, BoardMembership.Role.OWNER}:
        role = BoardMembership.Role.EDITOR

    # Política de domínio:
    # - Interno (domínio permitido): pode criar user automaticamente (mesmo que nunca tenha logado)
    # - Externo (fora do domínio): só pode compartilhar se o user já existir (criado manualmente pela Direção)
    domain = identifier.split("@", 1)[1].strip().lower()
    allowed_domains = [d.strip().lower() for d in getattr(settings, "INSTITUTIONAL_EMAIL_DOMAINS", []) if d]
    is_internal = (not allowed_domains) or (domain in allowed_domains)

    # Usuário (por e-mail)
    User = get_user_model()
    user = User.objects.filter(email__iexact=identifier).first()

    # Externo: não cria automaticamente; exige existir
    if (not is_internal) and (not user):
        return render_modal(
            status=200,  # <- era 400
            msg_error="Usuário não permitido para convite. Contate o adm.",
        )


    created_user = False
    if not user:
        # Interno: cria automaticamente
        user = User.objects.create(
            username=identifier,
            email=identifier,
            is_active=True,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        created_user = True

    membership, created_membership = BoardMembership.objects.get_or_create(
        board=board,
        user=user,
        defaults={
            "role": role,
            "invited_at": timezone.now(),
        },
    )

    # Se já existia membership, atualiza role (se não for owner) e re-invite se pendente
    if not created_membership:
        changed = False

        if membership.role != role and membership.role != BoardMembership.Role.OWNER:
            membership.role = role
            changed = True

        if membership.accepted_at is None:
            membership.invited_at = timezone.now()
            changed = True

        if changed:
            membership.save(update_fields=["role", "invited_at"])

    # ==========================================================
    # EMAIL (mantido como está no seu arquivo atual)
    # ==========================================================
    email_failed = False
    email_error_msg = ""
    
    should_email = created_membership or created_user or (membership.accepted_at is None)
    if not should_email:
        return render_modal(status=200, msg_success=f"Acesso atualizado para {user.email}.")

    try:
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        try:
            reset_path = reverse("boards:password_reset_confirm", kwargs={"uidb64": uidb64, "token": token})
        except Exception:
            reset_path = f"/accounts/reset/{uidb64}/{token}/"

        base_url = getattr(settings, "SITE_URL", "").strip()
        if not base_url:
            scheme = "https" if request.is_secure() else "http"
            base_url = f"{scheme}://{request.get_host()}"

        reset_url = f"{base_url}{reset_path}"

        # >>> ADICIONE AQUI <<<
        board_path = reverse("boards:board_detail", kwargs={"board_id": board.id})
        board_url = f"{base_url}{board_path}?email={user.email}"

        subject = f"Convite para o quadro: {board.name}"

        ctx = {
            "board": board,
            "inviter": request.user,
            "user": user,
            "reset_url": reset_url,
            "board_url": board_url,
            "created_user": created_user,
            "membership": membership,
            "uid": uidb64,   # se você for usar no template
            "token": token,  # se você for usar no template
        }

        try:
            text_body = render_to_string("registration/invite_board_email.txt", ctx).strip()
        except Exception:
            text_body = (
                f"Você foi convidado(a) para o quadro \"{board.name}\".\n\n"
                f"Acesse o quadro:\n{board_url}\n\n"
                f"Se você não lembra sua senha ou se é o primeiro acesso, clique aqui:\n{reset_url}\n\n"
                f"Convidado por: {request.user.email or request.user.get_username()}\n"
            )


        try:
            html_body = render_to_string("registration/invite_board_email.html", ctx)
        except Exception:
            html_body = None

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=[user.email],
        )
        if html_body:
            msg.attach_alternative(html_body, "text/html")

        msg.send(fail_silently=False)

    except Exception:
        email_failed = True
        email_error_msg = "Falha ao enviar o e-mail. Verifique SMTP/credenciais/DEFAULT_FROM_EMAIL."
        try:
            logger.exception("board_share: falha ao enviar convite por email")
        except Exception:
            pass

    if email_failed:
        return render_modal(
            status=200,
            msg_error=f"Convite criado, mas o e-mail não foi enviado. {email_error_msg}",
        )

    return render_modal(
        status=200,
        msg_success=f"Convite enviado para {user.email}.",
    )



# ======================================================================
# TROCAR TITULARIDADE
# ======================================================================

@require_http_methods(["GET", "POST"])
@login_required
def transfer_owner_start(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

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
    to_user = User.objects.filter(Q(email__iexact=email1) | Q(username__iexact=email1)).first()
    if not to_user:
        context["msg_error"] = "Usuário não encontrado. Peça para ele criar conta antes."
        return render(request, "boards/partials/transfer_owner_modal.html", context, status=200)

    if to_user.id == request.user.id:
        context["msg_error"] = "Você já é o titular atual."
        return render(request, "boards/partials/transfer_owner_modal.html", context, status=200)

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

    try:
        subject = f"Código para transferir titularidade — {board.name}"
        body = (
            f"Seu código para confirmar a transferência de titularidade do quadro \"{board.name}\" é: {code}\n\n"
            f"Esse código expira em 10 minutos."
        )

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

    context["step"] = 2
    context["msg_success"] = f"Código enviado para {sender_email}."
    return render(request, "boards/partials/transfer_owner_modal.html", context, status=200)


@require_POST
@login_required
def transfer_owner_confirm(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

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
        my2 = BoardMembership.objects.select_for_update().filter(board=board, user=request.user).first()
        if not my2 or my2.role != BoardMembership.Role.OWNER:
            cache.delete(key)
            return HttpResponse("Sua permissão mudou. Operação cancelada.", status=403)

        to_membership, created = BoardMembership.objects.get_or_create(
            board=board,
            user=to_user,
            defaults={"role": BoardMembership.Role.OWNER},
        )
        if not created and to_membership.role != BoardMembership.Role.OWNER:
            to_membership.role = BoardMembership.Role.OWNER
            to_membership.save(update_fields=["role"])

        my2.role = BoardMembership.Role.EDITOR
        my2.save(update_fields=["role"])

        owners_count = BoardMembership.objects.filter(board=board, role=BoardMembership.Role.OWNER).count()
        if owners_count <= 0:
            raise ValueError("Board ficou sem OWNER (violação de regra).")

        try:
            board.version = int(getattr(board, "version", 0) or 0) + 1
            board.save(update_fields=["version"])
        except Exception:
            pass

        _log_board(
            board,
            request,
            (
                f"<p><strong>{actor}</strong> transferiu a titularidade do quadro para "
                f"<strong>{escape(to_user.email or to_user.get_username())}</strong>.</p>"
            ),
        )

    cache.delete(key)

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


# ======================================================================
# POLLING / COLUNAS
# ======================================================================

@login_required
def board_poll(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    client_version = int(request.GET.get("v", 0))

    if board.version == client_version:
        return JsonResponse({"changed": False})

    columns = (
        board.columns
        .filter(is_deleted=False)
        .order_by("position")
        .prefetch_related(
            Prefetch(
                "cards",
                queryset=Card.objects.filter(is_archived=False).order_by("position", "id"),
            )
        )
    )

    # ============================================================
    # UNREAD POR CARD (POLL)
    # ============================================================
    unread_by_card = {}

    try:
        st = BoardActivityReadState.objects.filter(board=board, user=request.user).first()
        last_seen = st.last_seen_at if st and st.last_seen_at else None

        qs_logs = CardLog.objects.filter(
            card__column__board=board,
            card__is_deleted=False,
        )

        if last_seen:
            qs_logs = qs_logs.filter(created_at__gt=last_seen)

        actor_label = _actor_label(request)
        if actor_label:
            qs_logs = qs_logs.exclude(content__icontains=actor_label)

        data = (
            qs_logs.values("card_id")
            .annotate(c=models.Count("id"))
            .values_list("card_id", "c")
        )
        unread_by_card = {card_id: c for card_id, c in data}
    except Exception:
        unread_by_card = {}

    # ============================================================
    # FOLLOWING POR CARD (POLL)
    # ============================================================
    followed_ids = set()
    try:
        followed_ids = set(
            CardFollow.objects
            .filter(user=request.user, card__column__board=board)
            .values_list("card_id", flat=True)
        )
    except Exception:
        followed_ids = set()

    # ============================================================
    # FOLLOWERS (QUEM SEGUE) POR CARD — POLL
    # ============================================================
    followers_by_card = {}
    followers_count_by_card = {}

    try:
        qs_follows = (
            CardFollow.objects
            .filter(card__column__board=board)
            .select_related("user", "user__profile")
            .order_by("id")
        )

        for cf in qs_follows:
            u = cf.user

            # regra: não mostrar "eu mesmo" no stack
            if int(u.id) == int(request.user.id):
                continue

            cid = int(cf.card_id)

            avatar_url = None
            try:
                prof = getattr(u, "profile", None)
                av = getattr(prof, "avatar", None) if prof else None
                avatar_url = av.url if av else None
            except Exception:
                avatar_url = None

            try:
                prof = getattr(u, "profile", None)
                display_name = (getattr(prof, "display_name", "") or "").strip()
            except Exception:
                display_name = ""

            name = (
                display_name
                or (u.get_full_name() or "").strip()
                or (u.username or "").strip()
                or (u.email or "").strip()
                or "Usuário"
            )

            followers_by_card.setdefault(cid, []).append({
                "id": int(u.id),
                "name": name,
                "avatar_url": avatar_url,
            })

        followers_count_by_card = {cid: len(lst) for cid, lst in followers_by_card.items()}
    except Exception:
        followers_by_card = {}
        followers_count_by_card = {}

    # ============================================================
    # INJEÇÃO NO OBJETO CARD ANTES DO RENDER DO PARTIAL
    # ============================================================
    try:
        for col in columns:
            for c in col.cards.all():
                c.unread_count = int(unread_by_card.get(c.id, 0) or 0)
                c.is_following = (c.id in followed_ids)

                preview = followers_by_card.get(c.id, []) or []
                c.followers_preview = preview[:4]
                c.followers_count = int(followers_count_by_card.get(c.id, 0) or 0)
    except Exception:
        pass

    html = render_to_string(
        "boards/partials/columns_block.html",
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
                queryset=Card.objects.filter(is_archived=False).order_by("position", "id"),
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


# ======================================================================
# HISTÓRICO / NÃO LIDOS
# ======================================================================

@login_required
@require_http_methods(["GET"])
def board_history_modal(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    memberships_qs = board.memberships.all()
    if memberships_qs.exists() and not memberships_qs.filter(user=request.user).exists():
        return HttpResponse("Você não tem acesso a este quadro.", status=403)

    logs = (
        CardLog.objects
        .filter(card__column__board=board, card__is_deleted=False)
        .select_related("card", "card__column")
        .order_by("-created_at")[:500]
    )

    # Ao abrir o histórico: marca como lido (zera contagem do histórico)
    now = timezone.now()
    st, _created = BoardActivityReadState.objects.get_or_create(board=board, user=request.user)
    st.last_seen_at = now
    st.save(update_fields=["last_seen_at", "updated_at"])

    # ✅ NOVA REGRA: ao abrir o histórico, zera também as notificações dos CARDS do quadro
    cards_qs = Card.objects.filter(column__board=board, is_deleted=False).only("id")
    card_ids = list(cards_qs.values_list("id", flat=True))

    if card_ids:
        # atualiza os já existentes
        CardSeen.objects.filter(user=request.user, card_id__in=card_ids).update(last_seen_at=now)

        # cria os que não existem ainda (para realmente zerar tudo)
        existing_ids = set(
            CardSeen.objects.filter(user=request.user, card_id__in=card_ids)
            .values_list("card_id", flat=True)
        )
        missing_ids = [cid for cid in card_ids if cid not in existing_ids]
        if missing_ids:
            CardSeen.objects.bulk_create(
                [CardSeen(card_id=cid, user=request.user, last_seen_at=now) for cid in missing_ids],
                ignore_conflicts=True,
            )

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

    qs = CardLog.objects.filter(
        card__column__board=board,
        card__is_deleted=False,
        card__is_archived=False,
    )

    if last_seen:
        qs = qs.filter(created_at__gt=last_seen)

    # 🔴 REGRA-CHAVE: ignora logs do próprio usuário
    actor_label = _actor_label(request)
    if actor_label:
        qs = qs.exclude(content__icontains=actor_label)

    return JsonResponse({"unread": qs.count()})



# ======================================================================
# SOLICITAÇÃO DE ACESSO / APROVAÇÃO
# ======================================================================

@login_required
@require_POST
def request_board_access(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    # Se já tem acesso, não faz nada
    if BoardMembership.objects.filter(board=board, user=request.user).exists():
        return JsonResponse({"success": True, "already_has_access": True})

    # Campos do formulário
    nome = (request.POST.get("nome") or "").strip()
    posto = (request.POST.get("posto") or "").strip()
    funcao = (request.POST.get("funcao") or "").strip()
    telefone = (request.POST.get("telefone") or "").strip()
    ramal = (request.POST.get("ramal") or "").strip()
    email = (request.POST.get("email") or "").strip().lower()

    # Validação mínima (como você pediu)
    if not nome or not telefone or not email:
        return JsonResponse(
            {"success": False, "error": "Preencha Nome, Telefone e Email para solicitar autorização."},
            status=400,
        )

    # Segurança: email do formulário deve bater com o do usuário logado
    user_email = (request.user.email or "").strip().lower()
    if user_email and email != user_email:
        return JsonResponse(
            {"success": False, "error": "O e-mail informado precisa ser o mesmo do seu login."},
            status=400,
        )

    # Atualiza/garante profile (sem mexer no modelo BoardAccessRequest)
    try:
        profile = request.user.profile
    except Exception:
        from ..models import UserProfile
        profile = UserProfile.objects.create(user=request.user)

    # Mapeamento
    profile.display_name = nome or profile.display_name
    profile.posto = posto or profile.posto
    profile.setor = funcao or profile.setor  # "função" mapeando para setor (ou crie campo depois no sprint 2)
    profile.ramal = ramal or profile.ramal
    profile.telefone = telefone or profile.telefone
    profile.save(update_fields=["display_name", "posto", "setor", "ramal", "telefone"])

    # Cria a solicitação
    req_obj, created = BoardAccessRequest.objects.get_or_create(
        board=board,
        user=request.user,
    )

    # --------------------------------------------------
    # 1) SINALIZA MUDANÇA PARA O POLL DO OWNER (SEM F5)
    # --------------------------------------------------
    try:
        board.version = int(getattr(board, "version", 0) or 0) + 1
        board.save(update_fields=["version"])
    except Exception:
        pass


    # Descobre o dono
    owner_membership = BoardMembership.objects.filter(board=board, role=BoardMembership.Role.OWNER).select_related("user").first()
    owner_user = owner_membership.user if owner_membership else None

    # Se não achou dono, devolve sucesso sem e-mail (evita quebrar)
    if not owner_user or not (owner_user.email or "").strip():
        return JsonResponse({"success": True, "created": created, "email_sent": False})

    # Monta link para o dono abrir o quadro e aprovar
    base_url = getattr(settings, "SITE_URL", "").strip()
    if not base_url:
        scheme = "https" if request.is_secure() else "http"
        base_url = f"{scheme}://{request.get_host()}"

    board_path = reverse("boards:board_detail", kwargs={"board_id": board.id})
    board_url = f"{base_url}{board_path}"

    # Email para o dono (simples, sprint 1)
    subject = f"Solicitação de acesso — {board.name}"
    body = (
        f"Olá,\n\n"
        f"{nome} solicitou acesso ao quadro \"{board.name}\".\n\n"
        f"Contato:\n"
        f"- Nome: {nome}\n"
        f"- Posto: {posto or '-'}\n"
        f"- Função: {funcao or '-'}\n"
        f"- Telefone: {telefone}\n"
        f"- Ramal: {ramal or '-'}\n"
        f"- Email: {email}\n\n"
        f"Para aprovar ou negar, abra o quadro:\n{board_url}\n"
    )
    # --------------------------------------------------
    # 2) WHATSAPP PARA O DONO DO QUADRO
    # --------------------------------------------------
    try:
        from boards.services.notifications import send_whatsapp
        import re

        owner = owner_user
        prof = getattr(owner, "profile", None)

        phone = getattr(prof, "telefone", "") if prof else ""
        phone = re.sub(r"\D+", "", phone or "")

        # adiciona DDI Brasil se necessário
        if len(phone) in (10, 11):
            phone = "55" + phone

        if len(phone) in (12, 13):
            nome = request.user.get_full_name() or request.user.username
            msg = (
                f"{nome} solicitou acesso ao seu quadro:\n"
                f"{board.name}\n\n"
                f"Abra o quadro para aprovar ou negar."
            )
            send_whatsapp(user=owner, phone_digits=phone, body=msg)
            send_whatsapp(user=owner, phone_digits=phone, body=board_url)
    except Exception:
        pass

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[owner_user.email],
            fail_silently=False,
        )
        return JsonResponse({"success": True, "created": created, "email_sent": True})
    except Exception:
        return JsonResponse({"success": True, "created": created, "email_sent": False})



# ======================================================================
# REMOVER ACESSO (OWNER)
# ======================================================================

@require_http_methods(["POST"])
@login_required
@transaction.atomic
def board_share_remove(request, board_id, user_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    my_membership = BoardMembership.objects.filter(
        board=board,
        user=request.user,
        role=BoardMembership.Role.OWNER,
    ).first()
    if not my_membership:
        return HttpResponse("Você não tem permissão para remover acessos deste quadro.", status=403)

    membership = BoardMembership.objects.filter(board=board, user_id=user_id).select_related("user").first()
    if not membership:
        return HttpResponse("Acesso não encontrado.", status=404)

    if membership.role == BoardMembership.Role.OWNER:
        owners_count = BoardMembership.objects.filter(board=board, role=BoardMembership.Role.OWNER).count()
        if owners_count <= 1:
            return HttpResponse("Não é possível remover o último DONO do quadro.", status=400)

    removed_user = membership.user
    membership.delete()

    actor = _actor_label(request)
    _log_board(
        board,
        request,
        f"<p><strong>{actor}</strong> removeu o acesso de <strong>{escape(removed_user.email or removed_user.get_username())}</strong> do quadro.</p>",
    )

    return JsonResponse({"success": True})

@login_required
@require_POST
@transaction.atomic
def approve_board_access(request, board_id, user_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    owner = BoardMembership.objects.filter(
        board=board,
        user=request.user,
        role=BoardMembership.Role.OWNER,
    ).first()
    if not owner:
        return JsonResponse({"error": "Sem permissão."}, status=403)

    User = get_user_model()
    user = get_object_or_404(User, id=user_id)

    BoardMembership.objects.get_or_create(
        board=board,
        user=user,
        defaults={"role": BoardMembership.Role.VIEWER},
    )

    BoardAccessRequest.objects.filter(board=board, user=user).delete()

    # Email para solicitante
    if (user.email or "").strip():
        base_url = getattr(settings, "SITE_URL", "").strip()
        if not base_url:
            scheme = "https" if request.is_secure() else "http"
            base_url = f"{scheme}://{request.get_host()}"

        board_path = reverse("boards:board_detail", kwargs={"board_id": board.id})
        board_url = f"{base_url}{board_path}"

        try:
            send_mail(
                subject=f"Acesso aprovado — {board.name}",
                message=(
                    f"Olá,\n\n"
                    f"Seu acesso ao quadro \"{board.name}\" foi aprovado.\n\n"
                    f"Acesse aqui:\n{board_url}\n"
                ),
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception:
            pass

    return redirect(reverse("boards:board_detail", kwargs={"board_id": board.id}))


@login_required
@require_POST
@transaction.atomic
def deny_board_access(request, board_id, user_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    owner = BoardMembership.objects.filter(
        board=board,
        user=request.user,
        role=BoardMembership.Role.OWNER,
    ).first()
    if not owner:
        return JsonResponse({"error": "Sem permissão."}, status=403)

    User = get_user_model()
    user = get_object_or_404(User, id=user_id)

    # Remove a solicitação pendente
    BoardAccessRequest.objects.filter(board=board, user=user).delete()

    # Email para solicitante (melhor esforço)
    if (user.email or "").strip():
        try:
            send_mail(
                subject=f"Acesso negado — {board.name}",
                message=(
                    f"Olá,\n\n"
                    f"Infelizmente o dono do quadro \"{board.name}\" não autorizou seu acesso no momento.\n\n"
                    f"Se você acha que isso é um engano, responda este e-mail ou contate o responsável pelo quadro."
                ),
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[user.email],
                fail_silently=False,
            )
        except Exception:
            pass

    return redirect(reverse("boards:board_detail", kwargs={"board_id": board.id}))

def user_can_share_board(user, board) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False

    # “admin” (staff) pode ver/gerir
    if getattr(user, "is_staff", False):
        return True

    bm = BoardMembership.objects.filter(board=board, user=user).first()
    return bool(bm and bm.role == BoardMembership.Role.OWNER)


@login_required
def board_access_requests_poll(request, board_id):
    board = get_object_or_404(Board, id=board_id, is_deleted=False)

    # se não pode compartilhar/gerenciar, devolve vazio (não “vaza” info)
    if not user_can_share_board(request.user, board):
        return HttpResponse("", content_type="text/html")

    pending_access_requests = (
        BoardAccessRequest.objects
        .filter(board=board)
        .select_related("user", "user__profile")
        .order_by("-id")
    )

    html = render_to_string(
        "boards/partials/access_requests_panel.html",
        {"pending_access_requests": pending_access_requests},
        request=request,
    )
    return HttpResponse(html, content_type="text/html")

