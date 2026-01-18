from django.shortcuts import render, get_object_or_404
from django.http import HttpResponseBadRequest
from django.utils import timezone
from django.contrib.auth.decorators import login_required

from .models import Project, ActivityType, TimeEntry
from boards.models import Card


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

    return render(
        request,
        "tracktime/card_tracktime_panel.html",
        {
            "card": card,
            "projects": projects,
            "activities": activities,
            "entries": entries,
            "running": running,
        },
    )


@login_required
def card_tracktime_start(request, card_id):
    if request.method != "POST":
        return HttpResponseBadRequest()

    card = get_object_or_404(Card, id=card_id)

    project_id = request.POST.get("project")
    activity_id = request.POST.get("activity")

    if not project_id or not activity_id:
        return HttpResponseBadRequest("Projeto e atividade são obrigatórios")

    # impede dois timers ativos
    TimeEntry.objects.filter(
        user=request.user,
        ended_at__isnull=True,
    ).update(ended_at=timezone.now())

    TimeEntry.objects.create(
        user=request.user,
        project_id=project_id,
        activity_type_id=activity_id,
        card_id=card.id,
        board_id=card.list.board.id,
        card_title_cache=card.title,
        card_url_cache=request.build_absolute_uri(card.get_absolute_url()),
        started_at=timezone.now(),
        minutes=0,
    )

    return card_tracktime_panel(request, card_id)


@login_required
def card_tracktime_stop(request, card_id):
    if request.method != "POST":
        return HttpResponseBadRequest()

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
        return HttpResponseBadRequest()

    card = get_object_or_404(Card, id=card_id)

    project_id = request.POST.get("project")
    activity_id = request.POST.get("activity")
    minutes = request.POST.get("minutes")

    if not project_id or not activity_id or not minutes:
        return HttpResponseBadRequest("Dados incompletos")

    try:
        minutes = int(minutes)
    except ValueError:
        return HttpResponseBadRequest("Minutos inválidos")

    TimeEntry.objects.create(
        user=request.user,
        project_id=project_id,
        activity_type_id=activity_id,
        minutes=minutes,
        started_at=timezone.now(),
        ended_at=timezone.now(),
        card_id=card.id,
        board_id=card.list.board.id,
        card_title_cache=card.title,
        card_url_cache=request.build_absolute_uri(card.get_absolute_url()),
    )

    return card_tracktime_panel(request, card_id)


from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from .models import Project, ActivityType


@login_required
def portal(request):
    projects = Project.objects.all().order_by("name")
    activities = ActivityType.objects.all().order_by("name")

    if request.method == "POST":
        if "project_name" in request.POST:
            name = request.POST.get("project_name").strip()
            if name:
                Project.objects.create(name=name)

        if "activity_name" in request.POST:
            name = request.POST.get("activity_name").strip()
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
    if request.method == "POST":
        p = get_object_or_404(Project, pk=pk)
        p.is_active = not p.is_active
        p.save()
    return redirect("tracktime:portal")


@login_required
def toggle_activity(request, pk):
    if request.method == "POST":
        a = get_object_or_404(ActivityType, pk=pk)
        a.is_active = not a.is_active
        a.save()
    return redirect("tracktime:portal")
