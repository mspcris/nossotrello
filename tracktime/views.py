# tracktime/views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse, HttpResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.conf import settings
from django.core.mail import send_mail
from .models import Project, ActivityType, TimeEntry
from boards.models import Card, Board, CardLog
import re
from boards.models import UserProfile
from tracktime.services.pressticket import send_text_message, PressTicketError
import logging
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.views.decorators.http import require_http_methods
from datetime import timedelta
from django.contrib.auth import get_user_model
User = get_user_model()
from .models import TrackPresence


logger = logging.getLogger(__name__)

def _send_whatsapp_two_messages(*, number: str, message: str, url: str) -> None:
    """
    Sempre envia 2 mensagens:
    1) comunicado (message)
    2) somente link (url)
    """
    number = (number or "").strip()
    message = (message or "").strip()
    url = (url or "").strip()

    if not number or not getattr(settings, "PRESSTICKET_TOKEN", "").strip():
        return

    base_url = getattr(settings, "PRESSTICKET_BASE_URL", "https://api.atendimento.camim.com.br")
    token = getattr(settings, "PRESSTICKET_TOKEN", "")
    user_id = getattr(settings, "PRESSTICKET_USER_ID", 0)
    queue_id = getattr(settings, "PRESSTICKET_QUEUE_ID", 0)
    whatsapp_id = getattr(settings, "PRESSTICKET_WHATSAPP_ID", 0)

    # 1) comunicado
    if message:
        logger.warning(
            "pressticket: sending kind=message number=%r base_url=%r user_id=%s queue_id=%s whatsapp_id=%s",
            number, base_url, user_id, queue_id, whatsapp_id
        )
        resp = send_text_message(
            base_url=base_url,
            token=token,
            number=number,
            body=message,
            user_id=user_id,
            queue_id=queue_id,
            whatsapp_id=whatsapp_id,
        )
        logger.warning(
            "pressticket: sent ok kind=message number=%r resp_keys=%s",
            number, list((resp or {}).keys())[:15]
        )

    # 2) link puro (sem texto)
    if url:
        logger.warning(
            "pressticket: sending kind=url number=%r base_url=%r user_id=%s queue_id=%s whatsapp_id=%s",
            number, base_url, user_id, queue_id, whatsapp_id
        )
        resp = send_text_message(
            base_url=base_url,
            token=token,
            number=number,
            body=url,
            user_id=user_id,
            queue_id=queue_id,
            whatsapp_id=whatsapp_id,
        )
        logger.warning(
            "pressticket: sent ok kind=url number=%r resp_keys=%s",
            number, list((resp or {}).keys())[:15]
        )


def _get_or_create_activity_type_for_user(*, user, name: str) -> ActivityType:
    name = (name or "").strip()
    if not name:
        return None

    try:
        with transaction.atomic():
            obj, created = ActivityType.objects.get_or_create(
                name=name,
                created_by=user,
                defaults={"is_active": True},
            )
            if not created and not obj.is_active:
                obj.is_active = True
                obj.save(update_fields=["is_active"])
            return obj
    except IntegrityError:
        # fallback para corrida/duplicidade: busca o existente
        return (
            ActivityType.objects
            .filter(created_by=user, name=name)
            .order_by("-id")
            .first()
        )

def _get_or_create_project_for_user(*, user, name: str) -> Project:
    name = (name or "").strip()
    if not name:
        return None

    try:
        with transaction.atomic():
            obj, created = Project.objects.get_or_create(
                name=name,
                created_by=user,
                defaults={"is_active": True},
            )
            if not created and not obj.is_active:
                obj.is_active = True
                obj.save(update_fields=["is_active"])
            return obj
    except IntegrityError:
        return (
            Project.objects
            .filter(created_by=user, name=name)
            .order_by("-id")
            .first()
        )


def _format_mmss(seconds: int) -> str:
    seconds = max(int(seconds or 0), 0)
    mm = seconds // 60
    ss = seconds % 60
    return f"{mm}:{ss:02d}"


def _can_view_board(user, board) -> bool:
    """
    Regra de leitura:
    - superuser vê tudo
    - board com memberships: basta estar na membership
    - fallback legado: criador do board
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    memberships_qs = getattr(board, "memberships", None)
    if memberships_qs is not None:
        return memberships_qs.filter(user=user).exists()

    return bool(getattr(board, "created_by_id", None) == user.id)


# ============================================================
# Card modal tracktime (existente)
# ============================================================

@login_required
def card_tracktime_panel(request, card_id):
    card = get_object_or_404(
        Card.objects.select_related("column__board"),
        id=card_id
    )
    if not _can_view_board(request.user, card.column.board):
        return HttpResponseForbidden("Sem acesso ao board deste card")

    projects = Project.objects.filter(
        created_by=request.user,
        is_active=True
    ).order_by("name")

    activities = ActivityType.objects.filter(
        created_by=request.user,
        is_active=True
    ).order_by("name")


    entries = (
        TimeEntry.objects
        .filter(card_id=card.id)
        .select_related("project", "activity_type", "user")
        .order_by("-id")[:10]
    )

    running = (
        TimeEntry.objects
        .filter(card_id=card.id, user=request.user, ended_at__isnull=True)
        .first()
    )

    now = timezone.now()
    elapsed_seconds = 0
    confirm_needed = False
    confirm_due_in = None
    auto_stop_in = None

    if running and running.started_at:
        elapsed_seconds = int((now - running.started_at).total_seconds())
        confirm_needed = running.needs_confirmation(now=now)

        if running.confirm_due_at:
            confirm_due_in = int((running.confirm_due_at - now).total_seconds())
        if running.auto_stop_at:
            auto_stop_in = int((running.auto_stop_at - now).total_seconds())

    return render(
        request,
        "tracktime/card_tracktime_panel.html",
        {
            "card": card,
            "projects": projects,
            "activities": activities,
            "entries": entries,
            "running": running,
            "elapsed_seconds": elapsed_seconds,
            "elapsed_mmss": _format_mmss(elapsed_seconds),
            "confirm_needed": confirm_needed,
            "confirm_due_in": confirm_due_in,
            "auto_stop_in": auto_stop_in,
            "auto_stop_mmss": _format_mmss(auto_stop_in) if auto_stop_in is not None else None,
        },
    )


@login_required
def card_tracktime_start(request, card_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    card = get_object_or_404(
        Card.objects.select_related("column__board"),
        id=card_id
    )

    if not _can_view_board(request.user, card.column.board):
        return HttpResponseForbidden("Sem acesso ao board deste card")

    project_id = (request.POST.get("project") or "").strip()
    activity_id = (request.POST.get("activity") or "").strip()

    if not project_id or not activity_id:
        return HttpResponseBadRequest("Projeto e atividade são obrigatórios")

    # ✅ GATE: telefone obrigatório antes de qualquer efeito colateral
    prof = _get_or_create_profile(request.user)
    if not (prof.telefone or "").strip():
      

        url = reverse("tracktime:modal") + "?tab=portal&reason=phone_required"
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = url
        return resp


    project = get_object_or_404(
        Project,
        pk=project_id,
        created_by=request.user,
        is_active=True
    )

    activity = get_object_or_404(
        ActivityType,
        pk=activity_id,
        created_by=request.user,
        is_active=True
    )

    # ✅ 1 timer ativo por usuário (fecha corretamente, acumulando minutos)
    running_qs = TimeEntry.objects.filter(
        user=request.user,
        ended_at__isnull=True,
    ).order_by("-started_at")

    for r in running_qs:
        try:
            r.stop()
        except Exception:
            # fallback duro: ao menos encerra
            TimeEntry.objects.filter(pk=r.pk).update(ended_at=timezone.now())

    now = timezone.now()

    entry = TimeEntry.objects.create(
        user=request.user,
        project_id=project.id,
        activity_type_id=activity.id,
        card_id=card.id,
        board_id=card.column.board_id,
        card_title_cache=card.title,
        card_url_cache=(
        settings.SITE_URL.rstrip("/")
        + reverse("boards:board_detail", kwargs={"board_id": card.column.board_id})
        + f"?card={card.id}"
    ),

        started_at=now,
        minutes=0,
    )

    entry.set_confirmation_window(now=now)
    entry.save(update_fields=["confirm_due_at", "auto_stop_at"])

        # ✅ WhatsApp (MVP): dispara mensagem no start, sem quebrar o track-time se falhar
       # ✅ WhatsApp no START (2 mensagens: comunicado + link puro)
    try:
        prof = _get_or_create_profile(request.user)
        phone = (prof.telefone or "").strip()

        if phone and settings.PRESSTICKET_TOKEN:
            card_url = (entry.card_url_cache or "").strip()
            if not card_url:
                card_url = (
                    settings.SITE_URL.rstrip("/")
                    + reverse("boards:board_detail", kwargs={"board_id": card.column.board_id})
                    + f"?card={card.id}"
                )

            msg1 = (
                f"⏱️ Início do Track-time\n"
                f"Card: {card.title}"
            )

            _send_whatsapp_two_messages(
                number=phone,
                message=msg1,
                url=card_url,  # 2ª mensagem: SOMENTE o link
            )

    except PressTicketError as e:
        logger.warning("[tracktime] WhatsApp START não enviado (PressTicketError): %s", e)
    except Exception as e:
        logger.exception("[tracktime] WhatsApp START não enviado (erro inesperado): %s", e)




    return card_tracktime_panel(request, card_id)


@login_required
def card_tracktime_stop(request, card_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    entry = (
        TimeEntry.objects
        .filter(user=request.user, ended_at__isnull=True)
        .order_by("-started_at")
        .first()
    )

    if entry:
        entry.stop()

       # ✅ WhatsApp no STOP (2 mensagens: comunicado + link puro)
        try:
            prof = _get_or_create_profile(request.user)
            phone = (prof.telefone or "").strip()

            if phone and settings.PRESSTICKET_TOKEN:
                card_url = (entry.card_url_cache or "").strip()
                title = (entry.card_title_cache or "").strip() or "Card"

                total_min = int(getattr(entry, "minutes", 0) or 0)

                msg1 = (
                    f"⏱️ Fim do Track-time\n"
                    f"Card: {title}\n"
                    f"Total: {total_min} min"
                )

                _send_whatsapp_two_messages(
                    number=phone,
                    message=msg1,
                    url=card_url,  # 2ª mensagem: SOMENTE o link
                )

        except PressTicketError as e:
            logger.warning("[tracktime] WhatsApp STOP não enviado (PressTicketError): %s", e)
        except Exception as e:
            logger.exception("[tracktime] WhatsApp STOP não enviado (erro inesperado): %s", e)


    return card_tracktime_panel(request, card_id)


@login_required
def card_tracktime_manual(request, card_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    card = get_object_or_404(
        Card.objects.select_related("column__board"),
        id=card_id
    )

    # ✅ segurança: só quem vê o board pode trackear no card
    if not _can_view_board(request.user, card.column.board):
        return HttpResponseForbidden("Sem acesso ao board deste card")

    project_id = (request.POST.get("project") or "").strip()
    activity_id = (request.POST.get("activity") or "").strip()
    minutes = (request.POST.get("minutes") or "").strip()

    if not project_id or not activity_id or not minutes:
        return HttpResponseBadRequest("Dados incompletos")

    try:
        minutes_int = int(minutes)
    except ValueError:
        return HttpResponseBadRequest("Minutos inválidos")

    if minutes_int <= 0:
        return HttpResponseBadRequest("Minutos inválidos")

    project = get_object_or_404(
        Project,
        pk=project_id,
        created_by=request.user,
        is_active=True
    )

    activity = get_object_or_404(
        ActivityType,
        pk=activity_id,
        created_by=request.user,
        is_active=True
    )

    now = timezone.now()

    TimeEntry.objects.create(
    user=request.user,
    project_id=project.id,
    activity_type_id=activity.id,
    minutes=minutes_int,
    started_at=now,
    ended_at=now,
    card_id=card.id,
    board_id=card.column.board_id,
    card_title_cache=card.title,
    card_url_cache=(
        settings.SITE_URL.rstrip("/")
        + reverse("boards:board_detail", kwargs={"board_id": card.column.board_id})
        + f"?card={card.id}"
    ),
)


    return card_tracktime_panel(request, card_id)


@login_required
def card_tracktime_confirm_extend(request, card_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    entry = (
        TimeEntry.objects
        .filter(user=request.user, card_id=card_id, ended_at__isnull=True)
        .order_by("-started_at")
        .first()
    )
    if not entry:
        return HttpResponseBadRequest("Nenhum timer ativo para este card")

    entry.extend_one_hour(now=timezone.now())
    return card_tracktime_panel(request, card_id)


def tracktime_confirm_link(request, entry_id, token):
    entry = get_object_or_404(TimeEntry, id=entry_id)

    if request.user.is_authenticated and request.user != entry.user:
        return HttpResponseForbidden("Acesso negado")

    if not entry.is_running:
        return redirect("boards:board_detail", board_id=entry.board_id or 0)

    if not entry.check_confirmation_token(token):
        return HttpResponseForbidden("Token inválido ou expirado")

    entry.confirmation_token_hash = ""
    entry.extend_one_hour(now=timezone.now())

    board_id = entry.board_id
    card_id = entry.card_id

    if not board_id and card_id:
        try:
            c = Card.objects.select_related("column").get(id=card_id)
            board_id = c.column.board_id
        except Exception:
            board_id = None

    if not board_id:
        return redirect("/")

    url = reverse("boards:board_detail", kwargs={"board_id": board_id})
    return redirect(f"{url}?card={card_id}&tab=tracktime")


# ============================================================
# Portal (cadastros MVP)
# ============================================================

@login_required
def portal(request):
    projects = Project.objects.filter(created_by=request.user).order_by("name")
    activities = ActivityType.objects.filter(created_by=request.user).order_by("name")

    if request.method == "POST":
        if "project_name" in request.POST:
            name = (request.POST.get("project_name") or "").strip()
            if name:
                _get_or_create_project_for_user(user=request.user, name=name)

        if "activity_name" in request.POST:
            name = (request.POST.get("activity_name") or "").strip()
            if name:
                _get_or_create_activity_type_for_user(user=request.user, name=name)

        return redirect("tracktime:portal")



    return render(
        request,
        "tracktime/portal.html",
        {
            "projects": projects,
            "activities": activities,
        },
    )


def _redirect_back(request, fallback_url_name: str):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt:
        return redirect(nxt)
    ref = request.META.get("HTTP_REFERER")
    if ref:
        return redirect(ref)
    return redirect(reverse(fallback_url_name))


@login_required
def toggle_project(request, pk):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    p = get_object_or_404(Project, pk=pk, created_by=request.user)
    p.is_active = not p.is_active
    p.save(update_fields=["is_active"])

    return _redirect_back(request, "tracktime:portal")

@login_required
def toggle_activity(request, pk):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    a = get_object_or_404(ActivityType, pk=pk, created_by=request.user)
    a.is_active = not a.is_active
    a.save(update_fields=["is_active"])

    return _redirect_back(request, "tracktime:portal")



# ============================================================
# Board running badge (NÃO é o live modal)
# ============================================================

@login_required
def board_running(request, board_id: int):
    """
    Retorna timers rodando no board, para desenhar badge em tempo real.
    Saída: { "cards": { "<card_id>": [ {user, elapsed_seconds}, ...] } }
    """
    board = get_object_or_404(Board, id=board_id)
    if not _can_view_board(request.user, board):
        return HttpResponseForbidden("Sem acesso ao board")

    now = timezone.now()

    qs = (
        TimeEntry.objects
        .filter(board_id=board_id, ended_at__isnull=True)
        .select_related("user")
        .only("id", "card_id", "started_at", "user__email", "user__first_name", "user__last_name")
    )

    cards = {}
    for e in qs:
        if not e.card_id or not e.started_at:
            continue

        elapsed = int((now - e.started_at).total_seconds())

        name = (getattr(e.user, "get_full_name", lambda: "")() or "").strip()
        if not name:
            name = (getattr(e.user, "email", "") or "Usuário").strip()

        cards.setdefault(str(e.card_id), []).append({
            "user": name,
            "elapsed_seconds": elapsed,
        })

    return JsonResponse({
        "board_id": board_id,
        "cards": cards,
        "ts": now.isoformat(),
    })


# ============================================================
# Modal Tracktime (abas)
# ============================================================

@login_required
def tracktime_modal(request):
    tab = (request.GET.get("tab") or "live").strip().lower()
    if tab not in {"live", "portal", "week", "month"}:
        tab = "live"
    return render(request, "tracktime/modal/tracktime_modal.html", {"tab": tab})



@login_required
def tracktime_tab_portal(request):
    projects = Project.objects.filter(created_by=request.user).order_by("name")
    activities = ActivityType.objects.filter(created_by=request.user).order_by("name")

    if request.method == "POST":
        if "project_name" in request.POST:
            name = (request.POST.get("project_name") or "").strip()
            if name:
                _get_or_create_project_for_user(user=request.user, name=name)

        if "activity_name" in request.POST:
            name = (request.POST.get("activity_name") or "").strip()
            if name:
                _get_or_create_activity_type_for_user(user=request.user, name=name)

        projects = Project.objects.filter(created_by=request.user).order_by("name")
        activities = ActivityType.objects.filter(created_by=request.user).order_by("name")


    return render(
        request,
        "tracktime/modal/tabs/portal.html",
        {"projects": projects, "activities": activities},
    )



@login_required
def tracktime_tab_live(request):
    return render(request, "tracktime/modal/tabs/live.html", {})


@login_required
def tracktime_live_json(request):
    """
    Retorna timers ativos em tempo real, filtrando para boards que o user pode ver.
    Formato:
    {
      "ts": "...",
      "boards": [
        {"board_id": 31, "board_name": "...", "items":[...]}
      ]
    }
    """
    now = timezone.now()
    from django.urls import reverse

    qs = (
        TimeEntry.objects
        .filter(
            ended_at__isnull=True,
            board_id__isnull=False,
            card_id__isnull=False,
            started_at__isnull=False,
        )
        .select_related("user", "user__profile")
        .order_by("-started_at")
    )


    by_board = {}
    boards_cache = {}

    for e in qs:
        board_id = e.board_id
        card_id = e.card_id

        if not board_id or not card_id:
            continue

        # cache board + permissão (barato)
        if board_id not in boards_cache:
            try:
                b = Board.objects.get(id=board_id)
            except Board.DoesNotExist:
                boards_cache[board_id] = None
            else:
                boards_cache[board_id] = b

        board = boards_cache.get(board_id)
        if not board:
            continue
        if not _can_view_board(request.user, board):
            continue

        # ✅ pega o card aqui (sem isso dá 500)
        try:
            card = (
                Card.objects
                .select_related("column", "column__board")
                .prefetch_related("checklists", "attachments")
                .get(id=card_id)
            )
        except Card.DoesNotExist:
            continue

        # por segurança: board real do card (não confia só no cache)
        board = card.column.board
        if not _can_view_board(request.user, board):
            continue

        elapsed = int((now - e.started_at).total_seconds())

        name = (getattr(e.user, "get_full_name", lambda: "")() or "").strip()
        if not name:
            name = (getattr(e.user, "email", "") or "Usuário").strip()

        board_key = str(board.id)

        by_board.setdefault(board_key, {
            "board_id": board.id,
            "board_name": board.name,
            "items": []
        })

        # ✅ link correto (abre o board com card=...)
        board_url = reverse("boards:board_detail", kwargs={"board_id": board.id})
        card_url = f"{board_url}?card={card.id}"

        # descrição (evita AttributeError se o campo não existir)
        card_description = (getattr(card, "description", None) or "").strip()

        # capa (evita AttributeError / storage)
        card_cover = None
        cover_field = getattr(card, "cover_image", None)
        if cover_field:
            try:
                card_cover = cover_field.url
            except Exception:
                card_cover = None
        from django.templatetags.static import static as static_url

        profile = getattr(e.user, "profile", None)

        # identidade (nome amigável / email / handle)
        user_display = (getattr(e.user, "get_full_name", lambda: "")() or "").strip()
        if profile and getattr(profile, "display_name", ""):
            user_display = (profile.display_name or "").strip() or user_display

        if not user_display:
            user_display = (getattr(e.user, "email", "") or "Usuário").strip()

        user_handle = ""
        if profile and getattr(profile, "handle", None):
            user_handle = (profile.handle or "").strip()

        # avatar
        user_avatar_url = ""
        if profile:
            av = getattr(profile, "avatar", None)
            if av and getattr(av, "url", None):
                user_avatar_url = av.url
            elif getattr(profile, "avatar_choice", ""):
                user_avatar_url = static_url(f"images/avatar/{profile.avatar_choice}")

        # datas do card
        start_date = getattr(card, "start_date", None)
        warn_date = getattr(card, "due_warn_date", None)
        due_date = getattr(card, "due_date", None)

        by_board[board_key]["items"].append({
            "entry_id": e.id,
            "card_id": card.id,
            "card_title": card.title,
            "card_url": card_url,
            "card_cover": card_cover,
            "card_description": card_description,
            "started_at": e.started_at.isoformat(),

            "has_checklist": card.checklists.exists(),
            "has_attachments": card.attachments.exists(),

            # ✅ usuário completo
            "user": user_display,
            "user_handle": user_handle,
            "user_avatar_url": user_avatar_url,

            # ✅ datas do card
            "start_date": start_date.isoformat() if start_date else None,
            "warn_date": warn_date.isoformat() if warn_date else None,
            "due_date": due_date.isoformat() if due_date else None,

            "elapsed_seconds": elapsed,
        })


    # Ordena: boards por nome, itens por maior tempo
    boards = sorted(by_board.values(), key=lambda x: (x.get("board_name") or "").lower())
    for b in boards:
        b["items"].sort(key=lambda it: it.get("elapsed_seconds", 0), reverse=True)

    return JsonResponse({"ts": now.isoformat(), "boards": boards})


@login_required
def tracktime_tab_week(request):
    return render(request, "tracktime/modal/tabs/week.html", {})


@login_required
def tracktime_tab_month(request):
    return render(request, "tracktime/modal/tabs/month.html", {})


@login_required
def me_running_json(request):
    """
    Retorna o card/board do timer rodando do usuário logado (se existir).
    """
    e = (
        TimeEntry.objects
        .filter(
            user=request.user,
            ended_at__isnull=True,
            board_id__isnull=False,
            card_id__isnull=False,
            started_at__isnull=False,
        )
        .order_by("-started_at")
        .only("board_id", "card_id", "started_at")
        .first()
    )

    if not e:
        return JsonResponse({"running": False})

    return JsonResponse({
        "running": True,
        "board_id": int(e.board_id),
        "card_id": int(e.card_id),
        "ts": timezone.now().isoformat(),
    })


@login_required
def card_tracktime_panel_running_slot(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    running = (
        TimeEntry.objects
        .filter(card_id=card.id, user=request.user, ended_at__isnull=True)
        .first()
    )

    now = timezone.now()
    elapsed_seconds = 0
    confirm_needed = False
    confirm_due_in = None
    auto_stop_in = None

    if running and running.started_at:
        elapsed_seconds = int((now - running.started_at).total_seconds())
        confirm_needed = running.needs_confirmation(now=now)

        if running.confirm_due_at:
            confirm_due_in = int((running.confirm_due_at - now).total_seconds())
        if running.auto_stop_at:
            auto_stop_in = int((running.auto_stop_at - now).total_seconds())

    return render(
        request,
        "tracktime/partials/card_tracktime_running_slot.html",
        {
            "card": card,
            "running": running,
            "elapsed_seconds": elapsed_seconds,
            "elapsed_mmss": _format_mmss(elapsed_seconds),
            "confirm_needed": confirm_needed,
            "confirm_due_in": confirm_due_in,
            "auto_stop_in": auto_stop_in,
            "auto_stop_mmss": _format_mmss(auto_stop_in) if auto_stop_in is not None else None,
        },
    )


@login_required
def card_elapsed_json(request, card_id: int):
    """
    Retorna o timer rodando do usuário.
    Se estiver rodando em OUTRO card, informa isso (pra não ficar '—' infinito).
    """
    now = timezone.now()

    running = (
        TimeEntry.objects
        .filter(user=request.user, ended_at__isnull=True, started_at__isnull=False)
        .order_by("-started_at")
        .first()
    )

    if not running:
        return JsonResponse({"running": False, "reason": "no_running"})

    # se está rodando mas em outro card, avisa
    running_card_id = int(running.card_id or 0)
    if running_card_id != int(card_id):
        return JsonResponse({
            "running": True,
            "in_this_card": False,
            "running_card_id": running_card_id,
            "reason": "running_other_card",
        })

    elapsed_seconds = int((now - running.started_at).total_seconds())
    started_local = timezone.localtime(running.started_at)
    started_hhmm = started_local.strftime("%H:%M")

    return JsonResponse({
        "running": True,
        "in_this_card": True,
        "started_hhmm": started_hhmm,
        "elapsed_mmss": _format_mmss(elapsed_seconds),
        "elapsed_seconds": elapsed_seconds,
        "ts": now.isoformat(),
    })

def _get_or_create_profile(user):
    prof = getattr(user, "profile", None)
    if prof:
        return prof
    prof, _ = UserProfile.objects.get_or_create(user=user)
    return prof


def _digits_only(s: str) -> str:
    return re.sub(r"\D+", "", (s or ""))


def _normalize_br_phone(ddd: str, phone: str):
    ddd_d = _digits_only(ddd)
    ph_d = _digits_only(phone)

    if len(ddd_d) != 2:
        return None, "DDD inválido. Informe exatamente 2 números (ex: 21)."

    if len(ph_d) not in (8, 9):
        return None, "Telefone inválido. Informe 8 ou 9 dígitos (ex: 999999999)."

    # formato PressTicket: 55DDDNÚMERO (somente dígitos)
    return f"55{ddd_d}{ph_d}", None


def _render_phone_required_modal(request, card_id: int, project_id: str, activity_id: str, error: str = ""):
    html = render(
        request,
        "tracktime/partials/phone_required_modal.html",
        {
            "card_id": card_id,
            "project_id": project_id,
            "activity_id": activity_id,
            "error": error,
        },
    )
    # Força o modal a ir para o BODY, sem depender do hx-target que disparou o POST
    resp = HttpResponse(html)

    # joga o modal de telefone dentro do overlay do modal global (fica sempre acima)
    resp["HX-Retarget"] = "#modal"
    resp["HX-Reswap"] = "beforeend"

    return resp


@login_required
def tracktime_phone_required_modal(request):
    """
    Permite abrir o modal via GET (opcional).
    """
    card_id = int(request.GET.get("card_id") or 0)
    project_id = (request.GET.get("project_id") or "").strip()
    activity_id = (request.GET.get("activity_id") or "").strip()

    if not card_id or not project_id or not activity_id:
        return HttpResponseBadRequest("Dados incompletos para abrir o modal.")

    return _render_phone_required_modal(request, card_id, project_id, activity_id)


@login_required
def tracktime_phone_save(request):
    """
    Salva telefone no profile do usuário no formato 55DDDNÚMERO (somente dígitos).
    """
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    card_id = int((request.POST.get("card_id") or "0").strip() or 0)
    project_id = (request.POST.get("project_id") or "").strip()
    activity_id = (request.POST.get("activity_id") or "").strip()

    ddd = (request.POST.get("ddd") or "").strip()
    phone = (request.POST.get("phone") or "").strip()

    normalized, err = _normalize_br_phone(ddd, phone)
    if err:
        # mantém o modal aberto e exibe erro
        return _render_phone_required_modal(request, card_id, project_id, activity_id, error=err)

    prof = _get_or_create_profile(request.user)
    prof.telefone = normalized
    prof.save(update_fields=["telefone"])

    # HTMX: 204 OK sem conteúdo (o after-request do form dispara o start)
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204)

    # fallback não-HTMX: volta
    return redirect(request.META.get("HTTP_REFERER") or "/")







@login_required
@require_http_methods(["POST"])
def tracktime_presence_ping(request):
    tab = (request.POST.get("tab") or "").strip()[:40]
    path = (request.POST.get("path") or "").strip()[:200]

    now = timezone.now()
    TrackPresence.objects.update_or_create(
        user=request.user,
        defaults={"last_ping_at": now, "tab": tab, "path": path},
    )
    return JsonResponse({"ok": True, "ts": now.isoformat()})


@login_required
def tracktime_tab_online(request):
    return render(request, "tracktime/modal/tabs/online.html", {})


def _cardlog_to_text(log: CardLog) -> str:
    txt = (getattr(log, "content_text", "") or "").strip()
    if txt:
        return txt

    html = (getattr(log, "content", "") or "").strip()
    if html:
        return html  # deixa o frontend stripHtml limpar

    return "Atualização"




@login_required
def tracktime_online_json(request):
    now = timezone.now()

    # Quem "pode aparecer" no painel (presença recente)
    presence_after = now - timedelta(minutes=9)
    presences = (
        TrackPresence.objects
        .filter(last_ping_at__gte=presence_after)
        .select_related("user", "user__profile")
        .order_by("-last_ping_at")
    )

    user_ids = list(presences.values_list("user_id", flat=True))
    if not user_ids:
        return JsonResponse({"ts": now.isoformat(), "items": []})

    # 1) Timers rodando => sempre "ativo" (independente de 9 min)
    running_qs = (
        TimeEntry.objects
        .filter(ended_at__isnull=True, user_id__in=user_ids)
        .order_by("-started_at")
        .only("user_id", "started_at", "card_title_cache", "card_url_cache")
    )

    running_by_user = {}
    for e in running_qs:
        if e.user_id not in running_by_user:
            running_by_user[e.user_id] = {
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "card_title": (e.card_title_cache or "").strip(),
                "card_url": (e.card_url_cache or "").strip(),
            }

    # 2) Atividades (CardLog) nos últimos 9 minutos => "ativo"
    activity_after = now - timedelta(minutes=9)

    logs_qs = (
        CardLog.objects
        .filter(actor_id__in=user_ids, created_at__gte=activity_after)
        .select_related("card", "card__column", "card__column__board", "actor")
        .order_by("-created_at")
    )

    logs_by_user = {}
    for lg in logs_qs:
        lst = logs_by_user.setdefault(lg.actor_id, [])
        if len(lst) >= 20:
            continue

        card = getattr(lg, "card", None)
        board_id = None
        board_name = None
        card_title = None
        card_url = ""

        if card:
            card_title = (getattr(card, "title", "") or "").strip()
            col = getattr(card, "column", None)
            if col:
                board_id = getattr(col, "board_id", None)
                board = getattr(col, "board", None)
                if board:
                    board_name = (getattr(board, "name", "") or "").strip() or None

            if board_id:
                board_url = reverse("boards:board_detail", kwargs={"board_id": int(board_id)})
                card_url = f"{board_url}?card={int(card.id)}"

        text = _cardlog_to_text(lg)

        lst.append({
            "type": "cardlog",
            "at": lg.created_at.isoformat(),
            "text": text,  # ✅ sempre vem preenchido
            "content": (lg.content or "").strip(),  # opcional: mantém raw pra quill
            "card_id": getattr(card, "id", None),
            "card_title": card_title,
            "card_url": card_url,
            "board_id": board_id,
            "board_name": board_name,
        })


    items = []

    for p in presences:
        u = p.user
        prof = getattr(u, "profile", None)

        display = (getattr(u, "get_full_name", lambda: "")() or "").strip()
        if prof and getattr(prof, "display_name", ""):
            display = (prof.display_name or "").strip() or display
        if not display:
            display = (getattr(u, "email", "") or "Usuário").strip()

        handle = (getattr(prof, "handle", "") or "").strip() if prof else ""

        activities = []

        # timer rodando vira a primeira linha do histórico
        run = running_by_user.get(u.id)
        if run:
            t = (run.get("card_title") or "Card").strip()
            url = (run.get("card_url") or "").strip()
            activities.append({
                "type": "cardlog",
                "at": lg["at"],
                "text": lg.get("text") or "",     # ✅
                "content": lg.get("content") or "",  # opcional
                "card_title": lg.get("card_title"),
                "card_url": lg.get("card_url"),
                "board_name": lg.get("board_name"),
            })


        # logs recentes (<= 9 min)
        for lg in logs_by_user.get(u.id, []):
            # Texto amigável: remove HTML aqui no backend não é obrigatório;
            # o frontend já pode limpar, mas deixamos o conteúdo raw para flexibilidade.
            activities.append({
                "type": "cardlog",
                "at": lg["at"],
                "text": lg.get("text") or "",     # ✅
                "content": lg.get("content") or "",  # opcional
                "card_title": lg.get("card_title"),
                "card_url": lg.get("card_url"),
                "board_name": lg.get("board_name"),
            })


        # Regra do painel:
        # - se não tem timer rodando
        # - e não tem atividade nos últimos 9 min
        # => some
        if not activities:
            continue

        # ordena atividades por data desc
        activities.sort(key=lambda x: x.get("at") or "", reverse=True)

        last_activity_at = activities[0].get("at")

        items.append({
            "user_id": u.id,
            "user": display,
            "handle": handle,
            "last_ping_at": p.last_ping_at.isoformat(),
            "activities": activities[:20],
            "last_activity_at": last_activity_at,
        })

    # ordena por atividade mais recente
    items.sort(key=lambda x: x.get("last_activity_at") or "", reverse=True)

    return JsonResponse({"ts": now.isoformat(), "items": items})
