"""Fila de moderação para staff — listar, aprovar, rejeitar, escalonar."""
from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from boards.models import ModerationCase, SocialPost, BanLog
from boards.services.moderation import banishment
from boards.services.moderation.emails import send_human_decision_email


def _resolve_content(case: ModerationCase):
    """Devolve (obj_or_none, kind_label, link_url)."""
    if case.content_kind == ModerationCase.KIND_SOCIAL_POST:
        post = SocialPost.objects.filter(pk=case.object_id).first()
        url = reverse("boards:social_post_page", args=[post.id]) if post else ""
        return post, "Post", url
    # outras kinds entram em PRs seguintes
    return None, case.get_content_kind_display(), ""


@staff_member_required
def queue(request):
    """Lista casos pendentes (pending_human + auto_blocked sem decisão revisada)."""
    status = (request.GET.get("status") or "pending_human").strip()
    valid = dict(ModerationCase.STATUS_CHOICES)
    if status not in valid and status != "all":
        status = "pending_human"

    qs = ModerationCase.objects.select_related("author", "layer1_term").order_by("-created_at")
    if status != "all":
        qs = qs.filter(status=status)

    cases = []
    for c in qs[:200]:
        obj, kind_label, link = _resolve_content(c)
        cases.append({
            "case": c,
            "obj": obj,
            "kind_label": kind_label,
            "link": link,
        })

    ctx = {
        "cases": cases,
        "current_status": status,
        "status_choices": ModerationCase.STATUS_CHOICES,
        "kind_choices": ModerationCase.KIND_CHOICES,
    }
    return render(request, "boards/moderation_queue.html", ctx)


@staff_member_required
@require_POST
def approve(request, case_id: int):
    case = get_object_or_404(ModerationCase, pk=case_id)
    notes = (request.POST.get("notes") or "").strip()

    case.status = ModerationCase.STATUS_HUMAN_APPROVED
    case.decision_by = request.user
    case.decision_at = timezone.now()
    case.decision_notes = notes
    case.save(update_fields=["status", "decision_by", "decision_at", "decision_notes"])

    # Libera o post se ele estava em análise
    if case.content_kind == ModerationCase.KIND_SOCIAL_POST and case.object_id:
        SocialPost.objects.filter(pk=case.object_id).update(
            moderation_status=SocialPost.MOD_CLEAN,
            moderation_reason="",
            moderation_clause="",
        )

    send_human_decision_email(
        author=case.author, kind=case.content_kind, approved=True,
        terms_clause="", notes=notes, preview_text=case.subject_text,
        case_id=case.id,
    )
    return redirect(reverse("boards:moderation_queue") + f"?status={request.GET.get('status') or 'pending_human'}")


@staff_member_required
@require_POST
def reject(request, case_id: int):
    """Rejeita: marca post como removido + opcionalmente aplica punição escalonada."""
    case = get_object_or_404(ModerationCase, pk=case_id)
    notes = (request.POST.get("notes") or "").strip()
    terms_clause = (request.POST.get("terms_clause") or "4.4").strip()
    escalate = (request.POST.get("escalate") or "post_block").strip()

    case.status = ModerationCase.STATUS_HUMAN_REJECTED
    case.decision_by = request.user
    case.decision_at = timezone.now()
    case.decision_notes = notes
    case.save(update_fields=["status", "decision_by", "decision_at", "decision_notes"])

    # Aplica a ação de banimento solicitada (warn é a mais leve, idcamim_block a mais pesada)
    reason = notes or "Violação dos Termos de Uso constatada pela moderação."

    if escalate == BanLog.ACTION_WARN:
        # Aviso: não bloqueia o post mas registra advertência
        banishment.warn_user(
            user=case.author, reason=reason, terms_clause=terms_clause,
            case=case, applied_by=request.user,
        )
        # Mesmo no warn, removemos o conteúdo ofensivo
        if case.content_kind == ModerationCase.KIND_SOCIAL_POST and case.object_id:
            post = SocialPost.objects.filter(pk=case.object_id).first()
            if post:
                banishment.block_post(
                    post=post, reason=reason, terms_clause=terms_clause,
                    case=case, applied_by=request.user,
                )
    elif escalate == BanLog.ACTION_POST_BLOCK:
        if case.content_kind == ModerationCase.KIND_SOCIAL_POST and case.object_id:
            post = SocialPost.objects.filter(pk=case.object_id).first()
            if post:
                banishment.block_post(
                    post=post, reason=reason, terms_clause=terms_clause,
                    case=case, applied_by=request.user,
                )
    elif escalate == BanLog.ACTION_SOCIAL_BLOCK:
        if case.content_kind == ModerationCase.KIND_SOCIAL_POST and case.object_id:
            post = SocialPost.objects.filter(pk=case.object_id).first()
            if post:
                banishment.block_post(
                    post=post, reason=reason, terms_clause=terms_clause,
                    case=case, applied_by=request.user,
                )
        banishment.block_social(
            user=case.author, reason=reason, terms_clause=terms_clause,
            case=case, applied_by=request.user,
        )
    elif escalate == BanLog.ACTION_ACCOUNT_BLOCK:
        if case.content_kind == ModerationCase.KIND_SOCIAL_POST and case.object_id:
            post = SocialPost.objects.filter(pk=case.object_id).first()
            if post:
                banishment.block_post(
                    post=post, reason=reason, terms_clause=terms_clause,
                    case=case, applied_by=request.user,
                )
        banishment.block_account(
            user=case.author, reason=reason, terms_clause=terms_clause,
            case=case, applied_by=request.user,
        )
    elif escalate == BanLog.ACTION_IDCAMIM_BLOCK:
        banishment.block_idcamim(
            user=case.author, reason=reason, terms_clause=terms_clause,
            case=case, applied_by=request.user,
        )
    else:
        return HttpResponseBadRequest("escalate inválido")

    # Email da decisão (independente do tipo de banimento) para o autor saber por que
    send_human_decision_email(
        author=case.author, kind=case.content_kind, approved=False,
        terms_clause=terms_clause, notes=notes, preview_text=case.subject_text,
        case_id=case.id,
    )
    return redirect(reverse("boards:moderation_queue") + f"?status={request.GET.get('status') or 'pending_human'}")
