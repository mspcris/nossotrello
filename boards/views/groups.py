import hashlib
import html
import re
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import models
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import (
    SocialFriendship,
    SocialGroup,
    SocialGroupChatMessage,
    SocialGroupJoinRequest,
    SocialGroupMembership,
    SocialGroupScrapbookEntry,
    SocialPost,
)
from ..services.moderation import ContentBlocked, check_or_block, schedule_layer2
from ..services.social_activity import filter_active_users
from .social import _get_or_create_profile

User = get_user_model()
_GROUP_MENTION_RE = re.compile(r"@([a-z0-9_.]+)", re.I)

_GROUP_PALETTES = [
    ("#0f766e", "#2dd4bf", "#99f6e4"),
    ("#9a3412", "#fb923c", "#fed7aa"),
    ("#1d4ed8", "#60a5fa", "#bfdbfe"),
    ("#4d7c0f", "#a3e635", "#ecfccb"),
    ("#7c2d12", "#f97316", "#fde68a"),
    ("#be123c", "#fb7185", "#fecdd3"),
]


def _group_chat_payload(msg, viewer):
    prof = getattr(msg.sender, "profile", None)
    return {
        "id": msg.id,
        "sender_name": (prof.display_name if prof else "") or msg.sender.email,
        "sender_avatar": getattr(prof, "avatar_url", "") if prof else "",
        "text": msg.text,
        "photo_url": msg.photo.url if getattr(msg, "photo", None) else "",
        "created_label": timezone.localtime(msg.created_at).strftime("%d/%m %H:%M"),
        "is_mine": msg.sender_id == viewer.id,
    }


def _accepted_friend_ids(user):
    sent = set(
        SocialFriendship.objects.filter(
            requester=user, status=SocialFriendship.STATUS_ACCEPTED,
        ).values_list("receiver_id", flat=True)
    )
    received = set(
        SocialFriendship.objects.filter(
            receiver=user, status=SocialFriendship.STATUS_ACCEPTED,
        ).values_list("requester_id", flat=True)
    )
    return sent | received


def _parse_friend_ids(raw_ids, allowed_ids):
    parsed = []
    for raw in raw_ids:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value in allowed_ids and value not in parsed:
            parsed.append(value)
    return parsed


def _interest_tokens(raw_text):
    seen = set()
    tokens = []
    for chunk in (raw_text or "").replace(";", ",").replace("\n", ",").split(","):
        token = " ".join(chunk.strip().split())
        if not token:
            continue
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        tokens.append(token)
        if len(tokens) >= 4:
            break
    return tokens


def _suggest_group_name(theme, interests):
    base = (theme or "").strip()
    if not base:
        tokens = _interest_tokens(interests)
        base = tokens[0] if tokens else "Conexões"
    return f"Comunidade {base.title()}"


def _group_cover_svg(name, theme, interests, vibe):
    seed = f"{name}|{theme}|{interests}|{vibe}"
    palette = _GROUP_PALETTES[int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16) % len(_GROUP_PALETTES)]
    c1, c2, c3 = palette
    tokens = _interest_tokens(interests)
    title = html.escape((name or "Comunidade")[:40])
    subtitle = html.escape((theme or vibe or "Encontros que combinam com o seu grupo")[:56])
    chips = tokens or [theme or vibe or "Conversa", "Amizade", "Descobertas"]
    chip_lines = []
    x_positions = [70, 250, 430, 610]
    for idx, token in enumerate(chips[:4]):
        label = html.escape(token[:18].upper())
        x = x_positions[idx]
        chip_lines.append(
            f'<rect x="{x}" y="390" rx="20" ry="20" width="150" height="42" fill="rgba(255,255,255,0.16)" stroke="rgba(255,255,255,0.32)" />'
            f'<text x="{x + 75}" y="417" text-anchor="middle" fill="#ffffff" font-size="16" font-family="Arial, sans-serif" font-weight="700">{label}</text>'
        )
    return f"""
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 520">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{c1}" />
      <stop offset="55%" stop-color="{c2}" />
      <stop offset="100%" stop-color="{c3}" />
    </linearGradient>
    <filter id="blur">
      <feGaussianBlur stdDeviation="26" />
    </filter>
  </defs>
  <rect width="900" height="520" fill="url(#g)" />
  <circle cx="132" cy="120" r="84" fill="rgba(255,255,255,0.18)" filter="url(#blur)" />
  <circle cx="740" cy="118" r="112" fill="rgba(255,255,255,0.16)" filter="url(#blur)" />
  <circle cx="640" cy="430" r="140" fill="rgba(255,255,255,0.14)" filter="url(#blur)" />
  <path d="M0 382C126 348 238 326 366 352C496 378 598 456 900 330V520H0Z" fill="rgba(8,15,32,0.18)" />
  <text x="68" y="188" fill="#ffffff" font-size="22" font-family="Arial, sans-serif" opacity="0.82">COMUNIDADE</text>
  <text x="68" y="254" fill="#ffffff" font-size="54" font-family="Arial, sans-serif" font-weight="700">{title}</text>
  <text x="68" y="302" fill="#ffffff" font-size="24" font-family="Arial, sans-serif" opacity="0.92">{subtitle}</text>
  <text x="68" y="346" fill="#ffffff" font-size="18" font-family="Arial, sans-serif" opacity="0.78">Capa criada automaticamente a partir do tema e dos interesses do grupo.</text>
  {''.join(chip_lines)}
</svg>
""".strip()


def _group_cover_data(group):
    svg = group.cover_svg or _group_cover_svg(group.name, group.theme, group.interests, group.vibe)
    return f"data:image/svg+xml;charset=UTF-8,{quote(svg)}"


def _decorate_group(group):
    group.cover_data = _group_cover_data(group)
    group.star_count = group.current_stars()
    group.star_fill = range(group.star_count)
    group.star_empty = range(5 - group.star_count)
    return group


def _group_members(group):
    memberships = list(
        SocialGroupMembership.objects
        .filter(group=group)
        .select_related("user", "user__profile")
    )
    active_users = {
        user.id: user
        for user in filter_active_users(
            User.objects.filter(id__in=[membership.user_id for membership in memberships])
        ).select_related("profile")
    }
    return [membership for membership in memberships if membership.user_id in active_users]


def _role_rank(role):
    return {
        SocialGroupMembership.ROLE_OWNER: 0,
        SocialGroupMembership.ROLE_MANAGER: 1,
        SocialGroupMembership.ROLE_MEMBER: 2,
    }.get(role, 99)


def _can_manage_group(membership):
    return bool(membership and membership.role in {
        SocialGroupMembership.ROLE_OWNER,
        SocialGroupMembership.ROLE_MANAGER,
    })


def _can_manage_roles(membership):
    return bool(membership and membership.role == SocialGroupMembership.ROLE_OWNER)


def _can_remove_membership(actor_membership, target_membership):
    if not _can_manage_group(actor_membership):
        return False
    if actor_membership.user_id == target_membership.user_id:
        return False
    if target_membership.role == SocialGroupMembership.ROLE_OWNER:
        return False
    if actor_membership.role == SocialGroupMembership.ROLE_OWNER:
        return True
    return target_membership.role == SocialGroupMembership.ROLE_MEMBER


def _can_nudge_member(actor_membership, target_membership, posting_user_ids):
    if not _can_manage_group(actor_membership):
        return False
    if not target_membership or actor_membership.user_id == target_membership.user_id:
        return False
    if target_membership.role != SocialGroupMembership.ROLE_MEMBER:
        return False
    return target_membership.user_id not in posting_user_ids


def _member_payload(membership, actor_membership, posting_user_ids):
    prof = getattr(membership.user, "profile", None)
    can_manage_roles = _can_manage_roles(actor_membership)
    has_posts = membership.user_id in posting_user_ids
    return {
        "id": membership.user_id,
        "membership_id": membership.id,
        "profile": prof,
        "display_name": (prof.display_name if prof else "") or membership.user.email,
        "avatar_url": getattr(prof, "avatar_url", "") if prof else "",
        "meta": prof.setor if prof and prof.setor else "Ativo no social",
        "role": membership.role,
        "role_label": membership.get_role_display(),
        "is_owner": membership.role == SocialGroupMembership.ROLE_OWNER,
        "is_manager": membership.role == SocialGroupMembership.ROLE_MANAGER,
        "has_posts": has_posts,
        "can_remove": _can_remove_membership(actor_membership, membership),
        "can_nudge": _can_nudge_member(actor_membership, membership, posting_user_ids),
        "can_promote_manager": bool(
            can_manage_roles and membership.role == SocialGroupMembership.ROLE_MEMBER
        ),
        "can_demote_manager": bool(
            can_manage_roles and membership.role == SocialGroupMembership.ROLE_MANAGER
        ),
    }


def _join_request_payload(join_request):
    prof = getattr(join_request.user, "profile", None)
    return {
        "id": join_request.user_id,
        "display_name": (prof.display_name if prof else "") or join_request.user.email,
        "avatar_url": getattr(prof, "avatar_url", "") if prof else "",
        "meta": prof.setor if prof and prof.setor else "Quer entrar nesta comunidade",
        "created_label": timezone.localtime(join_request.created_at).strftime("%d/%m %H:%M"),
    }


def _user_sort_label(user):
    prof = getattr(user, "profile", None)
    return (prof.display_name if prof else "") or user.email


def _group_mentioned_users(text, actor, group):
    if not text:
        return User.objects.none()
    handles = {
        handle.strip().lower()
        for handle in _GROUP_MENTION_RE.findall(text)
        if handle.strip()
    }
    if not handles:
        return User.objects.none()
    return (
        User.objects
        .filter(
            social_group_memberships__group=group,
            profile__handle__in=handles,
        )
        .exclude(id=actor.id)
        .select_related("profile")
        .distinct()
    )


def _notify_group_post_mentions(text, actor, group, post_id):
    mentioned_users = _group_mentioned_users(text, actor, group)
    if not mentioned_users:
        return
    try:
        from boards.services.notifications import notify_social_mention
        for user in mentioned_users:
            try:
                notify_social_mention(
                    recipient=user,
                    actor=actor,
                    post_id=post_id,
                    context="post",
                )
            except Exception:
                pass
    except Exception:
        pass


def _invite_candidates(user, group=None):
    friend_ids = _accepted_friend_ids(user)
    if not friend_ids:
        return []
    excluded = set()
    if group is not None:
        excluded = set(
            SocialGroupMembership.objects.filter(group=group).values_list("user_id", flat=True)
        )
    users = (
        User.objects
        .filter(id__in=friend_ids)
        .exclude(id__in=excluded)
        .select_related("profile")
    )
    return list(users)


def _group_nudge_data(post):
    if not (post.text or "").startswith("__group_nudge__:"):
        return None
    try:
        target_uid = int(post.text.split(":", 1)[1])
        target_user = User.objects.select_related("profile").get(id=target_uid)
    except (TypeError, ValueError, User.DoesNotExist):
        return None

    actor_prof = getattr(post.user, "profile", None)
    target_prof = getattr(target_user, "profile", None)
    return {
        "actor_name": (actor_prof.display_name if actor_prof else "") or post.user.get_full_name() or post.user.email,
        "actor_avatar": getattr(actor_prof, "avatar_url", "") if actor_prof else "",
        "target_name": (target_prof.display_name if target_prof else "") or target_user.get_full_name() or target_user.email,
        "target_avatar": getattr(target_prof, "avatar_url", "") if target_prof else "",
        "target_id": target_user.id,
    }


def _post_payload(post, viewer_membership=None, viewer_user=None):
    prof = getattr(post.user, "profile", None)
    can_delete = False
    if viewer_user is not None:
        can_delete = post.user_id == viewer_user.id or _can_manage_group(viewer_membership)
    nudge_data = _group_nudge_data(post)
    return {
        "id": post.id,
        "author_name": (prof.display_name if prof else "") or post.user.email,
        "author_avatar": getattr(prof, "avatar_url", "") if prof else "",
        "text": "" if nudge_data else post.text,
        "photo_url": post.photo.url if post.photo else "",
        "video_url": post.video.url if post.video else "",
        "created_label": timezone.localtime(post.created_at).strftime("%d/%m/%Y %H:%M"),
        "show_on_profile": post.show_on_profile,
        "can_delete": can_delete,
        "nudge_data": nudge_data,
    }


@login_required
def groups_hub(request):
    prof = _get_or_create_profile(request.user)
    groups = list(
        SocialGroup.objects.all().prefetch_related("memberships")[:30]
    )
    memberships = set(
        SocialGroupMembership.objects.filter(user=request.user).values_list("group_id", flat=True)
    )
    pending_requests = set(
        SocialGroupJoinRequest.objects.filter(user=request.user).values_list("group_id", flat=True)
    )
    for group in groups:
        _decorate_group(group)
        group.member_total = group.memberships.count()
        group.is_member = group.id in memberships
        group.has_pending_request = group.id in pending_requests
    my_groups = [g for g in groups if g.is_member]
    return render(request, "boards/groups_hub.html", {
        "groups": groups,
        "my_groups": my_groups,
        "invite_candidates": _invite_candidates(request.user),
        "show_groups_onboarding": not prof.groups_onboarding_done,
    })


@login_required
@require_POST
def group_create(request):
    name = (request.POST.get("name") or "").strip()
    theme = (request.POST.get("theme") or "").strip()
    interests = (request.POST.get("interests") or "").strip()
    vibe = (request.POST.get("vibe") or "").strip()
    goal = (request.POST.get("goal") or "").strip()
    description = (request.POST.get("description") or "").strip()

    if not name:
        name = _suggest_group_name(theme, interests)
    if not any([theme, interests, vibe, goal, description]):
        messages.error(request, "Conte pelo menos o tema ou os interesses para criar a comunidade.")
        return redirect("boards:groups_hub")

    group = SocialGroup.objects.create(
        name=name,
        description=description,
        theme=theme,
        interests=interests,
        vibe=vibe,
        goal=goal,
        cover_svg=_group_cover_svg(name, theme, interests, vibe),
        created_by=request.user,
    )
    SocialGroupMembership.objects.create(
        group=group,
        user=request.user,
        invited_by=request.user,
        role=SocialGroupMembership.ROLE_OWNER,
    )

    allowed_ids = _accepted_friend_ids(request.user)
    invite_ids = _parse_friend_ids(request.POST.getlist("friend_ids"), allowed_ids)
    memberships = [
        SocialGroupMembership(
            group=group,
            user_id=user_id,
            invited_by=request.user,
            role=SocialGroupMembership.ROLE_MEMBER,
        )
        for user_id in invite_ids
    ]
    if memberships:
        SocialGroupMembership.objects.bulk_create(memberships, ignore_conflicts=True)

    messages.success(request, "Comunidade criada. Agora você já pode publicar, conversar e montar o scrapbook.")
    return redirect("boards:group_detail", slug=group.slug)


@login_required
def group_detail(request, slug):
    group = _decorate_group(get_object_or_404(SocialGroup, slug=slug))
    membership = (
        SocialGroupMembership.objects
        .filter(group=group, user=request.user)
        .first()
    )
    is_member = membership is not None
    can_manage_group = _can_manage_group(membership)
    can_manage_roles = _can_manage_roles(membership)
    posting_user_ids = set(
        SocialPost.objects.filter(group=group, is_active=True)
        .values_list("user_id", flat=True)
        .distinct()
    )
    member_memberships = sorted(
        _group_members(group),
        key=lambda item: (_role_rank(item.role), _user_sort_label(item.user)),
    )
    members = [_member_payload(item, membership, posting_user_ids) for item in member_memberships]
    pending_request = None
    if not is_member:
        pending_request = (
            SocialGroupJoinRequest.objects
            .filter(group=group, user=request.user)
            .first()
        )
    join_requests = []
    if can_manage_group:
        join_requests = [
            _join_request_payload(join_request)
            for join_request in SocialGroupJoinRequest.objects.filter(group=group)
            .select_related("user", "user__profile")[:20]
        ]
    posts = [
        _post_payload(post, viewer_membership=membership, viewer_user=request.user)
        for post in SocialPost.objects.filter(
            group=group,
            is_active=True,
            moderation_status=SocialPost.MOD_CLEAN,
        ).select_related("user", "user__profile").order_by("-created_at")[:30]
    ]
    chat_messages = []
    scrapbook_entries = []
    if is_member:
        chat_messages = [
            {
                "id": msg.id,
                "sender_name": (getattr(msg.sender, "profile", None).display_name if getattr(msg.sender, "profile", None) else "") or msg.sender.email,
                "sender_avatar": getattr(getattr(msg.sender, "profile", None), "avatar_url", ""),
                "text": msg.text,
                "created_label": timezone.localtime(msg.created_at).strftime("%d/%m %H:%M"),
                "is_mine": msg.sender_id == request.user.id,
            }
            for msg in SocialGroupChatMessage.objects.filter(
                group=group, is_active=True,
            ).select_related("sender", "sender__profile").order_by("-created_at")[:40][::-1]
        ]
        scrapbook_entries = [
            {
                "author_name": (getattr(entry.author, "profile", None).display_name if getattr(entry.author, "profile", None) else "") or entry.author.email,
                "author_avatar": getattr(getattr(entry.author, "profile", None), "avatar_url", ""),
                "text": entry.text,
                "photo_url": entry.photo.url if entry.photo else "",
                "created_label": timezone.localtime(entry.created_at).strftime("%d/%m/%Y %H:%M"),
            }
            for entry in SocialGroupScrapbookEntry.objects.filter(
                group=group, is_active=True,
            ).select_related("author", "author__profile")[:12]
        ]

    return render(request, "boards/group_detail.html", {
        "group": group,
        "is_member": is_member,
        "membership": membership,
        "can_manage_group": can_manage_group,
        "can_manage_roles": can_manage_roles,
        "pending_request": pending_request,
        "join_requests": join_requests,
        "members": members[:18],
        "member_total": len(members),
        "posts": posts,
        "chat_messages": chat_messages,
        "scrapbook_entries": scrapbook_entries,
        "invite_candidates": _invite_candidates(request.user, group) if can_manage_group else [],
        "show_groups_onboarding": not _get_or_create_profile(request.user).groups_onboarding_done,
    })


@login_required
@require_POST
def group_join(request, slug):
    group = get_object_or_404(SocialGroup, slug=slug)
    if SocialGroupMembership.objects.filter(group=group, user=request.user).exists():
        messages.info(request, "Você já faz parte desta comunidade.")
        return redirect("boards:group_detail", slug=group.slug)

    _, created = SocialGroupJoinRequest.objects.get_or_create(
        group=group,
        user=request.user,
    )
    if created:
        messages.success(request, "Pedido enviado. Agora é só aguardar a aprovação do dono ou de um gestor.")
    else:
        messages.info(request, "Seu pedido já está aguardando aprovação.")
    return redirect("boards:group_detail", slug=group.slug)


@login_required
@require_POST
def group_invite_friends(request, slug):
    group = get_object_or_404(SocialGroup, slug=slug)
    membership = SocialGroupMembership.objects.filter(group=group, user=request.user).first()
    if not _can_manage_group(membership):
        return HttpResponseForbidden("Sem permissão.")

    allowed_ids = _accepted_friend_ids(request.user)
    invite_ids = _parse_friend_ids(request.POST.getlist("friend_ids"), allowed_ids)
    memberships = [
        SocialGroupMembership(
            group=group,
            user_id=user_id,
            invited_by=request.user,
            role=SocialGroupMembership.ROLE_MEMBER,
        )
        for user_id in invite_ids
    ]
    if memberships:
        SocialGroupMembership.objects.bulk_create(memberships, ignore_conflicts=True)
        SocialGroupJoinRequest.objects.filter(group=group, user_id__in=invite_ids).delete()
        messages.success(request, "Amigos adicionados à comunidade.")
    else:
        messages.info(request, "Escolha pelo menos um amigo para convidar.")
    return redirect("boards:group_detail", slug=group.slug)


@login_required
@require_POST
def group_request_approve(request, slug, user_id):
    group = get_object_or_404(SocialGroup, slug=slug)
    membership = SocialGroupMembership.objects.filter(group=group, user=request.user).first()
    if not _can_manage_group(membership):
        return HttpResponseForbidden("Sem permissão.")

    target_user = get_object_or_404(User, id=user_id)
    join_request = SocialGroupJoinRequest.objects.filter(group=group, user=target_user).first()
    if not join_request:
        messages.info(request, "Esse pedido já foi resolvido.")
        return redirect("boards:group_detail", slug=group.slug)

    SocialGroupMembership.objects.get_or_create(
        group=group,
        user=target_user,
        defaults={
            "invited_by": request.user,
            "role": SocialGroupMembership.ROLE_MEMBER,
        },
    )
    SocialGroupJoinRequest.objects.filter(group=group, user=target_user).delete()
    messages.success(request, "Pedido aprovado. A pessoa já faz parte da comunidade.")
    return redirect("boards:group_detail", slug=group.slug)


@login_required
@require_POST
def group_request_deny(request, slug, user_id):
    group = get_object_or_404(SocialGroup, slug=slug)
    membership = SocialGroupMembership.objects.filter(group=group, user=request.user).first()
    if not _can_manage_group(membership):
        return HttpResponseForbidden("Sem permissão.")

    deleted, _ = SocialGroupJoinRequest.objects.filter(group=group, user_id=user_id).delete()
    if deleted:
        messages.success(request, "Pedido recusado.")
    else:
        messages.info(request, "Esse pedido já foi resolvido.")
    return redirect("boards:group_detail", slug=group.slug)


@login_required
@require_POST
def group_member_remove(request, slug, user_id):
    group = get_object_or_404(SocialGroup, slug=slug)
    actor_membership = SocialGroupMembership.objects.filter(group=group, user=request.user).first()
    target_membership = SocialGroupMembership.objects.filter(group=group, user_id=user_id).first()
    if not actor_membership or not target_membership or not _can_remove_membership(actor_membership, target_membership):
        return HttpResponseForbidden("Sem permissão.")

    target_name = (getattr(getattr(target_membership.user, "profile", None), "display_name", "") or target_membership.user.email)
    target_membership.delete()
    messages.success(request, f"{target_name} foi removido da comunidade.")
    return redirect("boards:group_detail", slug=group.slug)


@login_required
@require_POST
def group_member_role_update(request, slug, user_id):
    group = get_object_or_404(SocialGroup, slug=slug)
    actor_membership = SocialGroupMembership.objects.filter(group=group, user=request.user).first()
    if not _can_manage_roles(actor_membership):
        return HttpResponseForbidden("Sem permissão.")

    target_membership = get_object_or_404(SocialGroupMembership, group=group, user_id=user_id)
    if target_membership.role == SocialGroupMembership.ROLE_OWNER or target_membership.user_id == request.user.id:
        return HttpResponseForbidden("Sem permissão.")

    new_role = (request.POST.get("role") or "").strip()
    if new_role not in {SocialGroupMembership.ROLE_MANAGER, SocialGroupMembership.ROLE_MEMBER}:
        messages.error(request, "Papel inválido.")
        return redirect("boards:group_detail", slug=group.slug)

    target_membership.role = new_role
    target_membership.save(update_fields=["role"])
    messages.success(request, f"{target_membership.user.email} agora está como {target_membership.get_role_display().lower()}.")
    return redirect("boards:group_detail", slug=group.slug)


@login_required
@require_POST
def group_member_nudge(request, slug, user_id):
    group = get_object_or_404(SocialGroup, slug=slug)
    actor_membership = SocialGroupMembership.objects.filter(group=group, user=request.user).first()
    target_membership = SocialGroupMembership.objects.filter(group=group, user_id=user_id).first()
    posting_user_ids = set(
        SocialPost.objects.filter(group=group, is_active=True)
        .values_list("user_id", flat=True)
        .distinct()
    )
    if not actor_membership or not target_membership or not _can_nudge_member(actor_membership, target_membership, posting_user_ids):
        return HttpResponseForbidden("Sem permissão.")

    from boards.services.notifications import notify_group_nudge

    notify_group_nudge(
        recipient=target_membership.user,
        actor=request.user,
        group=group,
    )
    SocialPost.objects.create(
        user=request.user,
        group=group,
        text=f"__group_nudge__:{target_membership.user_id}",
        visibility=SocialPost.VISIBILITY_ALL,
        show_on_profile=False,
    )
    target_name = (getattr(getattr(target_membership.user, "profile", None), "display_name", "") or target_membership.user.email)
    messages.success(request, f"{target_name} recebeu uma cutucada para participar mais da comunidade.")
    return redirect("boards:group_detail", slug=group.slug)


@login_required
@require_POST
def group_post_create(request, slug):
    group = get_object_or_404(SocialGroup, slug=slug)
    if not SocialGroupMembership.objects.filter(group=group, user=request.user).exists():
        return HttpResponseForbidden("Sem permissão.")
    prof = getattr(request.user, "profile", None)
    if prof is not None and getattr(prof, "social_blocked", False):
        messages.error(request, "Seu acesso ao Espaço Social está bloqueado no momento.")
        return redirect("boards:group_detail", slug=group.slug)

    text = (request.POST.get("text") or "").strip()
    photo = request.FILES.get("photo")
    video = request.FILES.get("video")
    media = request.FILES.get("media")
    if media and not photo and not video:
        content_type = (media.content_type or "").lower()
        if content_type.startswith("video/"):
            video = media
        else:
            photo = media
    destination = (request.POST.get("destination") or "group_only").strip()
    show_on_profile = destination == "group_and_profile"

    if not text and not photo and not video:
        messages.error(request, "Adicione texto, foto ou vídeo antes de publicar.")
        return redirect("boards:group_detail", slug=group.slug)

    try:
        check_or_block(text=text, author=request.user, kind="social_post")
    except ContentBlocked as exc:
        messages.error(request, exc.user_message)
        return redirect("boards:group_detail", slug=group.slug)

    from boards.services.image_compress import compress_image

    compressed_photo = compress_image(photo) if photo else None
    post = SocialPost.objects.create(
        user=request.user,
        group=group,
        text=text,
        photo=compressed_photo,
        video=video or None,
        visibility=SocialPost.VISIBILITY_ALL,
        show_on_profile=show_on_profile,
    )
    if text:
        schedule_layer2(
            obj=post,
            kind="social_post",
            text=text,
            author=request.user,
        )
        _notify_group_post_mentions(text, request.user, group, post.id)

    if video:
        try:
            from boards.services.video_compress import schedule_video_compress
            schedule_video_compress(post.id)
        except Exception:
            pass

    if group.register_publication():
        group.save()

    if show_on_profile:
        messages.success(request, "Post publicado na comunidade e na sua página.")
    else:
        messages.success(request, "Post publicado só na comunidade.")
    return redirect("boards:group_detail", slug=group.slug)


@login_required
@require_POST
def group_post_delete(request, slug, post_id):
    group = get_object_or_404(SocialGroup, slug=slug)
    post = get_object_or_404(SocialPost, id=post_id, group=group, is_active=True)
    membership = SocialGroupMembership.objects.filter(group=group, user=request.user).first()
    can_delete = bool(
        post.user_id == request.user.id or _can_manage_group(membership)
    )
    if not can_delete:
        return HttpResponseForbidden("Sem permissão.")

    post.is_active = False
    update_fields = ["is_active"]
    if post.user_id != request.user.id:
        post.moderation_status = SocialPost.MOD_REMOVED
        post.moderation_reason = "Removido pela gestão da comunidade."
        update_fields.extend(["moderation_status", "moderation_reason"])
    post.save(update_fields=update_fields)
    messages.success(request, "Publicação apagada da comunidade.")
    return redirect("boards:group_detail", slug=group.slug)


@login_required
@require_POST
def group_chat_send(request, slug):
    group = get_object_or_404(SocialGroup, slug=slug)
    if not SocialGroupMembership.objects.filter(group=group, user=request.user).exists():
        return JsonResponse({"error": "Sem permissão."}, status=403)
    prof = getattr(request.user, "profile", None)
    if prof is not None and getattr(prof, "social_blocked", False):
        return JsonResponse({"error": "Seu acesso ao Espaço Social está bloqueado no momento."}, status=403)

    text = (request.POST.get("text") or "").strip()
    photo = request.FILES.get("photo")
    if photo and not (photo.content_type or "").lower().startswith("image/"):
        return JsonResponse({"error": "Envie apenas imagens no chat."}, status=400)
    if not text and not photo:
        return JsonResponse({"error": "Mensagem vazia."}, status=400)
    client_request_id = (request.POST.get("client_request_id") or "").strip()[:100]

    result_cache_key = None
    pending_cache_key = None
    if client_request_id:
        result_cache_key = f"group-chat-send:{group.id}:{request.user.id}:{client_request_id}"
        pending_cache_key = f"{result_cache_key}:pending"
        existing_msg_id = cache.get(result_cache_key)
        if existing_msg_id:
            existing_msg = (
                SocialGroupChatMessage.objects
                .filter(group=group, sender=request.user, id=existing_msg_id)
                .select_related("sender", "sender__profile")
                .first()
            )
            if existing_msg:
                return JsonResponse(_group_chat_payload(existing_msg, request.user))
        if not cache.add(pending_cache_key, 1, timeout=30):
            return JsonResponse({"error": "Essa mensagem já está sendo enviada."}, status=409)

    try:
        from boards.services.image_compress import compress_image

        msg = SocialGroupChatMessage.objects.create(
            group=group,
            sender=request.user,
            text=text,
            photo=compress_image(photo) if photo else None,
        )
        if result_cache_key:
            cache.set(result_cache_key, msg.id, timeout=120)
        group.save()
        return JsonResponse(_group_chat_payload(msg, request.user))
    finally:
        if pending_cache_key:
            cache.delete(pending_cache_key)


@login_required
def group_mention_search(request, slug):
    group = get_object_or_404(SocialGroup, slug=slug)
    if not SocialGroupMembership.objects.filter(group=group, user=request.user).exists():
        return JsonResponse([], safe=False)

    q = (request.GET.get("q") or "").strip()
    if len(q) < 1:
        return JsonResponse([], safe=False)

    users = (
        User.objects
        .filter(social_group_memberships__group=group)
        .exclude(id=request.user.id)
        .select_related("profile")
        .filter(
            models.Q(profile__handle__icontains=q)
            | models.Q(profile__display_name__icontains=q)
        )
        .order_by("profile__handle")
        .distinct()[:15]
    )

    results = []
    for user in users:
        profile = getattr(user, "profile", None)
        handle = (getattr(profile, "handle", "") or "").strip()
        if not handle:
            continue
        results.append({
            "id": user.id,
            "handle": handle,
            "display_name": (getattr(profile, "display_name", "") or "").strip(),
            "avatar_url": getattr(profile, "avatar_url", "") if profile else "",
        })
    return JsonResponse(results, safe=False)


@login_required
def group_chat_poll(request, slug):
    group = get_object_or_404(SocialGroup, slug=slug)
    if not SocialGroupMembership.objects.filter(group=group, user=request.user).exists():
        return JsonResponse({"error": "Sem permissão."}, status=403)

    try:
        after_id = int(request.GET.get("after") or 0)
    except (TypeError, ValueError):
        after_id = 0

    messages_payload = []
    for msg in SocialGroupChatMessage.objects.filter(
        group=group, is_active=True, id__gt=after_id,
    ).select_related("sender", "sender__profile").order_by("created_at")[:60]:
        messages_payload.append(_group_chat_payload(msg, request.user))
    return JsonResponse({"messages": messages_payload})


@login_required
@require_POST
def group_scrapbook_add(request, slug):
    group = get_object_or_404(SocialGroup, slug=slug)
    if not SocialGroupMembership.objects.filter(group=group, user=request.user).exists():
        return HttpResponseForbidden("Sem permissão.")
    prof = getattr(request.user, "profile", None)
    if prof is not None and getattr(prof, "social_blocked", False):
        messages.error(request, "Seu acesso ao Espaço Social está bloqueado no momento.")
        return redirect("boards:group_detail", slug=group.slug)

    text = (request.POST.get("text") or "").strip()
    photo = request.FILES.get("photo")
    if not text and not photo:
        messages.error(request, "Escreva algo ou envie uma foto para o scrapbook.")
        return redirect("boards:group_detail", slug=group.slug)

    from boards.services.image_compress import compress_image

    SocialGroupScrapbookEntry.objects.create(
        group=group,
        author=request.user,
        text=text,
        photo=compress_image(photo) if photo else None,
    )
    messages.success(request, "Memória adicionada ao scrapbook.")
    return redirect("boards:group_detail", slug=group.slug)


@login_required
@require_POST
def groups_onboarding_done(request):
    prof = _get_or_create_profile(request.user)
    if not prof.groups_onboarding_done:
        prof.groups_onboarding_done = True
        prof.save(update_fields=["groups_onboarding_done"])
    return JsonResponse({"ok": True})
