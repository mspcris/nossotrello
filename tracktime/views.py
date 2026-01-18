# tracktime/views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.conf import settings
from django.core.mail import send_mail
from .models import Project, ActivityType, TimeEntry
from boards.models import Card
from boards.models import Board
from .models import TimeEntry


def _format_mmss(seconds: int) -> str:
    seconds = max(int(seconds or 0), 0)
    mm = seconds // 60
    ss = seconds % 60
    return f"{mm}:{ss:02d}"


@login_required
def card_tracktime_panel(request, card_id):
    card = get_object_or_404(Card, id=card_id)

    projects = Project.objects.filter(is_active=True).order_by("name")
    activities = ActivityType.objects.filter(is_active=True).order_by("name")

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

    card = get_object_or_404(Card, id=card_id)

    project_id = request.POST.get("project")
    activity_id = request.POST.get("activity_type")

    if not project_id or not activity_id:
        return HttpResponseBadRequest("Projeto e atividade são obrigatórios")

    # 1 timer ativo por usuário (fecha qualquer outro)
    TimeEntry.objects.filter(
        user=request.user,
        ended_at__isnull=True,
    ).update(ended_at=timezone.now())

    now = timezone.now()

    entry = TimeEntry.objects.create(
        user=request.user,
        project_id=project_id,
        activity_type_id=activity_id,
        card_id=card.id,
        board_id=card.column.board_id,  # ✅ via column
        card_title_cache=card.title,
        card_url_cache=request.build_absolute_uri(reverse("boards:card_modal", args=[card.id])),
        started_at=now,
        minutes=0,
    )

    # janela de confirmação
    entry.set_confirmation_window(now=now)
    entry.save(update_fields=["confirm_due_at", "auto_stop_at"])

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

    return card_tracktime_panel(request, card_id)


@login_required
def card_tracktime_manual(request, card_id):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    card = get_object_or_404(Card, id=card_id)

    project_id = request.POST.get("project")
    activity_id = request.POST.get("activity_type")
    minutes = request.POST.get("minutes")

    if not project_id or not activity_id or not minutes:
        return HttpResponseBadRequest("Dados incompletos")

    try:
        minutes_int = int(minutes)
    except ValueError:
        return HttpResponseBadRequest("Minutos inválidos")

    if minutes_int <= 0:
        return HttpResponseBadRequest("Minutos inválidos")

    TimeEntry.objects.create(
        user=request.user,
        project_id=project_id,
        activity_type_id=activity_id,
        minutes=minutes_int,
        started_at=timezone.now(),
        ended_at=timezone.now(),
        card_id=card.id,
        board_id=card.column.board_id,  # ✅ via column
        card_title_cache=card.title,
        card_url_cache=request.build_absolute_uri(reverse("boards:card_modal", args=[card.id])),
    )

    return card_tracktime_panel(request, card_id)


@login_required
def card_tracktime_confirm_extend(request, card_id):
    """
    CTA do modal: "Ainda estou na tarefa (+1h)".
    """
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
    """
    Link do e-mail: confirma +1h.
    Não exige login, mas se estiver logado com outro usuário, bloqueia.
    """
    entry = get_object_or_404(TimeEntry, id=entry_id)

    if request.user.is_authenticated and request.user != entry.user:
        return HttpResponseForbidden("Acesso negado")

    if not entry.is_running:
        # já parou
        return redirect("boards:board_detail", board_id=entry.board_id or 0)

    if not entry.check_confirmation_token(token):
        return HttpResponseForbidden("Token inválido ou expirado")

    # uso único
    entry.confirmation_token_hash = ""
    entry.extend_one_hour(now=timezone.now())

    # redireciona para o board abrindo o card no tab tracktime
    board_id = entry.board_id
    card_id = entry.card_id

    if not board_id and card_id:
        try:
            c = Card.objects.get(id=card_id)
            board_id = c.column.board_id
        except Exception:
            board_id = None

    if not board_id:
        # fallback
        return redirect("/")

    url = reverse("boards:board_detail", kwargs={"board_id": board_id})
    return redirect(f"{url}?card={card_id}&tab=tracktime")


# =========================
# Portal (cadastros MVP)
# =========================

@login_required
def portal(request):
    projects = Project.objects.all().order_by("name")
    activities = ActivityType.objects.all().order_by("name")

    if request.method == "POST":
        if "project_name" in request.POST:
            name = (request.POST.get("project_name") or "").strip()
            if name:
                Project.objects.create(name=name)

        if "activity_name" in request.POST:
            name = (request.POST.get("activity_name") or "").strip()
            if name:
                ActivityType.objects.create(name=name)

        return redirect("tracktime:portal")

    return render(
        request,
        "tracktime/portal.html",
        {
            "projects": projects,
            "activities": activities,
        },
    )


@login_required
def toggle_project(request, pk):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    p = get_object_or_404(Project, pk=pk)
    p.is_active = not p.is_active
    p.save(update_fields=["is_active"])

    return redirect("tracktime:portal")


@login_required
def toggle_activity(request, pk):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    a = get_object_or_404(ActivityType, pk=pk)
    a.is_active = not a.is_active
    a.save(update_fields=["is_active"])

    return redirect("tracktime:portal")



def _can_view_board(user, board) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    memberships_qs = getattr(board, "memberships", None)
    if memberships_qs is None:
        return False

    # board compartilhado: basta estar na membership
    if memberships_qs.exists():
        return memberships_qs.filter(user=user).exists()

    # board legado: somente criador
    return bool(getattr(board, "created_by_id", None) == user.id)


@login_required
def board_running(request, board_id: int):
    """
    Retorna timers rodando no board, para desenhar badge em tempo real.
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

    # agrupa por card
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


from django.http import JsonResponse, HttpResponseForbidden
from django.template.loader import render_to_string
from boards.models import Board
from django.db.models import Q

def _can_view_board(user, board) -> bool:
    if not user.is_authenticated:
        return False
    if getattr(user, "is_superuser", False):
        return True

    memberships_qs = getattr(board, "memberships", None)
    if memberships_qs is not None:
        return memberships_qs.filter(user=user).exists()

    # fallback legado (se existir)
    return bool(getattr(board, "created_by_id", None) == user.id)


@login_required
def tracktime_modal(request):
    """
    Container do modal com abas.
    O conteúdo das abas é carregado via HTMX para manter padrão do app.
    """
    return render(request, "tracktime/modal/tracktime_modal.html", {})


@login_required
def tracktime_tab_portal(request):
    projects = Project.objects.all().order_by("name")
    activities = ActivityType.objects.all().order_by("name")
    return render(
        request,
        "tracktime/modal/tabs/portal.html",
        {"projects": projects, "activities": activities},
    )


@login_required
def tracktime_tab_live(request):
    """
    Aba HTML (lista vazia + container). A lista é preenchida via polling em JSON.
    """
    return render(request, "tracktime/modal/tabs/live.html", {})


@login_required
def tracktime_live_json(request):
    """
    Retorna timers ativos em tempo real, filtrando para boards que o user pode ver.
    MVP: busca por board_id e valida acesso board a board.
    """
    now = timezone.now()

    # Puxa todos os running (otimização MVP: dá para limitar por boards do usuário depois)
    qs = (
        TimeEntry.objects
        .filter(ended_at__isnull=True, board_id__isnull=False)
        .select_related("user")
        .only("id", "board_id", "card_id", "started_at", "card_title_cache", "card_url_cache",
              "user__email", "user__first_name", "user__last_name")
        .order_by("-started_at")
    )

    # Agrupa por board e filtra por permissão
    by_board = {}
    boards_cache = {}

    for e in qs:
        board_id = e.board_id
        if not board_id or not e.card_id or not e.started_at:
            continue

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

        elapsed = int((now - e.started_at).total_seconds())

        name = (getattr(e.user, "get_full_name", lambda: "")() or "").strip()
        if not name:
            name = (getattr(e.user, "email", "") or "Usuário").strip()

        by_board.setdefault(str(board_id), {
            "board_id": board_id,
            "board_name": getattr(board, "name", f"Board {board_id}"),
            "items": []
        })

        by_board[str(board_id)]["items"].append({
            "entry_id": e.id,
            "card_id": e.card_id,
            "card_title": e.card_title_cache or "(sem título)",
            "card_url": e.card_url_cache or "",
            "user": name,
            "elapsed_seconds": elapsed,
        })

    # Ordena: boards por nome, itens por maior tempo
    boards = sorted(by_board.values(), key=lambda x: x["board_name"].lower())
    for b in boards:
        b["items"].sort(key=lambda it: it["elapsed_seconds"], reverse=True)

    return JsonResponse({"ts": now.isoformat(), "boards": boards})


@login_required
def tracktime_tab_week(request):
    # MVP placeholder (próxima entrega: agregação por semana)
    return render(request, "tracktime/modal/tabs/week.html", {})


@login_required
def tracktime_tab_month(request):
    # MVP placeholder (próxima entrega: agregação por mês)
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
