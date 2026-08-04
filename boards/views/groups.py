import hashlib
import html
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import (
    SocialFriendship,
    SocialGroup,
    SocialGroupChatMessage,
    SocialGroupMembership,
    SocialGroupScrapbookEntry,
    SocialPost,
)
from ..services.moderation import ContentBlocked, check_or_block, schedule_layer2
from ..services.social_activity import filter_active_users
from .social import _get_or_create_profile, _notify_mentions

User = get_user_model()

_GROUP_PALETTES = [
    ("#0f766e", "#2dd4bf", "#99f6e4"),
    ("#9a3412", "#fb923c", "#fed7aa"),
    ("#1d4ed8", "#60a5fa", "#bfdbfe"),
    ("#4d7c0f", "#a3e635", "#ecfccb"),
    ("#7c2d12", "#f97316", "#fde68a"),
    ("#be123c", "#fb7185", "#fecdd3"),
]


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
    member_ids = list(
        SocialGroupMembership.objects.filter(group=group).values_list("user_id", flat=True)
    )
    if not member_ids:
        return []
    return list(
        filter_active_users(User.objects.filter(id__in=member_ids)).select_related("profile")
    )


def _invite_candidates(user, group=None):
    friend_ids = _accepted_friend_ids(user)
    if not friend_ids:
        return []
    excluded = set()
    if group is not None:
        excluded = set(
            SocialGroupMembership.objects.filter(group=group).values_list("user_id", flat=True)
        )
    users = filter_active_users(
        User.objects.filter(id__in=friend_ids).exclude(id__in=excluded)
    ).select_related("profile")
    return list(users)


def _post_payload(post):
    prof = getattr(post.user, "profile", None)
    return {
        "id": post.id,
        "author_name": (prof.display_name if prof else "") or post.user.email,
        "author_avatar": getattr(prof, "avatar_url", "") if prof else "",
        "text": post.text,
        "photo_url": post.photo.url if post.photo else "",
        "video_url": post.video.url if post.video else "",
        "created_label": timezone.localtime(post.created_at).strftime("%d/%m/%Y %H:%M"),
        "show_on_profile": post.show_on_profile,
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
    for group in groups:
        _decorate_group(group)
        group.member_total = group.memberships.count()
        group.is_member = group.id in memberships
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
    members = _group_members(group)
    posts = [
        _post_payload(post)
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
        "members": members[:18],
        "member_total": len(members),
        "posts": posts,
        "chat_messages": chat_messages,
        "scrapbook_entries": scrapbook_entries,
        "invite_candidates": _invite_candidates(request.user, group) if is_member else [],
        "show_groups_onboarding": not _get_or_create_profile(request.user).groups_onboarding_done,
    })


@login_required
@require_POST
def group_join(request, slug):
    group = get_object_or_404(SocialGroup, slug=slug)
    SocialGroupMembership.objects.get_or_create(
        group=group,
        user=request.user,
        defaults={
            "invited_by": request.user,
            "role": SocialGroupMembership.ROLE_MEMBER,
        },
    )
    messages.success(request, "Você entrou na comunidade.")
    return redirect("boards:group_detail", slug=group.slug)


@login_required
@require_POST
def group_invite_friends(request, slug):
    group = get_object_or_404(SocialGroup, slug=slug)
    if not SocialGroupMembership.objects.filter(group=group, user=request.user).exists():
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
        messages.success(request, "Amigos adicionados à comunidade.")
    else:
        messages.info(request, "Escolha pelo menos um amigo para convidar.")
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
        _notify_mentions(text, request.user, post.id, context="post")

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
def group_chat_send(request, slug):
    group = get_object_or_404(SocialGroup, slug=slug)
    if not SocialGroupMembership.objects.filter(group=group, user=request.user).exists():
        return JsonResponse({"error": "Sem permissão."}, status=403)
    prof = getattr(request.user, "profile", None)
    if prof is not None and getattr(prof, "social_blocked", False):
        return JsonResponse({"error": "Seu acesso ao Espaço Social está bloqueado no momento."}, status=403)

    text = (request.POST.get("text") or "").strip()
    if not text:
        return JsonResponse({"error": "Mensagem vazia."}, status=400)

    msg = SocialGroupChatMessage.objects.create(
        group=group,
        sender=request.user,
        text=text,
    )
    prof = _get_or_create_profile(request.user)
    group.save()
    return JsonResponse({
        "id": msg.id,
        "sender_name": prof.display_name or request.user.email,
        "sender_avatar": prof.avatar_url,
        "text": msg.text,
        "created_label": timezone.localtime(msg.created_at).strftime("%d/%m %H:%M"),
        "is_mine": True,
    })


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
        prof = getattr(msg.sender, "profile", None)
        messages_payload.append({
            "id": msg.id,
            "sender_name": (prof.display_name if prof else "") or msg.sender.email,
            "sender_avatar": getattr(prof, "avatar_url", "") if prof else "",
            "text": msg.text,
            "created_label": timezone.localtime(msg.created_at).strftime("%d/%m %H:%M"),
            "is_mine": msg.sender_id == request.user.id,
        })
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
