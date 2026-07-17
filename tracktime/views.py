# tracktime/views.py

import json
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse, HttpResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.conf import settings
from django.core.mail import send_mail
from django.utils.html import escape
from .models import Project, ActivityType, TimeEntry
from boards.models import Card, Board, CardLog
import re
from boards.models import UserProfile
import threading
from tracktime.services.evolution import send_text_message as evolution_send, EvolutionError
import logging
from django.db import IntegrityError, transaction
from django.db.models import Max, Sum
from django.views.decorators.http import require_http_methods
from datetime import timedelta
from django.contrib.auth import get_user_model
User = get_user_model()
from .models import TrackPresence
from tracktime.services.notifications import notify_tracktime_extended

from boards.services.notifications import (
    get_board_recipients_for_card,
    get_card_followers,
    build_card_snapshot,
    format_card_message,
    notify_users_for_card,
)





logger = logging.getLogger(__name__)


def _actor_handle(user) -> str:
    """Retorna @handle, display_name ou username do usuário."""
    try:
        prof = getattr(user, "profile", None)
        if prof:
            if getattr(prof, "handle", None):
                return "@" + prof.handle.strip()
            if getattr(prof, "display_name", None):
                return prof.display_name.strip()
    except Exception:
        pass
    return getattr(user, "username", None) or getattr(user, "email", "?")


def _log_tracktime_feed(*, card, user, html_message: str) -> None:
    """Registra no feed do card como entrada de sistema (sem content_text/delta)."""
    try:
        CardLog.objects.create(
            card=card,
            actor=user,
            content=html_message,
            content_delta={},
            content_text="",
            attachment=None,
        )
    except Exception as exc:
        logger.exception("[tracktime] Falha ao gravar log no feed: %s", exc)


def _send_whatsapp_two_messages(*, number: str, message: str, url: str) -> None:
    """
    Sempre envia 2 mensagens:
    1) comunicado (message)
    2) somente link (url)
    """
    number = (number or "").strip()
    message = (message or "").strip()
    url = (url or "").strip()

    base_url = (getattr(settings, "EVOLUTION_BASE_URL", "") or "").strip()
    api_key = (getattr(settings, "EVOLUTION_API_KEY", "") or "").strip()
    instance = (getattr(settings, "EVOLUTION_INSTANCE", "") or "").strip()

    if not number or not (base_url and api_key and instance):
        return

    def _send(body):
        try:
            evolution_send(base_url=base_url, api_key=api_key, instance=instance, number=number, body=body)
            logger.info("evolution: sent ok number=%r", number)
        except EvolutionError as e:
            logger.warning("evolution: send failed number=%r: %s", number, e)
        except Exception as e:
            logger.warning("evolution: send failed number=%r: %s", number, e)

    if message:
        threading.Thread(target=_send, args=(message,), daemon=True).start()
    if url:
        threading.Thread(target=_send, args=(url,), daemon=True).start()


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

    # Agrega minutos por usuário (todos os lançamentos, não só os 10 últimos)
    per_user_qs = (
        TimeEntry.objects
        .filter(card_id=card.id, ended_at__isnull=False)
        .values("user__id", "user__email", "user__first_name", "user__last_name")
        .annotate(total_minutes=Sum("minutes"))
        .order_by("-total_minutes")
    )
    chart_labels = []
    chart_minutes = []
    for row in per_user_qs:
        fname = (row.get("user__first_name") or "").strip()
        lname = (row.get("user__last_name") or "").strip()
        label = (f"{fname} {lname}").strip() or (row.get("user__email") or "?")
        chart_labels.append(label)
        chart_minutes.append(int(row["total_minutes"] or 0))

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
            "chart_labels_json": json.dumps(chart_labels, ensure_ascii=False),
            "chart_minutes_json": json.dumps(chart_minutes),
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
      

        # HTMX: abre modal (não redireciona para fragmento sem layout)
        if request.headers.get("HX-Request"):
            return _render_phone_required_modal(request, card_id, project_id, activity_id)

        # fallback não-HTMX: manda para uma página “de verdade” (com base/layout)
        return redirect(reverse("tracktime:portal") + "?reason=phone_required")



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
        card_title_cache=(card.title or "")[:500],  # coluna é CharField(500); title é TextField
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

    # Feed do card — entrada de sistema
    _log_tracktime_feed(
        card=card,
        user=request.user,
        html_message=(
            f"<p><strong>{escape(_actor_handle(request.user))}</strong>"
            f" iniciou track-time: {escape(project.name)} / {escape(activity.name)}.</p>"
        ),
    )

        # ✅ WhatsApp (MVP): dispara mensagem no start, sem quebrar o track-time se falhar
       # ✅ WhatsApp no START (2 mensagens: comunicado + link puro)
    try:
        # Regra: track-time notifica o autor SEMPRE + seguidores do card
        followers = get_card_followers(card=card)
        recipients = followers[:]
        if request.user not in recipients:
            recipients.insert(0, request.user)


        snap = build_card_snapshot(card=card)
        msg = format_card_message(
            title_prefix="⏱️ Início do Track-time",
            snap=snap,
        )

        notify_users_for_card(
            card=card,
            recipients=recipients,
            subject=f"Início do Track-time: {snap.title}",
            message=msg,
            snap=snap,
            include_link_as_second_whatsapp_message=True,
            exclude_actor=False,
            actor=entry.user,
        )




    except Exception as e:
        logger.exception("[tracktime] Notificação START falhou: %s", e)





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

        card = None
        try:
            card = Card.objects.select_related("column__board").get(id=entry.card_id)
        except Exception:
            card = None
        if not card:
            return card_tracktime_panel(request, card_id)


       # ✅ WhatsApp no STOP (2 mensagens: comunicado + link puro)
        try:
            followers = get_card_followers(card=card)
            recipients = followers[:]
            if request.user not in recipients:
                recipients.insert(0, request.user)


            snap = build_card_snapshot(card=card)
            total_min = int(getattr(entry, "minutes", 0) or 0)

            msg = format_card_message(
                title_prefix="⏱️ Fim do Track-time",
                snap=snap,
                extra_lines=[f"Total: {total_min} min"],
            )

            notify_users_for_card(
                card=card,
                recipients=recipients,
                subject=f"Fim do Track-time: {snap.title}",
                message=msg,
                snap=snap,
                include_link_as_second_whatsapp_message=True,
                exclude_actor=False,   # autor DEVE ser notificado no track-time
                actor=entry.user,
            )


        except Exception as e:
            logger.exception("[tracktime] Notificação STOP falhou: %s", e)

        # Feed do card — entrada de sistema
        total_min = int(getattr(entry, "minutes", 0) or 0)
        proj_name = escape(getattr(getattr(entry, "project", None), "name", "") or "")
        act_name  = escape(getattr(getattr(entry, "activity_type", None), "name", "") or "")
        if total_min >= 60:
            h, m = divmod(total_min, 60)
            dur = f"{h}h {m:02d}min" if m else f"{h}h"
        else:
            dur = f"{total_min} min"
        context = f" — {proj_name} / {act_name}" if (proj_name or act_name) else ""
        _log_tracktime_feed(
            card=card,
            user=request.user,
            html_message=(
                f"<p><strong>{escape(_actor_handle(request.user))}</strong>"
                f" encerrou track-time{context}: {escape(dur)}.</p>"
            ),
        )

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
    card_title_cache=(card.title or "")[:500],  # coluna é CharField(500); title é TextField
    card_url_cache=(
        settings.SITE_URL.rstrip("/")
        + reverse("boards:board_detail", kwargs={"board_id": card.column.board_id})
        + f"?card={card.id}"
    ),
)

    # Feed do card — lançamento manual
    if minutes_int >= 60:
        h, m = divmod(minutes_int, 60)
        dur = f"{h}h {m:02d}min" if m else f"{h}h"
    else:
        dur = f"{minutes_int} min"
    _log_tracktime_feed(
        card=card,
        user=request.user,
        html_message=(
            f"<p><strong>{escape(_actor_handle(request.user))}</strong>"
            f" lançou track-time manual: {escape(project.name)} / {escape(activity.name)}"
            f" — {escape(dur)}.</p>"
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
    try:
        card = Card.objects.select_related("column__board").get(id=entry.card_id)
        followers = get_card_followers(card=card)
        recipients = followers[:]
        if entry.user not in recipients:
            recipients.insert(0, request.user)


        snap = build_card_snapshot(card=card)

        msg = format_card_message(
            title_prefix="✅ Track-time estendido em +1 hora",
            snap=snap,
        )

        notify_users_for_card(
            card=card,
            recipients=recipients,
            subject=f"Track-time estendido: {snap.title}",
            message=msg,
            snap=snap,
            include_link_as_second_whatsapp_message=True,
            exclude_actor=False,   # autor DEVE ser notificado no track-time
            actor=entry.user,
        )


    except Exception as e:
        logger.exception("[tracktime] Notificação CONFIRM (+1h) falhou: %s", e)

    try:
        notify_tracktime_extended(entry=entry)
    except Exception:
        logger.exception("[tracktime] notify extend failed entry_id=%s", entry.id)


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

def _resolve_tracktime_tab(request):
    """Retorna (tab, url_do_conteudo_da_tab) a partir de ?tab=."""
    tab = (request.GET.get("tab") or "live").strip().lower()
    if tab not in {"live", "day", "portal", "week", "month", "online"}:
        tab = "live"
    return tab, reverse(f"tracktime:tab_{tab}")


@login_required
def tracktime_modal(request):
    tab, tab_url = _resolve_tracktime_tab(request)

    # Acesso direto pela URL (sem HTMX) → página completa, com layout
    if not request.headers.get("HX-Request"):
        return redirect(f'{reverse("tracktime:page")}?tab={tab}')

    return render(
        request,
        "tracktime/modal/tracktime_modal.html",
        {"tab": tab, "initial_tab_url": tab_url},
    )


@login_required
def tracktime_page(request):
    """Página do Track-time com URL própria — F5 mantém você aqui (?tab=...)."""
    tab, tab_url = _resolve_tracktime_tab(request)
    return render(
        request,
        "tracktime/page.html",
        {"tab": tab, "initial_tab_url": tab_url, "page_mode": True},
    )



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


# ======================================================================
# LIMITES DE TRACK-TIME (admin) — tempo até o auto-encerramento por usuário
# ======================================================================

TRACKTIME_SYSTEM_DEFAULT_MIN = 60  # espelha _user_limit_minutes() em models.py


def _is_tracktime_admin(user):
    """Só o Cristiano (ou superuser/staff) gere limites de track-time."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return True
    return (getattr(user, "email", "") or "").strip().lower() == "cristiano@camim.com.br"


@login_required
def tracktime_tab_limits(request):
    if not _is_tracktime_admin(request.user):
        return HttpResponseForbidden("Apenas o administrador pode ver os limites.")

    profiles = (
        UserProfile.objects.select_related("user")
        .order_by("display_name", "user__email")
    )
    rows = []
    for p in profiles:
        u = p.user
        if not u:
            continue
        name = (p.display_name or "").strip() or (u.get_full_name() or "").strip() or (u.email or u.get_username())
        limit = int(getattr(p, "tracktime_limit_minutes", 0) or 0)
        rows.append({
            "user_id": u.id,
            "name": name,
            "email": u.email or "",
            "handle": (getattr(p, "handle", "") or "").strip(),
            "limit": limit,  # 0 = usa o padrão
            "effective": limit if limit > 0 else TRACKTIME_SYSTEM_DEFAULT_MIN,
        })

    return render(request, "tracktime/modal/tabs/limits.html", {
        "rows": rows,
        "system_default": TRACKTIME_SYSTEM_DEFAULT_MIN,
    })


@login_required
@require_http_methods(["POST"])
def tracktime_set_user_limit(request):
    if not _is_tracktime_admin(request.user):
        return HttpResponseForbidden("Apenas o administrador pode alterar limites.")

    try:
        uid = int(request.POST.get("user_id") or 0)
        minutes = int(request.POST.get("minutes") or 0)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Parâmetros inválidos.")

    if minutes < 0 or minutes > 1440:
        return HttpResponseBadRequest("Minutos fora do intervalo (0–1440).")

    prof = UserProfile.objects.filter(user_id=uid).first()
    if not prof:
        return HttpResponseBadRequest("Usuário sem perfil.")

    prof.tracktime_limit_minutes = minutes
    prof.save(update_fields=["tracktime_limit_minutes"])

    effective = minutes if minutes > 0 else TRACKTIME_SYSTEM_DEFAULT_MIN
    return JsonResponse({"ok": True, "user_id": uid, "limit": minutes, "effective": effective})


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
def tracktime_closed_today_json(request):
    """Track-times ENCERRADOS hoje (ended_at = hoje), para a seção abaixo do Ao Vivo.

    Lista plana (o front já achata). Traz o tempo TOTAL trabalhado (minutes) em vez
    do cronômetro correndo. Só boards que o usuário pode ver; teto de 120 itens.
    """
    from django.templatetags.static import static as static_url
    from django.urls import reverse

    now = timezone.now()
    today = timezone.localdate()

    qs = (
        TimeEntry.objects
        .filter(ended_at__date=today, board_id__isnull=False, card_id__isnull=False)
        .select_related("user", "user__profile")
        .order_by("-ended_at")[:400]
    )

    board_ok = {}
    items = []
    for e in qs:
        bid = e.board_id
        if bid not in board_ok:
            b = Board.objects.filter(id=bid).first()
            board_ok[bid] = b if (b and _can_view_board(request.user, b)) else None
        board = board_ok.get(bid)
        if not board:
            continue

        profile = getattr(e.user, "profile", None)
        user_display = ""
        if profile and getattr(profile, "display_name", ""):
            user_display = (profile.display_name or "").strip()
        if not user_display:
            user_display = (getattr(e.user, "get_full_name", lambda: "")() or "").strip()
        if not user_display:
            user_display = (getattr(e.user, "email", "") or "Usuário").strip()

        user_handle = (getattr(profile, "handle", "") or "").strip() if profile else ""

        user_avatar_url = ""
        if profile:
            av = getattr(profile, "avatar", None)
            if av and getattr(av, "url", None):
                user_avatar_url = av.url
            elif getattr(profile, "avatar_choice", ""):
                user_avatar_url = static_url(f"images/avatar/{profile.avatar_choice}")

        board_url = reverse("boards:board_detail", kwargs={"board_id": board.id})
        card_url = f"{board_url}?card={e.card_id}" if e.card_id else ""

        items.append({
            "entry_id": e.id,
            "card_id": e.card_id,
            "card_title": e.card_title_cache or "(sem título)",
            "card_url": card_url,
            "board_name": board.name,
            "user": user_display,
            "user_handle": user_handle,
            "user_avatar_url": user_avatar_url,
            "minutes": int(e.minutes or 0),
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "ended_at": e.ended_at.isoformat() if e.ended_at else None,
        })

        if len(items) >= 120:
            break

    return JsonResponse({"ts": now.isoformat(), "items": items})


@login_required
def tracktime_today_totals_json(request):
    """Total de minutos trabalhados HOJE por usuário (soma de todos os tracks).

    Conta os concluídos hoje (minutes) + o tempo corrido dos que ainda rodam
    (começados hoje). Só boards que o usuário pode ver.
    """
    from django.templatetags.static import static as static_url

    now = timezone.now()
    today = timezone.localdate()

    board_ok = {}
    def _can(bid):
        if bid not in board_ok:
            b = Board.objects.filter(id=bid).first()
            board_ok[bid] = bool(b and _can_view_board(request.user, b))
        return board_ok[bid]

    totals = {}   # user_id -> minutos
    users = {}    # user_id -> User

    # concluídos hoje: soma o minutes gravado
    done = (
        TimeEntry.objects
        .filter(ended_at__date=today, board_id__isnull=False)
        .select_related("user", "user__profile")
    )
    for e in done:
        if not _can(e.board_id):
            continue
        totals[e.user_id] = totals.get(e.user_id, 0) + int(e.minutes or 0)
        users[e.user_id] = e.user

    # rodando (começados hoje): soma o tempo corrido até agora
    running = (
        TimeEntry.objects
        .filter(ended_at__isnull=True, started_at__date=today, board_id__isnull=False)
        .select_related("user", "user__profile")
    )
    for e in running:
        if not _can(e.board_id) or not e.started_at:
            continue
        mins = max(0, int((now - e.started_at).total_seconds() // 60))
        totals[e.user_id] = totals.get(e.user_id, 0) + mins
        users[e.user_id] = e.user

    items = []
    for uid, mins in totals.items():
        u = users.get(uid)
        if not u:
            continue
        prof = getattr(u, "profile", None)
        name = ""
        if prof and getattr(prof, "display_name", ""):
            name = (prof.display_name or "").strip()
        if not name:
            name = (getattr(u, "get_full_name", lambda: "")() or "").strip()
        if not name:
            name = (getattr(u, "email", "") or "Usuário").strip()

        avatar = ""
        if prof:
            av = getattr(prof, "avatar", None)
            if av and getattr(av, "url", None):
                avatar = av.url
            elif getattr(prof, "avatar_choice", ""):
                avatar = static_url(f"images/avatar/{prof.avatar_choice}")

        items.append({
            "user_id": uid,
            "user": name,
            "user_handle": (getattr(prof, "handle", "") or "").strip() if prof else "",
            "user_avatar_url": avatar,
            "minutes": int(mins),
        })

    items.sort(key=lambda x: x["minutes"], reverse=True)
    return JsonResponse({"ts": now.isoformat(), "items": items})


def _fmt_min(m):
    """Format integer minutes as 'Xh Ym' string."""
    h, rem = divmod(int(m or 0), 60)
    if h and rem:
        return f"{h}h {rem:02d}m"
    elif h:
        return f"{h}h"
    else:
        return f"{rem}m"


def _apply_report_filters(request, base_qs):
    """
    Filtros das abas de relatório (?u=<user_id> e ?p=<project_id>).
    Retorna (qs_filtrado, filter_users, filter_projects, sel_user, sel_project, filter_qs).
    As opções dos selects vêm do período SEM filtro, para permitir trocar de filtro.
    """
    u_param = (request.GET.get("u") or "").strip()
    p_param = (request.GET.get("p") or "").strip()

    filter_users = []
    seen_u = set()
    for row in base_qs.values(
        "user_id", "user__first_name", "user__last_name",
        "user__email", "user__profile__display_name",
    ).distinct():
        uid = row["user_id"]
        if not uid or uid in seen_u:
            continue
        seen_u.add(uid)
        full = f'{(row.get("user__first_name") or "").strip()} {(row.get("user__last_name") or "").strip()}'.strip()
        name = ((row.get("user__profile__display_name") or "").strip()
                or full
                or (row.get("user__email") or "?"))
        filter_users.append({"id": uid, "name": name})
    filter_users.sort(key=lambda x: x["name"].lower())

    filter_projects = []
    seen_p = set()
    for row in base_qs.values("project_id", "project__name").distinct():
        pid = row["project_id"]
        if not pid or pid in seen_p:
            continue
        seen_p.add(pid)
        filter_projects.append({"id": pid, "name": (row.get("project__name") or "?")})
    filter_projects.sort(key=lambda x: x["name"].lower())

    sel_user = int(u_param) if u_param.isdigit() else None
    sel_project = int(p_param) if p_param.isdigit() else None

    qs = base_qs
    if sel_user:
        qs = qs.filter(user_id=sel_user)
    if sel_project:
        qs = qs.filter(project_id=sel_project)

    filter_qs = ""
    if sel_user:
        filter_qs += f"&u={sel_user}"
    if sel_project:
        filter_qs += f"&p={sel_project}"

    return qs, filter_users, filter_projects, sel_user, sel_project, filter_qs


def _report_filter_labels(filter_users, filter_projects, sel_user, sel_project):
    """Nomes amigáveis dos filtros selecionados (para título do relatório/CSV)."""
    user_name = next((u["name"] for u in filter_users if u["id"] == sel_user), None) if sel_user else None
    project_name = next((p["name"] for p in filter_projects if p["id"] == sel_project), None) if sel_project else None
    return user_name, project_name


def _report_csv_response(entries_list, filename):
    import csv
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.write("\ufeff")  # BOM para o Excel abrir com acentos corretos
    writer = csv.writer(resp, delimiter=";")
    writer.writerow(["Data", "Usuário", "Quadro", "Card", "Projeto", "Minutos", "Horas"])
    for e in entries_list:
        writer.writerow([
            e.get("date") or e.get("time") or "",
            e.get("user_name", ""),
            e.get("board_name", ""),
            e.get("card_title", ""),
            e.get("project_name", ""),
            e.get("minutes", 0),
            e.get("hours_display", ""),
        ])
    return resp


@login_required
def tracktime_tab_day(request):
    import datetime
    from collections import defaultdict

    d_param = request.GET.get("d", "")
    today = timezone.localdate()
    try:
        day = datetime.date.fromisoformat(d_param)
    except Exception:
        day = today

    prev_day = (day - datetime.timedelta(days=1)).isoformat()
    next_day_date = day + datetime.timedelta(days=1)
    next_day = next_day_date.isoformat() if next_day_date <= today else None

    PT_WEEKDAYS = [
        "Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
        "Sexta-feira", "Sábado", "Domingo"
    ]
    weekday_label = PT_WEEKDAYS[day.weekday()]
    is_today = (day == today)

    base_qs = (
        TimeEntry.objects
        .filter(created_at__date=day, minutes__gt=0)
        .select_related("user", "user__profile", "project")
        .order_by("-created_at")
    )
    entries_qs, filter_users, filter_projects, sel_user, sel_project, filter_qs = \
        _apply_report_filters(request, base_qs)
    entries = list(entries_qs)
    total_minutes = sum(e.minutes for e in entries)

    board_ids = {e.board_id for e in entries if e.board_id}
    from boards.models import Board
    board_name_map = {b.id: b.name for b in Board.objects.filter(id__in=board_ids).only("id", "name")} if board_ids else {}

    by_user = defaultdict(lambda: {"name": "", "handle": "", "minutes": 0, "count": 0})
    by_project = defaultdict(lambda: {"name": "", "minutes": 0})
    by_board = defaultdict(lambda: {"name": "", "minutes": 0})
    hour_minutes = defaultdict(int)

    entries_list = []
    for e in entries:
        u = e.user
        prof = getattr(u, "profile", None)
        name = ((getattr(prof, "display_name", "") or "").strip() or u.get_full_name() or u.get_username() or u.email or "?")
        handle = (getattr(prof, "handle", "") or "").strip()
        board_name = board_name_map.get(e.board_id, "") if e.board_id else ""
        proj_name = e.project.name if e.project else "(sem projeto)"

        uid = u.id
        by_user[uid]["name"] = name
        by_user[uid]["handle"] = handle
        by_user[uid]["minutes"] += e.minutes
        by_user[uid]["count"] += 1

        pid = e.project_id or 0
        by_project[pid]["name"] = proj_name
        by_project[pid]["minutes"] += e.minutes

        bid = e.board_id or 0
        by_board[bid]["name"] = board_name or "(sem quadro)"
        by_board[bid]["minutes"] += e.minutes

        local_dt = timezone.localtime(e.created_at)
        hour_minutes[local_dt.hour] += e.minutes

        entries_list.append({
            "date": f'{day.strftime("%d/%m/%Y")} {local_dt.strftime("%H:%M")}',
            "time": local_dt.strftime("%H:%M"),
            "user_name": name,
            "project_name": proj_name,
            "board_name": board_name,
            "card_title": e.card_title_cache or "",
            "card_url": e.card_url_cache or "",
            "minutes": e.minutes,
            "hours_display": _fmt_min(e.minutes),
            "deleted": e.is_card_deleted_cache,
        })

    # eixo de horas: da primeira à última hora com registro (mínimo 8h–18h pra não ficar vazio)
    if hour_minutes:
        h_start = min(min(hour_minutes), 8)
        h_end = max(max(hour_minutes), 18)
    else:
        h_start, h_end = 8, 18
    by_hour = [
        {"label": f"{h:02d}h", "minutes": hour_minutes.get(h, 0)}
        for h in range(h_start, h_end + 1)
    ]

    by_user_list = sorted(by_user.values(), key=lambda x: -x["minutes"])
    by_project_list = sorted(by_project.values(), key=lambda x: -x["minutes"])
    by_board_list = sorted(by_board.values(), key=lambda x: -x["minutes"])

    for item in by_user_list:
        item["hours_display"] = _fmt_min(item["minutes"])
        item["pct"] = round(item["minutes"] / total_minutes * 100) if total_minutes else 0
    for item in by_project_list:
        item["hours_display"] = _fmt_min(item["minutes"])
        item["pct"] = round(item["minutes"] / total_minutes * 100) if total_minutes else 0
    for item in by_board_list:
        item["hours_display"] = _fmt_min(item["minutes"])
        item["pct"] = round(item["minutes"] / total_minutes * 100) if total_minutes else 0

    if request.GET.get("export") == "csv":
        return _report_csv_response(entries_list, f"tracktime_{day.isoformat()}.csv")

    sel_user_name, sel_project_name = _report_filter_labels(
        filter_users, filter_projects, sel_user, sel_project
    )
    period_label = ("Hoje — " if is_today else "") + f"{weekday_label}, {day.strftime('%d/%m/%Y')}"

    ctx = {
        "day": day,
        "is_today": is_today,
        "weekday_label": weekday_label,
        "prev_day": prev_day, "next_day": next_day,
        "total_minutes": total_minutes,
        "total_hours_display": _fmt_min(total_minutes),
        "num_users": len(by_user),
        "num_entries": len(entries_list),
        "by_user": by_user_list,
        "by_project": by_project_list,
        "by_board": by_board_list,
        "by_hour": by_hour,
        "entries": entries_list,
        "has_data": total_minutes > 0,
        "filter_users": filter_users, "filter_projects": filter_projects,
        "sel_user": sel_user, "sel_project": sel_project,
        "sel_user_name": sel_user_name, "sel_project_name": sel_project_name,
        "filter_qs": filter_qs,
        "period_label": period_label,
        "period_param": f"d={day.isoformat()}",
    }
    if request.GET.get("print") == "1":
        return render(request, "tracktime/modal/tabs/print.html", ctx)
    return render(request, "tracktime/modal/tabs/day.html", ctx)


@login_required
def tracktime_tab_week(request):
    import datetime
    from django.db.models import Sum
    from collections import defaultdict

    w_param = request.GET.get("w", "")
    try:
        week_start = datetime.date.fromisoformat(w_param)
        week_start -= datetime.timedelta(days=week_start.weekday())
    except Exception:
        today = timezone.localdate()
        week_start = today - datetime.timedelta(days=today.weekday())

    week_end = week_start + datetime.timedelta(days=6)
    prev_week = (week_start - datetime.timedelta(days=7)).isoformat()
    today = timezone.localdate()
    next_week_start = week_start + datetime.timedelta(days=7)
    next_week = next_week_start.isoformat() if next_week_start <= today else None

    base_qs = (
        TimeEntry.objects
        .filter(created_at__date__gte=week_start, created_at__date__lte=week_end, minutes__gt=0)
        .select_related("user", "user__profile", "project")
        .order_by("-created_at")
    )
    entries_qs, filter_users, filter_projects, sel_user, sel_project, filter_qs = \
        _apply_report_filters(request, base_qs)
    entries = list(entries_qs)
    total_minutes = sum(e.minutes for e in entries)

    # Board names cache
    board_ids = {e.board_id for e in entries if e.board_id}
    from boards.models import Board
    board_name_map = {b.id: b.name for b in Board.objects.filter(id__in=board_ids).only("id", "name")} if board_ids else {}

    by_user = defaultdict(lambda: {"name": "", "handle": "", "minutes": 0, "count": 0})
    by_project = defaultdict(lambda: {"name": "", "minutes": 0})
    by_board = defaultdict(lambda: {"name": "", "minutes": 0})
    day_minutes = {week_start + datetime.timedelta(days=i): 0 for i in range(7)}

    entries_list = []
    for e in entries:
        u = e.user
        prof = getattr(u, "profile", None)
        name = ((getattr(prof, "display_name", "") or "").strip() or u.get_full_name() or u.get_username() or u.email or "?")
        handle = (getattr(prof, "handle", "") or "").strip()
        board_name = board_name_map.get(e.board_id, "") if e.board_id else ""
        proj_name = e.project.name if e.project else "(sem projeto)"

        uid = u.id
        by_user[uid]["name"] = name
        by_user[uid]["handle"] = handle
        by_user[uid]["minutes"] += e.minutes
        by_user[uid]["count"] += 1

        pid = e.project_id or 0
        by_project[pid]["name"] = proj_name
        by_project[pid]["minutes"] += e.minutes

        bid = e.board_id or 0
        by_board[bid]["name"] = board_name or "(sem quadro)"
        by_board[bid]["minutes"] += e.minutes

        d = timezone.localtime(e.created_at).date()
        if d in day_minutes:
            day_minutes[d] += e.minutes

        entries_list.append({
            "date": timezone.localtime(e.created_at).date().isoformat(),
            "user_name": name,
            "project_name": proj_name,
            "board_name": board_name,
            "card_title": e.card_title_cache or "",
            "card_url": e.card_url_cache or "",
            "minutes": e.minutes,
            "hours_display": _fmt_min(e.minutes),
            "deleted": e.is_card_deleted_cache,
        })

    day_labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    by_day = [
        {"date": (week_start + datetime.timedelta(days=i)).isoformat(), "label": day_labels[i],
         "minutes": day_minutes.get(week_start + datetime.timedelta(days=i), 0),
         "hours_display": _fmt_min(day_minutes.get(week_start + datetime.timedelta(days=i), 0))}
        for i in range(7)
    ]

    by_user_list = sorted(by_user.values(), key=lambda x: -x["minutes"])
    by_project_list = sorted(by_project.values(), key=lambda x: -x["minutes"])
    by_board_list = sorted(by_board.values(), key=lambda x: -x["minutes"])

    for item in by_user_list:
        item["hours_display"] = _fmt_min(item["minutes"])
        item["pct"] = round(item["minutes"] / total_minutes * 100) if total_minutes else 0
    for item in by_project_list:
        item["hours_display"] = _fmt_min(item["minutes"])
        item["pct"] = round(item["minutes"] / total_minutes * 100) if total_minutes else 0
    for item in by_board_list:
        item["hours_display"] = _fmt_min(item["minutes"])
        item["pct"] = round(item["minutes"] / total_minutes * 100) if total_minutes else 0

    if request.GET.get("export") == "csv":
        return _report_csv_response(entries_list, f"tracktime_semana_{week_start.isoformat()}.csv")

    sel_user_name, sel_project_name = _report_filter_labels(
        filter_users, filter_projects, sel_user, sel_project
    )

    ctx = {
        "week_start": week_start, "week_end": week_end,
        "prev_week": prev_week, "next_week": next_week,
        "total_minutes": total_minutes,
        "total_hours_display": _fmt_min(total_minutes),
        "num_users": len(by_user),
        "num_entries": len(entries_list),
        "by_user": by_user_list,
        "by_project": by_project_list,
        "by_board": by_board_list,
        "by_day": by_day, "entries": entries_list,
        "has_data": total_minutes > 0,
        "filter_users": filter_users, "filter_projects": filter_projects,
        "sel_user": sel_user, "sel_project": sel_project,
        "sel_user_name": sel_user_name, "sel_project_name": sel_project_name,
        "filter_qs": filter_qs,
        "period_label": f"Semana {week_start.strftime('%d/%m')} – {week_end.strftime('%d/%m/%Y')}",
        "period_param": f"w={week_start.isoformat()}",
    }
    if request.GET.get("print") == "1":
        return render(request, "tracktime/modal/tabs/print.html", ctx)
    return render(request, "tracktime/modal/tabs/week.html", ctx)


@login_required
def tracktime_tab_month(request):
    import datetime
    import calendar
    from collections import defaultdict

    m_param = request.GET.get("m", "")
    try:
        year, month = m_param.split("-")
        year, month = int(year), int(month)
        month_start = datetime.date(year, month, 1)
    except Exception:
        today = timezone.localdate()
        month_start = today.replace(day=1)

    last_day = calendar.monthrange(month_start.year, month_start.month)[1]
    month_end = month_start.replace(day=last_day)

    prev_m = (month_start - datetime.timedelta(days=1)).replace(day=1)
    prev_month = prev_m.strftime("%Y-%m")
    today = timezone.localdate()
    next_m_start = month_end + datetime.timedelta(days=1)
    next_month = next_m_start.strftime("%Y-%m") if next_m_start <= today else None

    PT_MONTHS = [
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]
    month_label = f"{PT_MONTHS[month_start.month - 1]} {month_start.year}"

    base_qs = (
        TimeEntry.objects
        .filter(created_at__date__gte=month_start, created_at__date__lte=month_end, minutes__gt=0)
        .select_related("user", "user__profile", "project")
        .order_by("-created_at")
    )
    entries_qs, filter_users, filter_projects, sel_user, sel_project, filter_qs = \
        _apply_report_filters(request, base_qs)
    entries = list(entries_qs)
    total_minutes = sum(e.minutes for e in entries)

    board_ids = {e.board_id for e in entries if e.board_id}
    from boards.models import Board
    board_name_map = {b.id: b.name for b in Board.objects.filter(id__in=board_ids).only("id", "name")} if board_ids else {}

    by_user = defaultdict(lambda: {"name": "", "handle": "", "minutes": 0, "count": 0})
    by_project = defaultdict(lambda: {"name": "", "minutes": 0})
    by_board = defaultdict(lambda: {"name": "", "minutes": 0})
    by_week = defaultdict(lambda: {"label": "", "minutes": 0, "sort_key": ""})

    entries_list = []
    for e in entries:
        u = e.user
        prof = getattr(u, "profile", None)
        name = ((getattr(prof, "display_name", "") or "").strip() or u.get_full_name() or u.get_username() or u.email or "?")
        handle = (getattr(prof, "handle", "") or "").strip()
        board_name = board_name_map.get(e.board_id, "") if e.board_id else ""
        proj_name = e.project.name if e.project else "(sem projeto)"
        d = timezone.localtime(e.created_at).date()
        # ISO week within month
        iso_week = d.isocalendar()[1]
        week_key = f"{d.year}-W{iso_week:02d}"
        # week label: Mon-Sun of that week
        week_mon = d - datetime.timedelta(days=d.weekday())
        week_sun = week_mon + datetime.timedelta(days=6)
        by_week[week_key]["label"] = f"{week_mon.strftime('%d/%m')} – {week_sun.strftime('%d/%m')}"
        by_week[week_key]["minutes"] += e.minutes
        by_week[week_key]["sort_key"] = week_key

        uid = u.id
        by_user[uid]["name"] = name
        by_user[uid]["handle"] = handle
        by_user[uid]["minutes"] += e.minutes
        by_user[uid]["count"] += 1

        pid = e.project_id or 0
        by_project[pid]["name"] = proj_name
        by_project[pid]["minutes"] += e.minutes

        bid = e.board_id or 0
        by_board[bid]["name"] = board_name or "(sem quadro)"
        by_board[bid]["minutes"] += e.minutes

        entries_list.append({
            "date": d.isoformat(),
            "user_name": name,
            "project_name": proj_name,
            "board_name": board_name,
            "card_title": e.card_title_cache or "",
            "card_url": e.card_url_cache or "",
            "minutes": e.minutes,
            "hours_display": _fmt_min(e.minutes),
            "deleted": e.is_card_deleted_cache,
        })

    by_user_list = sorted(by_user.values(), key=lambda x: -x["minutes"])
    by_project_list = sorted(by_project.values(), key=lambda x: -x["minutes"])
    by_board_list = sorted(by_board.values(), key=lambda x: -x["minutes"])
    by_week_list = sorted(by_week.values(), key=lambda x: x.get("sort_key", ""))

    for item in by_user_list:
        item["hours_display"] = _fmt_min(item["minutes"])
        item["pct"] = round(item["minutes"] / total_minutes * 100) if total_minutes else 0
    for item in by_project_list:
        item["hours_display"] = _fmt_min(item["minutes"])
        item["pct"] = round(item["minutes"] / total_minutes * 100) if total_minutes else 0
    for item in by_board_list:
        item["hours_display"] = _fmt_min(item["minutes"])
        item["pct"] = round(item["minutes"] / total_minutes * 100) if total_minutes else 0
    for item in by_week_list:
        item["hours_display"] = _fmt_min(item["minutes"])

    if request.GET.get("export") == "csv":
        return _report_csv_response(entries_list, f"tracktime_{month_start.strftime('%Y-%m')}.csv")

    sel_user_name, sel_project_name = _report_filter_labels(
        filter_users, filter_projects, sel_user, sel_project
    )

    ctx = {
        "month_start": month_start, "month_end": month_end,
        "prev_month": prev_month, "next_month": next_month,
        "month_label": month_label,
        "total_minutes": total_minutes,
        "total_hours_display": _fmt_min(total_minutes),
        "num_users": len(by_user),
        "num_entries": len(entries_list),
        "by_user": by_user_list,
        "by_project": by_project_list,
        "by_board": by_board_list,
        "by_week": by_week_list,
        "entries": entries_list,
        "has_data": total_minutes > 0,
        "filter_users": filter_users, "filter_projects": filter_projects,
        "sel_user": sel_user, "sel_project": sel_project,
        "sel_user_name": sel_user_name, "sel_project_name": sel_project_name,
        "filter_qs": filter_qs,
        "period_label": month_label,
        "period_param": f"m={month_start.strftime('%Y-%m')}",
    }
    if request.GET.get("print") == "1":
        return render(request, "tracktime/modal/tabs/print.html", ctx)
    return render(request, "tracktime/modal/tabs/month.html", ctx)


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
        # ISO timestamps para o JS calcular o tick localmente via
        # Date.now() - startedAtMs (sem precisar polling de 1Hz).
        "started_at_iso": running.started_at.isoformat(),
        "server_now_iso": now.isoformat(),
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

        # timer rodando vira a primeira linha do histórico.
        # (BUG antigo: este bloco lia de `lg` — variável órfã do loop de logs.
        # Quando não havia CardLog nos últimos 9 min mas o usuário tinha timer
        # rodando, `lg` era indefinida -> NameError -> 500 -> aba travava em
        # "Carregando...". Agora usa `run`, que é o dado do timer.)
        run = running_by_user.get(u.id)
        if run:
            activities.append({
                "type": "tracktime",
                "at": run.get("started_at") or now.isoformat(),
                "text": "⏱ Track-time rodando",
                "content": "",
                "card_title": run.get("card_title") or None,
                "card_url": run.get("card_url") or "",
                "board_name": None,
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





