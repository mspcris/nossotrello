# boards/views/social.py
"""
Espaço social: rede social de trabalho — check-in diário, humor,
almoço, pendências do dia, feed de fotos do trabalho.
"""
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import timedelta

import requests as http_requests
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model
from django.utils import timezone

from django.db import models
from collections import Counter, defaultdict

from ..models import (
    Board, BoardMembership, Column, SocialPost, SocialPostSeen, SocialPostVersion,
    SocialPostReaction, SocialPostComment, SocialCommentReaction,
    DailyCheckIn, Card, CardFollow, UserProfile,
    CamilaKnowledge, CamilaConfig, SocialFriendship, SocialCardDismiss, CamilaPOP,
    ChatConversation, ChatMessage, ChatSticker, SocialPostView,
)

User = get_user_model()

_mention_logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"@([a-z0-9_.]+)", re.IGNORECASE)


def _notify_mentions(text: str, actor, post_id: int, context: str = "post"):
    """Extrai @handles do texto e envia notificação para cada usuário mencionado."""
    if not text:
        return
    handles = set(_MENTION_RE.findall(text))
    if not handles:
        return
    mentioned_users = User.objects.filter(
        profile__handle__in=handles
    ).exclude(id=actor.id).select_related("profile")
    if not mentioned_users:
        return
    try:
        from boards.services.notifications import notify_social_mention
        for u in mentioned_users:
            try:
                notify_social_mention(
                    recipient=u,
                    actor=actor,
                    post_id=post_id,
                    context=context,
                )
            except Exception:
                _mention_logger.exception("mention notify failed user_id=%s", u.id)
    except Exception:
        _mention_logger.exception("mention notify: import failed")


from django.contrib.admin.views.decorators import staff_member_required

_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL_DEFAULT = "llama-3.3-70b-versatile"


def _groq_chat(messages: list[dict], system_prompt: str = "", config=None) -> str:
    """Chama a Groq API e retorna o texto da resposta."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return ""
    if config is None:
        try:
            config = CamilaConfig.get()
        except Exception:
            config = None
    model = (config.model if config else None) or os.getenv("GROQ_MODEL", "").strip() or _GROQ_MODEL_DEFAULT
    temperature = config.temperature if config else 0.8
    max_tokens = config.max_tokens if config else 500
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages,
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        r = http_requests.post(
            _GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return f"Erro ao contatar a IA: {exc}"


def _can_see_social(request, target_user) -> bool:
    if request.user == target_user or request.user.is_staff:
        return True
    return BoardMembership.objects.filter(
        user=request.user,
        board__memberships__user=target_user,
    ).exists()


def _get_or_create_profile(user):
    prof, _ = UserProfile.objects.get_or_create(user=user)
    return prof


def _get_today_checkin(user):
    today = timezone.localdate()
    checkin, _ = DailyCheckIn.objects.get_or_create(
        user=user, date=today,
    )
    return checkin


def _get_today_tasks(user):
    """Retorna cards que o usuário segue com vencimento hoje ou pendentes, excluindo dispensados hoje."""
    today = timezone.localdate()

    # Cards que o usuário segue, não deletados, não arquivados, não entregues
    followed_ids = CardFollow.objects.filter(user=user).values_list("card_id", flat=True)

    # IDs dispensados hoje
    dismissed_ids = SocialCardDismiss.objects.filter(
        user=user, dismissed_on=today
    ).values_list("card_id", flat=True)

    cards = (
        Card.objects
        .filter(id__in=followed_ids, is_deleted=False, is_archived=False, is_delivered=False)
        .exclude(id__in=dismissed_ids)
        .select_related("column", "column__board")
        .order_by("due_date", "position")[:20]
    )
    return cards


def _build_social_context(request, target_user, extra=None):
    is_me = request.user.id == target_user.id
    prof = _get_or_create_profile(target_user)
    today = timezone.localdate()

    # Check-in de hoje
    checkin = None
    if is_me:
        checkin = _get_today_checkin(target_user)

    # Último check-in (para exibir no perfil de outros)
    latest_checkin = (
        DailyCheckIn.objects
        .filter(user=target_user, mood__gt="")
        .order_by("-date")
        .first()
    )

    # Posts + prefetch reactions/comments
    posts_qs = SocialPost.objects.filter(user=target_user, is_active=True).order_by("-created_at")
    if not is_me:
        # Visitor: hide "friends only" posts unless they are an accepted friend
        is_friend = SocialFriendship.objects.filter(
            models.Q(requester=request.user, receiver=target_user, status="accepted")
            | models.Q(requester=target_user, receiver=request.user, status="accepted")
        ).exists()
        if not is_friend:
            posts_qs = posts_qs.exclude(visibility="friends")
    posts = list(posts_qs[:30])

    if posts:
        post_ids = [p.id for p in posts]

        # Prefetch reactions
        reactions_by_post = defaultdict(list)
        for r in SocialPostReaction.objects.filter(post_id__in=post_ids).select_related("user"):
            reactions_by_post[r.post_id].append(r)

        # Prefetch comments
        comments_by_post = defaultdict(list)
        for c in (
            SocialPostComment.objects
            .filter(post_id__in=post_ids)
            .select_related("user")
            .order_by("created_at")
        ):
            comments_by_post[c.post_id].append(c)

        # Prefetch view counts
        view_counts = dict(
            SocialPostView.objects
            .filter(post_id__in=post_ids)
            .values_list("post_id")
            .annotate(cnt=models.Count("id"))
        )

        # Annotate each post
        for post in posts:
            post_reactions = reactions_by_post.get(post.id, [])
            post.reaction_counts = dict(Counter(r.reaction for r in post_reactions))
            post.total_reactions = len(post_reactions)
            post.my_reaction = next(
                (r.reaction for r in post_reactions if r.user_id == request.user.id), None
            )
            # Custom reactions (not in the 5 presets)
            preset_keys = set(dict(SocialPostReaction.REACTION_CHOICES).keys())
            post.custom_reactions = {
                k: v for k, v in post.reaction_counts.items() if k not in preset_keys
            }
            post.comment_list = comments_by_post.get(post.id, [])
            post.comment_count = len(post.comment_list)
            post.view_count = view_counts.get(post.id, 0)

            # Repost: herda conteúdo do post original
            post.is_repost = False
            post.original_author = None
            if post.shared_from_id:
                post.is_repost = True
                try:
                    orig = SocialPost.objects.select_related("user__profile").get(id=post.shared_from_id, is_active=True)
                    orig_prof = getattr(orig.user, "profile", None)
                    post.original_author = orig_prof.display_name if orig_prof else orig.user.get_full_name()
                    post.original_user_id = orig.user_id
                    # Herda mídia/texto do original se o repost está vazio
                    if not post.text and orig.text:
                        post.text = orig.text
                    if not post.photo and orig.photo:
                        post.photo = orig.photo
                    if not post.video and orig.video:
                        post.video = orig.video
                    if not post.gif_url and orig.gif_url:
                        post.gif_url = orig.gif_url
                    if not post.sticker_url and orig.sticker_url:
                        post.sticker_url = orig.sticker_url
                    if not post.text_style and orig.text_style:
                        post.text_style = orig.text_style
                except SocialPost.DoesNotExist:
                    pass

            # Friendship post annotation
            post.is_friendship = False
            post.friendship_data = None
            if post.text.startswith("__friendship__:"):
                post.is_friendship = True
                try:
                    friend_uid = int(post.text.split(":")[1])
                    friend_user = User.objects.select_related("profile").get(id=friend_uid)
                    friend_prof = getattr(friend_user, "profile", None)
                    post_prof = getattr(post.user, "profile", None)
                    post.friendship_data = {
                        "friend_name": friend_prof.display_name if friend_prof else friend_user.get_full_name(),
                        "friend_avatar": friend_prof.avatar.url if friend_prof and friend_prof.avatar else "",
                        "friend_avatar_choice": friend_prof.avatar_choice if friend_prof else "",
                        "friend_id": friend_uid,
                        "user_name": post_prof.display_name if post_prof else post.user.get_full_name(),
                        "user_avatar": post_prof.avatar.url if post_prof and post_prof.avatar else "",
                        "user_avatar_choice": post_prof.avatar_choice if post_prof else "",
                    }
                except Exception:
                    pass

    # Marca visto
    if not is_me and posts:
        SocialPostSeen.objects.update_or_create(
            viewer=request.user,
            target_user=target_user,
            defaults={"last_seen_post_at": timezone.now()},
        )
        # Registra visualização individual de cada post
        for p in posts:
            SocialPostView.objects.get_or_create(post=p, viewer=request.user)

    # Tarefas do dia (só para o próprio)
    today_tasks = []
    overdue_tasks = []
    if is_me:
        all_tasks = _get_today_tasks(target_user)
        for c in all_tasks:
            if c.due_date and c.due_date < today:
                overdue_tasks.append(c)
            else:
                today_tasks.append(c)

    # Sugestões de amigos por unidade + tutorial de onboarding
    show_unit_tutorial = False
    show_onboarding_tour = False
    unit_suggestions = []
    available_units = []
    if is_me:
        show_unit_tutorial = not prof.unidade and not prof.onboarding_done
        show_onboarding_tour = not prof.onboarding_done
        available_units = list(
            UserProfile.objects
            .exclude(unidade="")
            .values_list("unidade", flat=True)
            .distinct()
            .order_by("unidade")
        )
        # IDs de amigos aceitos (SocialFriendship)
        accepted_out = set(SocialFriendship.objects.filter(
            requester=target_user, status="accepted"
        ).values_list("receiver_id", flat=True))
        accepted_in = set(SocialFriendship.objects.filter(
            receiver=target_user, status="accepted"
        ).values_list("requester_id", flat=True))
        my_friend_ids = accepted_out | accepted_in

        # Pendentes enviados/recebidos (para não mostrar botão duplo)
        pending_out = set(SocialFriendship.objects.filter(
            requester=target_user, status="pending"
        ).values_list("receiver_id", flat=True))
        pending_in = set(SocialFriendship.objects.filter(
            receiver=target_user, status="pending"
        ).values_list("requester_id", flat=True))

        exclude_ids = my_friend_ids | pending_out | pending_in | {target_user.id}

        # Sugestões = TODOS os usuários ativos (exceto eu e amigos/pendentes)
        unit_suggestions = list(
            User.objects.filter(is_active=True)
            .exclude(id__in=exclude_ids)
            .select_related("profile")
            .order_by("profile__display_name")[:40]
        )

    # Meus Amigos (amizades aceitas) — só para o dono
    real_friends = []
    board_friends = []  # mantém para compat
    my_boards = []
    board_columns_map = {}
    if is_me:
        accepted_out = set(SocialFriendship.objects.filter(
            requester=target_user, status="accepted"
        ).values_list("receiver_id", flat=True))
        accepted_in = set(SocialFriendship.objects.filter(
            receiver=target_user, status="accepted"
        ).values_list("requester_id", flat=True))
        real_friend_ids = accepted_out | accepted_in
        if real_friend_ids:
            real_friends = list(
                User.objects.filter(id__in=real_friend_ids)
                .select_related("profile")
                .order_by("profile__display_name")
            )
        # Quadros que o usuário pode compartilhar (owner ou editor)
        my_boards = list(
            Board.objects.filter(
                memberships__user=target_user,
                memberships__role__in=["owner", "editor"],
                is_deleted=False,
                is_archived=False,
            ).values("id", "name").distinct().order_by("name")
        )
        # Mapa board_id → colunas (para filtro JS)
        board_ids = [b["id"] for b in my_boards]
        _cols = Column.objects.filter(board_id__in=board_ids, is_deleted=False).order_by("position").values("id", "name", "board_id")
        board_columns_map = {}
        for c in _cols:
            board_columns_map.setdefault(str(c["board_id"]), []).append({"id": c["id"], "name": c["name"]})

    # Pílulas de comentários não vistos (só para o dono)
    unread_comment_posts = []
    unread_reply_items = []
    if is_me:
        from django.db.models import Count
        unseen_qs = (
            SocialPostComment.objects
            .filter(post__user=target_user, seen_by_owner=False)
            .exclude(user=target_user)
            .values("post_id", "post__text")
            .annotate(count=Count("id"))
            .order_by("-post_id")
        )
        for row in unseen_qs:
            unread_comment_posts.append({
                "post_id": row["post_id"],
                "text": (row["post__text"] or "")[:50],
                "count": row["count"],
            })

        # Pílulas de respostas não vistas (Paulo respondeu ao meu comentário)
        unread_reply_items = list(
            SocialPostComment.objects
            .filter(reply_to__user=target_user, reply_seen=False)
            .exclude(user=target_user)
            .select_related("user", "post__user")
            .order_by("-created_at")[:10]
        )
        for r in unread_reply_items:
            r.replier_name = _get_or_create_profile(r.user).display_name or r.user.email

    # Convites de amizade pendentes recebidos
    pending_friend_requests = []
    # Convites que EU enviei (pendentes)
    sent_friend_requests = []
    if is_me:
        pending_friend_requests = list(
            SocialFriendship.objects.filter(
                receiver=target_user, status="pending"
            ).select_related("requester", "requester__profile")
            .order_by("-created_at")
        )
        sent_friend_requests = list(
            SocialFriendship.objects.filter(
                requester=target_user, status="pending"
            ).select_related("receiver", "receiver__profile")
            .order_by("-created_at")
        )

    # Mood choices para o seletor
    mood_choices = DailyCheckIn.MOOD_CHOICES
    mood_emojis = DailyCheckIn.MOOD_EMOJIS

    ctx = {
        "target_user": target_user,
        "profile": prof,
        "posts": posts,
        "is_me": is_me,
        "checkin": checkin,
        "latest_checkin": latest_checkin,
        "today_tasks": today_tasks,
        "overdue_tasks": overdue_tasks,
        "today": today,
        "mood_choices": mood_choices,
        "mood_emojis": mood_emojis,
        "unread_comment_posts": unread_comment_posts,
        "unread_reply_items": unread_reply_items,
        "board_friends": board_friends,
        "real_friends": real_friends,
        "my_boards": my_boards,
        "board_columns_map": json.dumps(board_columns_map) if is_me else "{}",
        "show_unit_tutorial": show_unit_tutorial,
        "unit_suggestions": unit_suggestions,
        "available_units": available_units,
        "pending_friend_requests": pending_friend_requests,
        "sent_friend_requests": sent_friend_requests,
        "show_onboarding_tour": show_onboarding_tour,
    }
    if extra:
        ctx.update(extra)
    return ctx


# ---------------------------------------------------------------
# Página social standalone (GET) — /social/ ou /social/<user_id>/
# ---------------------------------------------------------------
@login_required
def social_page(request, user_id: int = None, handle: str = None):
    """Página standalone do espaço social — pode dar F5 e continuar."""
    if handle:
        target_user = get_object_or_404(UserProfile, handle=handle).user
    elif user_id:
        target_user = get_object_or_404(User, id=user_id)
    else:
        target_user = request.user
    ctx = _build_social_context(request, target_user)
    return render(request, "boards/social_page.html", ctx)


# ---------------------------------------------------------------
# Página de post individual (GET) — /social/post/<id>/view/
# ---------------------------------------------------------------
@login_required
def social_post_page(request, post_id: int):
    """Abre MEU perfil e exibe a publicação em modal."""
    post = get_object_or_404(SocialPost, id=post_id, is_active=True)
    ctx = _build_social_context(request, request.user)
    ctx["modal_post_id"] = post.id
    return render(request, "boards/social_page.html", ctx)


# ---------------------------------------------------------------
# Dados completos de um post (GET → JSON) — para modal
# ---------------------------------------------------------------
@login_required
def social_post_full(request, post_id: int):
    """Retorna JSON completo de um post: autor, mídia, reações, comentários."""
    post = get_object_or_404(SocialPost, id=post_id, is_active=True)

    # Autor
    author = _user_card(post.user)

    # Mídia
    photo_url = post.photo.url if post.photo else None
    video_url = post.video.url if post.video else None

    # Friendship post
    is_friendship = False
    friendship_data = None
    if post.text.startswith("__friendship__:"):
        is_friendship = True
        try:
            friend_uid = int(post.text.split(":")[1])
            friend_user = User.objects.select_related("profile").get(id=friend_uid)
            is_friendship = True
            friendship_data = {
                "user": _user_card(post.user),
                "friend": _user_card(friend_user),
            }
        except Exception:
            pass

    # Se é repost, herda do original
    is_repost = False
    original_author = None
    text = post.text
    text_style = post.text_style
    if post.shared_from_id:
        is_repost = True
        try:
            orig = SocialPost.objects.select_related("user__profile").get(
                id=post.shared_from_id, is_active=True
            )
            original_author = _user_card(orig.user)
            if not text and orig.text:
                text = orig.text
            if not text_style and orig.text_style:
                text_style = orig.text_style
            if not photo_url and orig.photo:
                photo_url = orig.photo.url
            if not video_url and orig.video:
                video_url = orig.video.url
        except SocialPost.DoesNotExist:
            pass

    # Reações
    reactions = SocialPostReaction.objects.filter(post=post).select_related("user", "user__profile")
    reaction_counts = dict(Counter(r.reaction for r in reactions))
    my_reaction = next((r.reaction for r in reactions if r.user_id == request.user.id), None)

    # Comentários
    comments_qs = (
        SocialPostComment.objects
        .filter(post=post, is_active=True)
        .select_related("user", "user__profile")
        .order_by("created_at")
    )
    comments = []
    for c in comments_qs:
        c_prof = getattr(c.user, "profile", None)
        c_avatar = None
        if c_prof and c_prof.avatar:
            c_avatar = c_prof.avatar.url
        elif c_prof and c_prof.avatar_choice:
            from django.templatetags.static import static
            c_avatar = static(f"images/avatar/{c_prof.avatar_choice}")
        comments.append({
            "id": c.id,
            "author": c_prof.display_name if c_prof else c.user.email,
            "avatar": c_avatar,
            "text": c.text,
            "time": timezone.localtime(c.created_at).strftime("%d/%m %H:%M"),
            "reply_to_id": c.reply_to_id,
        })

    # Views
    view_count = SocialPostView.objects.filter(post=post).count()

    # Registra visualização
    SocialPostView.objects.get_or_create(post=post, viewer=request.user)

    return JsonResponse({
        "id": post.id,
        "author": author,
        "text": text,
        "text_style": text_style,
        "photo": photo_url,
        "video": video_url,
        "gif_url": post.gif_url or None,
        "sticker_url": post.sticker_url or None,
        "is_repost": is_repost,
        "original_author": original_author,
        "is_friendship": is_friendship,
        "friendship_data": friendship_data,
        "reaction_counts": reaction_counts,
        "my_reaction": my_reaction,
        "total_reactions": len(list(reactions)),
        "comments": comments,
        "comment_count": len(comments),
        "view_count": view_count + 1,
        "visibility": post.visibility,
        "created_at": timezone.localtime(post.created_at).strftime("%d/%m/%Y %H:%M"),
        "is_mine": post.user_id == request.user.id,
    })


# ---------------------------------------------------------------
# Painel social principal (GET)
# ---------------------------------------------------------------
@login_required
def social_posts_panel(request, user_id: int):
    target_user = get_object_or_404(User, id=user_id)
    if not _can_see_social(request, target_user):
        raise Http404
    ctx = _build_social_context(request, target_user)
    return render(request, "boards/social_panel.html", ctx)


# ---------------------------------------------------------------
# Detalhes de um post (JSON) — comentários
# ---------------------------------------------------------------
@login_required
def social_post_detail(request, post_id: int):
    """Retorna comentários de um post como JSON."""
    post = get_object_or_404(SocialPost, id=post_id, is_active=True)
    comments = list(
        SocialPostComment.objects
        .filter(post=post, is_active=True)
        .select_related("user", "user__profile")
        .order_by("created_at")
    )
    # Prefetch reações de comentários
    comment_ids = [c.id for c in comments]
    all_creacts = SocialCommentReaction.objects.filter(comment_id__in=comment_ids)
    creact_map = {}  # comment_id -> {reaction: count}
    my_creact_map = {}  # comment_id -> reaction
    for cr in all_creacts:
        creact_map.setdefault(cr.comment_id, Counter())[cr.reaction] += 1
        if cr.user_id == request.user.id:
            my_creact_map[cr.comment_id] = cr.reaction

    result = []
    for c in comments:
        prof = getattr(c.user, "profile", None)
        counts = dict(creact_map.get(c.id, {}))
        result.append({
            "id": c.id,
            "author": prof.display_name if prof else c.user.email,
            "text": c.text,
            "time": timezone.localtime(c.created_at).strftime("%d/%m %H:%M"),
            "reaction_counts": counts,
            "my_reaction": my_creact_map.get(c.id),
        })
    return JsonResponse({"comments": result})


# ---------------------------------------------------------------
# Feed de amigos (JSON) — para o reel horizontal
# ---------------------------------------------------------------
@login_required
def social_friends_feed(request):
    """Retorna posts de amigos (accepted friendships) como JSON.
    Se ?all=1, retorna posts de todos os usuários.
    """
    me = request.user
    show_all = request.GET.get("all") == "1"

    # Últimos 3 dias apenas
    three_days_ago = timezone.now() - timedelta(days=3)

    if show_all:
        # Todos os posts (exceto os do próprio)
        posts = list(
            SocialPost.objects
            .filter(is_active=True, created_at__gte=three_days_ago)
            .exclude(user=me)
            .exclude(visibility="friends")
            .select_related("user", "user__profile")
            .order_by("-created_at")
        )
    else:
        # Somente amizades aceitas
        accepted_out = SocialFriendship.objects.filter(
            requester=me, status="accepted"
        ).values_list("receiver_id", flat=True)
        accepted_in = SocialFriendship.objects.filter(
            receiver=me, status="accepted"
        ).values_list("requester_id", flat=True)
        friend_ids = set(accepted_out)
        friend_ids.update(accepted_in)
        friend_ids.discard(me.id)

        # Incluir o próprio usuário para que veja seus posts no reel
        feed_ids = set(friend_ids)
        feed_ids.add(me.id)

        posts = list(
            SocialPost.objects
            .filter(user_id__in=feed_ids, is_active=True, created_at__gte=three_days_ago)
            .select_related("user", "user__profile")
            .order_by("-created_at")
        )

    # Ordenar: por dia (desc), depois vídeos > imagens > texto, cronológico dentro do tipo
    def _media_rank(p):
        if p.video:
            return 0  # vídeos primeiro
        if p.photo:
            return 1  # imagens depois
        if p.gif_url or p.sticker_url:
            return 1  # GIF/sticker = mesmo nível de imagem
        return 2      # texto por último

    def _sort_key(p):
        local_dt = timezone.localtime(p.created_at)
        day = local_dt.date()
        return (-day.toordinal(), _media_rank(p), -local_dt.timestamp())

    posts.sort(key=_sort_key)

    if not posts:
        return JsonResponse({"posts": []})

    # Prefetch reactions
    post_ids = [p.id for p in posts]
    reactions_by_post = defaultdict(list)
    for r in SocialPostReaction.objects.filter(post_id__in=post_ids).select_related("user"):
        reactions_by_post[r.post_id].append(r)
    comments_by_post = defaultdict(int)
    for pid, cnt in (
        SocialPostComment.objects
        .filter(post_id__in=post_ids)
        .values_list("post_id")
        .annotate(cnt=models.Count("id"))
    ):
        comments_by_post[pid] = cnt

    # Prefetch shared_from (reposts)
    shared_ids = [p.shared_from_id for p in posts if p.shared_from_id]
    shared_posts = {}
    if shared_ids:
        for sp in SocialPost.objects.filter(id__in=shared_ids).select_related("user", "user__profile"):
            shared_posts[sp.id] = sp

    def _avatar_url(prof):
        """Retorna URL do avatar: upload > avatar_choice > vazio."""
        if prof and getattr(prof, "avatar", None):
            try:
                return prof.avatar.url
            except Exception:
                pass
        if prof and getattr(prof, "avatar_choice", ""):
            from django.templatetags.static import static
            return static(f"images/avatar/{prof.avatar_choice}")
        return ""

    result = []
    for p in posts:
        prof = getattr(p.user, "profile", None)
        p_reactions = reactions_by_post.get(p.id, [])
        my_reaction = next((r.reaction for r in p_reactions if r.user_id == me.id), None)

        # Se for repost, usa mídia/texto do original
        display_post = p
        shared_info = None
        if p.shared_from_id and p.shared_from_id in shared_posts:
            orig = shared_posts[p.shared_from_id]
            display_post = orig
            orig_prof = getattr(orig.user, "profile", None)
            shared_info = {
                "original_user_name": orig_prof.display_name if orig_prof else orig.user.get_full_name(),
                "original_user_id": orig.user_id,
                "original_user_avatar": _avatar_url(orig_prof),
            }

        # Detectar post de amizade
        friendship_data = None
        if display_post.text.startswith("__friendship__:"):
            try:
                friend_uid = int(display_post.text.split(":")[1])
                friend_user = User.objects.select_related("profile").get(id=friend_uid)
                friend_prof = getattr(friend_user, "profile", None)
                friendship_data = {
                    "friend_name": friend_prof.display_name if friend_prof else friend_user.get_full_name(),
                    "friend_avatar": _avatar_url(friend_prof),
                    "friend_id": friend_uid,
                    "user_name": prof.display_name if prof else p.user.get_full_name(),
                    "user_avatar": _avatar_url(prof),
                }
            except Exception:
                pass

        result.append({
            "id": p.id,
            "user_name": prof.display_name if prof else p.user.get_full_name(),
            "user_avatar": _avatar_url(prof),
            "user_id": p.user_id,
            "text": display_post.text if not friendship_data else "",
            "photo": display_post.photo.url if display_post.photo else "",
            "video": display_post.video.url if display_post.video else "",
            "gif_url": display_post.gif_url,
            "sticker_url": display_post.sticker_url,
            "created_at": timezone.localtime(p.created_at).strftime("%d/%m %H:%M"),
            "reaction_counts": dict(Counter(r.reaction for r in p_reactions)),
            "total_reactions": len(p_reactions),
            "my_reaction": my_reaction,
            "comment_count": comments_by_post.get(p.id, 0),
            "shared_from": shared_info,
            "friendship": friendship_data,
        })

    return JsonResponse({"posts": result})


# ---------------------------------------------------------------
# Criar post (POST)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_post_create(request):
    text = (request.POST.get("text") or "").strip()
    photo = request.FILES.get("photo")
    video = request.FILES.get("video")
    media = request.FILES.get("media")

    # media field (gallery) — detecta tipo automaticamente
    if media and not photo and not video:
        ct = (media.content_type or "").lower()
        if ct.startswith("video/"):
            video = media
        else:
            photo = media

    gif_url = (request.POST.get("gif_url") or "").strip()
    sticker_url = (request.POST.get("sticker_url") or "").strip()
    text_style_raw = (request.POST.get("text_style") or "").strip()
    text_style = None
    if text_style_raw:
        try:
            text_style = json.loads(text_style_raw)
        except (json.JSONDecodeError, TypeError):
            pass
    visibility = (request.POST.get("visibility") or "all").strip()
    if visibility not in ("all", "friends"):
        visibility = "all"

    extra = {}
    if not text and not photo and not video and not gif_url and not sticker_url:
        extra["post_error"] = "Adicione um texto, foto ou vídeo antes de publicar."
    else:
        post = SocialPost.objects.create(
            user=request.user,
            text=text,
            photo=photo or None,
            video=video or None,
            gif_url=gif_url,
            sticker_url=sticker_url,
            text_style=text_style,
            visibility=visibility,
        )
        # Notificar @menções
        if text:
            _notify_mentions(text, request.user, post.id, context="post")
        # AI react trigger
        parts = []
        if text:
            parts.append(f"Publicou: {text}")
        if photo:
            parts.append("Enviou uma foto")
        if video:
            parts.append("Enviou um vídeo")
        extra["ai_react_text"] = "; ".join(parts)
        extra["focus_post_id"] = post.id

    ctx = _build_social_context(request, request.user, extra)
    return render(request, "boards/social_panel.html", ctx)


# ---------------------------------------------------------------
# Deletar post (POST)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_post_delete(request, post_id: int):
    post = get_object_or_404(SocialPost, id=post_id, user=request.user)
    post.is_active = False
    post.save(update_fields=["is_active"])
    ctx = _build_social_context(request, request.user)
    return render(request, "boards/social_panel.html", ctx)


# ---------------------------------------------------------------
# Editar post (POST → JSON)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_post_edit(request, post_id: int):
    """Edita texto e/ou visibilidade de um post. Salva versão anterior."""
    post = get_object_or_404(SocialPost, id=post_id, user=request.user)

    # Salvar versão anterior (audit trail — nunca apagar)
    SocialPostVersion.objects.create(
        post=post,
        text=post.text,
        photo=post.photo if post.photo else None,
        video=post.video if post.video else None,
        gif_url=post.gif_url,
        sticker_url=post.sticker_url,
        visibility=post.visibility,
    )

    new_text = request.POST.get("text")
    new_visibility = request.POST.get("visibility")

    updated = []
    if new_text is not None:
        post.text = new_text.strip()
        updated.append("text")
    if new_visibility in ("all", "friends"):
        post.visibility = new_visibility
        updated.append("visibility")

    if updated:
        post.save(update_fields=updated)

    return JsonResponse({
        "ok": True,
        "id": post.id,
        "text": post.text,
        "visibility": post.visibility,
    })


# ---------------------------------------------------------------
# Alternar visibilidade do post (all ↔ friends)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_post_toggle_visibility(request, post_id: int):
    post = get_object_or_404(SocialPost, id=post_id, user=request.user)
    post.visibility = "friends" if post.visibility == "all" else "all"
    post.save(update_fields=["visibility"])
    return JsonResponse({"visibility": post.visibility})


# ---------------------------------------------------------------
# Daily check-in (POST)
# ---------------------------------------------------------------
@login_required
@require_POST
def daily_checkin_save(request):
    today = timezone.localdate()
    checkin, _ = DailyCheckIn.objects.get_or_create(user=request.user, date=today)

    mood = (request.POST.get("mood") or "").strip()
    mood_note = (request.POST.get("mood_note") or "").strip()
    lunch_text = (request.POST.get("lunch_text") or "").strip()
    daily_posto = (request.POST.get("daily_posto") or "").strip()
    lunch_photo = request.FILES.get("lunch_photo")

    if mood:
        checkin.mood = mood
    if mood_note:
        checkin.mood_note = mood_note
    if lunch_text:
        checkin.lunch_text = lunch_text
    if daily_posto:
        checkin.daily_posto = daily_posto
    if lunch_photo:
        checkin.lunch_photo = lunch_photo

    update_fields = ["mood", "mood_note", "lunch_text", "daily_posto"]
    if lunch_photo:
        update_fields.append("lunch_photo")

    checkin.save(update_fields=update_fields)

    # Se marcou posto fixo
    prof = _get_or_create_profile(request.user)
    if request.POST.get("fixed_posto") == "1":
        prof.fixed_posto = True
        prof.posto = daily_posto or prof.posto
        prof.save(update_fields=["fixed_posto", "posto"])
    elif request.POST.get("fixed_posto") == "0":
        prof.fixed_posto = False
        prof.save(update_fields=["fixed_posto"])

    # Auto-post mood to feed (somente se mudou o humor AGORA)
    if mood:
        mood_emojis = {
            "excited": "🤩", "happy": "😊", "calm": "😌",
            "normal": "😐", "tired": "😪", "stressed": "😤", "sick": "🤒",
        }
        mood_labels = dict(DailyCheckIn.MOOD_CHOICES)
        emoji = mood_emojis.get(mood, "😊")
        label = mood_labels.get(mood, mood)
        post_text = f"{emoji} {label}"
        if mood_note:
            post_text += f" — {mood_note}"
        # Evitar duplicata: não criar se já postou mood hoje
        already_posted = SocialPost.objects.filter(
            user=request.user,
            created_at__date=today,
            text__startswith=emoji,
        ).exists()
        if not already_posted:
            SocialPost.objects.create(user=request.user, text=post_text)

    # Auto-post lunch to feed
    if lunch_text or lunch_photo:
        post_text = f"🍽️ {lunch_text}" if lunch_text else "🍽️ Almoço do dia"
        SocialPost.objects.create(
            user=request.user,
            text=post_text,
            photo=lunch_photo or None,
        )

    # AI react trigger — só o que foi ALTERADO nesta requisição
    parts = []
    if mood:
        mood_labels = dict(DailyCheckIn.MOOD_CHOICES)
        parts.append(f"Atualizei meu humor para: {mood_labels.get(mood, mood)}")
    if lunch_text:
        parts.append(f"Vou almoçar: {lunch_text}")
    if lunch_photo and not lunch_text:
        parts.append("Postei uma foto do meu almoço")
    ai_react_text = "; ".join(parts) if parts else ""

    ctx = _build_social_context(request, request.user, extra={"ai_react_text": ai_react_text})
    return render(request, "boards/social_panel.html", ctx)


# ---------------------------------------------------------------
# Cover photo upload (POST)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_cover_upload(request):
    prof = _get_or_create_profile(request.user)
    f = request.FILES.get("cover_photo")
    extra = {}
    if f:
        from django.core.files.base import ContentFile
        f.seek(0)
        cover_bytes = f.read()
        f.seek(0)
        prof.cover_photo = f
        prof.save(update_fields=["cover_photo"])
        SocialPost.objects.create(
            user=request.user,
            text="📸 Atualizei minha foto de capa!",
            photo=ContentFile(cover_bytes, name="cover.jpg"),
        )
        extra["ai_react_text"] = "Troquei a foto de capa do meu perfil"
    else:
        extra["cover_error"] = "Selecione uma imagem."

    ctx = _build_social_context(request, request.user, extra)
    return render(request, "boards/social_panel.html", ctx)


# ---------------------------------------------------------------
# Mood check-in via IA (POST → JSON)
# ---------------------------------------------------------------
@login_required
@require_POST
def mood_checkin(request):
    text = (request.POST.get("text") or "").strip()
    if not text:
        return JsonResponse({"error": "Escreva como você está se sentindo."}, status=400)

    system_prompt = (
        "Você é um assistente empático e motivador. "
        "O usuário compartilhou como está se sentindo. "
        "Faça uma análise breve e gentil do estado emocional (2-3 frases), "
        "ofereça uma palavra de acolhimento e sugira uma ação simples de autocuidado. "
        "Seja caloroso, humano e conciso. Responda sempre em português brasileiro."
    )
    response = _groq_chat([{"role": "user", "content": text}], system_prompt)
    return JsonResponse({"response": response, "mood_text": text})


# ---------------------------------------------------------------
# Chatbot motivacional (POST → JSON)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_chatbot_message(request):
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    message = (data.get("message") or "").strip()
    history = data.get("history") or []

    if not message:
        return JsonResponse({"error": "Mensagem vazia."}, status=400)

    cfg = CamilaConfig.get()
    system_prompt = cfg.prompt_coach

    messages = [*history[-10:], {"role": "user", "content": message}]
    response = _groq_chat(messages, system_prompt, config=cfg)
    return JsonResponse({"response": response})


# ---------------------------------------------------------------
# Camila.AI — base de conhecimento helper
# ---------------------------------------------------------------

def _pop_relevance_score(pop: "CamilaPOP", query_words: set) -> int:
    """Pontua um POP pela quantidade de palavras da query que aparecem nele."""
    haystack = " ".join([
        pop.title, pop.code, pop.category, pop.raw_text, pop.extracted_text
    ]).lower()
    return sum(1 for w in query_words if w in haystack)


def _find_relevant_pops(query: str, max_pops: int = 6):
    """Retorna os POPs mais relevantes para a query (busca por palavras-chave)."""
    import re as _re
    query_words = set(_re.findall(r"[a-záàâãéêíóôõúüç]{4,}", query.lower()))
    pops = list(CamilaPOP.objects.filter(is_active=True))
    if not pops:
        return []
    if not query_words:
        return pops[:max_pops]
    scored = [(pop, _pop_relevance_score(pop, query_words)) for pop in pops]
    scored.sort(key=lambda x: -x[1])
    # Retorna os relevantes (score > 0) + completa com os primeiros se precisar
    relevant = [p for p, s in scored if s > 0][:max_pops]
    if not relevant:
        relevant = [p for p, _ in scored[:3]]
    return relevant


def _pop_index_block(pops) -> str:
    """Bloco compacto com título + código + link de todos os POPs (índice)."""
    if not pops:
        return ""
    lines = ["\n\n--- ÍNDICE DE POPs DISPONÍVEIS (todos os procedimentos) ---"]
    lines.append("Para qualquer um destes POPs, informe o título, código e o link de download.")
    current_cat = None
    for pop in sorted(pops, key=lambda p: (p.category, p.code)):
        if pop.category != current_cat:
            current_cat = pop.category
            lines.append(f"\nSetor: {current_cat or 'Geral'}")
        prefix = f"[{pop.code}] " if pop.code else ""
        pdf_link = f" — PDF: /media/{pop.pdf_file.name}" if pop.pdf_file else ""
        lines.append(f"  • {prefix}{pop.title}{pdf_link}")
    return "\n".join(lines)


def _camila_knowledge_prompt(query: str = "") -> str:
    """Monta bloco de conhecimento.
    - Inclui base de conhecimento completa
    - Inclui texto INTEGRAL dos POPs relevantes para a query
    - Inclui índice compacto de todos os POPs (títulos + links)
    """
    lines = []

    entries = CamilaKnowledge.objects.filter(is_active=True)
    if entries.exists():
        lines.append("\n\n--- BASE DE CONHECIMENTO DA CAMIM ---")
        for e in entries:
            lines.append(f"\n[{e.get_category_display()}] {e.title}:\n{e.content}")
        lines.append("\n--- FIM DA BASE DE CONHECIMENTO ---\n")

    all_pops = list(CamilaPOP.objects.filter(is_active=True))
    if all_pops:
        # Índice de todos os POPs (compacto — sempre presente)
        lines.append(_pop_index_block(all_pops))

        # Texto completo dos POPs relevantes para esta query
        relevant = _find_relevant_pops(query, max_pops=5) if query else all_pops[:3]
        lines.append("\n\n--- CONTEÚDO COMPLETO DOS POPs RELEVANTES ---")
        lines.append("Use estas informações para responder com precisão. Cite o código, setor e ofereça o link de download.")
        for pop in relevant:
            prefix = f"[{pop.code}] " if pop.code else ""
            lines.append(f"\n### {prefix}{pop.title} — Setor: {pop.category or 'Geral'}")
            if pop.pdf_file:
                lines.append(f"Download do PDF completo: /media/{pop.pdf_file.name}")
            # Usa texto integral; se não tiver, usa o resumo
            content = pop.raw_text or pop.extracted_text
            lines.append(content[:8000])  # até 8000 chars por POP relevante

    return "\n".join(lines)


@login_required
@require_POST
def social_comments_mark_seen(request, post_id: int):
    """Marca todos os comentários não vistos de um post como vistos pelo dono."""
    post = get_object_or_404(SocialPost, id=post_id, user=request.user)
    SocialPostComment.objects.filter(post=post, seen_by_owner=False).update(seen_by_owner=True)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def social_ai_react(request):
    """Retorna uma reação rápida da Camila.AI sobre a ação do usuário."""
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    context = (data.get("context") or "").strip()
    if not context:
        return JsonResponse({"response": ""})

    cfg = CamilaConfig.get()
    prompt = cfg.prompt_react + _camila_knowledge_prompt()
    response = _groq_chat(
        [{"role": "user", "content": context}],
        prompt,
        config=cfg,
    )
    return JsonResponse({"response": response})


def _get_weather_context() -> str:
    """Busca clima atual do Rio de Janeiro via OpenMeteo (cache 30 min)."""
    from django.core.cache import cache
    import requests as _requests

    cached = cache.get("camila_weather_ctx")
    if cached:
        return cached

    _WMO = {
        0: "céu limpo ☀️", 1: "principalmente limpo ☀️", 2: "parcialmente nublado ⛅",
        3: "nublado ☁️", 45: "névoa 🌫️", 48: "névoa 🌫️",
        51: "garoa leve 🌦️", 53: "garoa 🌦️", 55: "garoa intensa 🌦️",
        61: "chuva leve 🌧️", 63: "chuva 🌧️", 65: "chuva forte 🌧️",
        71: "neve leve ❄️", 73: "neve ❄️", 75: "neve forte ❄️",
        80: "pancadas de chuva 🌧️", 81: "pancadas 🌧️", 82: "pancadas fortes 🌧️",
        95: "trovoada ⛈️", 96: "trovoada ⛈️", 99: "trovoada ⛈️",
    }
    try:
        r = _requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": -22.9068, "longitude": -43.1729,
                "current": "weather_code,temperature_2m,relative_humidity_2m,wind_speed_10m",
                "timezone": "America/Sao_Paulo",
            },
            timeout=3,
        )
        cur = r.json().get("current", {})
        code = cur.get("weather_code")
        temp = cur.get("temperature_2m")
        hum  = cur.get("relative_humidity_2m")
        wind = cur.get("wind_speed_10m")
        desc = _WMO.get(int(code), "tempo variável") if code is not None else "tempo variável"
        parts = [f"{desc}", f"{temp:.0f}°C" if temp is not None else None,
                 f"umidade {hum:.0f}%" if hum is not None else None,
                 f"vento {wind:.0f} km/h" if wind is not None else None]
        ctx = "\n\n[Clima atual no Rio de Janeiro: " + ", ".join(p for p in parts if p) + "]"
        cache.set("camila_weather_ctx", ctx, 1800)
        return ctx
    except Exception:
        return ""


@login_required
@require_POST
def social_camila_chat(request):
    """Chat conversacional com a Camila.AI."""
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    message = (data.get("message") or "").strip()
    history = data.get("history") or []

    if not message:
        return JsonResponse({"error": "Mensagem vazia."}, status=400)

    cfg = CamilaConfig.get()

    social_ctx = (
        "\n\n[REGRAS IMPORTANTES]\n"
        "1. Você está DENTRO da rede social interna da CAMIM (tarefas.camim.com.br/social/).\n"
        "2. NUNCA diga 'não entendi'. Se a mensagem for curta (ex: 'como?', 'como fazer?', 'sim'), "
        "INTERPRETE pelo contexto da conversa anterior (history). Se você sugeriu publicar e o usuário "
        "disse 'como?', ele quer saber COMO publicar.\n"
        "3. Respostas CURTAS e DIRETAS. Máximo 3-4 frases. Sem enrolação.\n"
        "4. NUNCA redirecione para Central de Atendimento para dúvidas sobre a rede social.\n"
        "\n[COMO USAR A REDE SOCIAL]\n"
        "- PUBLICAR: tocar no botão + (roxo, canto inferior direito) → escrever texto, "
        "escolher foto/vídeo da galeria ou tirar na hora → enviar.\n"
        "- REAGIR: nos posts do feed, tocar em 👍 ❤️ 😂 🔥 👏.\n"
        "- COMENTAR: campo abaixo de cada post → digitar → enviar.\n"
        "- PERFIL: tocar no avatar → editar foto, capa, posto, setor, telefone.\n"
        "- HUMOR: seção 'Como tá o astral?' → escolher emoji.\n"
        "- QUADROS/TAREFAS: acessar tarefas.camim.com.br (fora da rede social).\n"
    )

    prompt = cfg.prompt_chat + social_ctx + _camila_knowledge_prompt(message) + _get_weather_context()
    messages = [*history[-10:], {"role": "user", "content": message}]
    response = _groq_chat(messages, prompt, config=cfg)
    return JsonResponse({"response": response})


# ---------------------------------------------------------------
# Reação a post (POST → JSON)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_post_react(request, post_id: int):
    post = get_object_or_404(SocialPost, id=post_id)
    reaction_type = (request.POST.get("reaction") or "").strip()

    # Aceita presets (like, love, etc.) ou qualquer emoji direto
    valid_presets = dict(SocialPostReaction.REACTION_CHOICES)
    if reaction_type not in valid_presets and len(reaction_type) > 16:
        return JsonResponse({"error": "Reação inválida."}, status=400)
    if not reaction_type:
        return JsonResponse({"error": "Reação inválida."}, status=400)

    existing = SocialPostReaction.objects.filter(user=request.user, post=post).first()
    my_reaction = None

    if existing:
        if existing.reaction == reaction_type:
            existing.delete()  # toggle off
        else:
            existing.reaction = reaction_type
            existing.save()
            my_reaction = reaction_type
    else:
        SocialPostReaction.objects.create(
            user=request.user, post=post, reaction=reaction_type,
        )
        my_reaction = reaction_type

    counts = dict(Counter(
        SocialPostReaction.objects.filter(post=post).values_list("reaction", flat=True)
    ))

    return JsonResponse({
        "my_reaction": my_reaction,
        "counts": counts,
        "total": sum(counts.values()),
    })


# ---------------------------------------------------------------
# Reação a comentário
# ---------------------------------------------------------------
@login_required
@require_POST
def social_comment_react(request, comment_id: int):
    comment = get_object_or_404(SocialPostComment, id=comment_id)
    reaction_type = (request.POST.get("reaction") or "").strip()

    valid = dict(SocialCommentReaction.REACTION_CHOICES)
    if reaction_type not in valid:
        return JsonResponse({"error": "Reação inválida."}, status=400)

    existing = SocialCommentReaction.objects.filter(
        user=request.user, comment=comment
    ).first()
    my_reaction = None

    if existing:
        if existing.reaction == reaction_type:
            existing.delete()
        else:
            existing.reaction = reaction_type
            existing.save()
            my_reaction = reaction_type
    else:
        SocialCommentReaction.objects.create(
            user=request.user, comment=comment, reaction=reaction_type,
        )
        my_reaction = reaction_type

    counts = dict(Counter(
        SocialCommentReaction.objects.filter(comment=comment).values_list("reaction", flat=True)
    ))

    return JsonResponse({
        "my_reaction": my_reaction,
        "counts": counts,
        "total": sum(counts.values()),
    })


# ---------------------------------------------------------------
# Like em card → publica no feed social
# ---------------------------------------------------------------
@login_required
@require_POST
def card_like_social(request, card_id: int):
    """Curte um card e publica automaticamente no feed social."""
    card = get_object_or_404(Card, id=card_id)
    board = card.column.board
    user_name = request.user.get_full_name() or request.user.username
    card_url = request.build_absolute_uri(f"/board/{board.id}/?card={card.id}")
    text = (
        f"👍 {user_name} curtiu o card: {card.title}\n"
        f"📋 Quadro: {board.name}\n"
        f"🔗 {card_url}"
    )
    post_kwargs = {"user": request.user, "text": text}
    if card.cover_image:
        post_kwargs["photo"] = card.cover_image
    SocialPost.objects.create(**post_kwargs)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------
# Comentário em post (POST → JSON)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_post_comment(request, post_id: int):
    post = get_object_or_404(SocialPost, id=post_id)
    text = (request.POST.get("text") or "").strip()

    if not text:
        return JsonResponse({"error": "Comentário vazio."}, status=400)

    # Resposta a outro comentário?
    reply_to = None
    reply_to_id = request.POST.get("reply_to_id")
    if reply_to_id:
        try:
            reply_to = SocialPostComment.objects.select_related("user").get(
                id=int(reply_to_id), post=post
            )
        except (SocialPostComment.DoesNotExist, ValueError):
            pass

    # reply_seen=True se quem responde É o autor do comentário-pai (sem notificação)
    reply_seen = reply_to is None or (reply_to.user_id == request.user.id)

    # seen_by_owner=True se quem comenta é o próprio dono do post
    comment = SocialPostComment.objects.create(
        user=request.user,
        post=post,
        text=text,
        seen_by_owner=(request.user.id == post.user_id),
        reply_to=reply_to,
        reply_seen=reply_seen,
    )

    # Notificações sociais (email + WhatsApp)
    try:
        from boards.services.notifications import notify_social_interaction
        if reply_to:
            # Resposta a um comentário → avisa o autor do comentário
            if reply_to.user_id != request.user.id:
                notify_social_interaction(
                    recipient=reply_to.user,
                    actor=request.user,
                    kind="reply",
                    post_id=post.id,
                )
        else:
            # Comentário simples → avisa o dono do post
            if post.user_id != request.user.id:
                notify_social_interaction(
                    recipient=post.user,
                    actor=request.user,
                    kind="comment",
                    post_text=post.text or "",
                    post_id=post.id,
                )
    except Exception:
        _mention_logger.exception("social notify: unexpected error")

    # Notificar @menções no comentário
    _notify_mentions(text, request.user, post.id, context="comment")

    prof = _get_or_create_profile(request.user)
    reply_to_user = None
    if reply_to:
        rp = _get_or_create_profile(reply_to.user)
        reply_to_user = rp.display_name or reply_to.user.email

    return JsonResponse({
        "id": comment.id,
        "user": prof.display_name or request.user.email,
        "text": comment.text,
        "created_at": comment.created_at.strftime("%d/%m %H:%M"),
        "reply_to_id": reply_to.id if reply_to else None,
        "reply_to_user": reply_to_user,
    })


@login_required
@require_POST
def social_reply_seen(request, comment_id: int):
    """Marca uma resposta como vista pelo autor do comentário-pai."""
    SocialPostComment.objects.filter(
        id=comment_id,
        reply_to__user=request.user,
        reply_seen=False,
    ).update(reply_seen=True)
    return JsonResponse({"ok": True})


# Cache simples em memória para notícias (evita requisição a cada poll)
_news_cache: dict = {"ts": 0, "headlines": []}
_NEWS_TTL = 3 * 3600  # 3 horas

@login_required
def social_news_nudge(request):
    """Retorna manchetes do Google News Brasil (cache 3h)."""
    import time
    now = time.time()
    if now - _news_cache["ts"] > _NEWS_TTL:
        try:
            resp = http_requests.get(
                "https://news.google.com/rss?hl=pt-BR&gl=BR&ceid=BR:pt-419",
                timeout=6,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")[:6]
            headlines = []
            for item in items:
                title = (item.findtext("title") or "").strip()
                link  = (item.findtext("link")  or "").strip()
                # Remove source suffix " - Jornal X" do título do Google News
                if " - " in title:
                    title = title.rsplit(" - ", 1)[0].strip()
                if title and link:
                    headlines.append({"title": title[:120], "url": link})
            _news_cache["ts"] = now
            _news_cache["headlines"] = headlines
        except Exception:
            pass  # retorna cache anterior se houver falha
    return JsonResponse({"headlines": _news_cache["headlines"]})


# ---------------------------------------------------------------
# Avatar upload via social page (POST → JSON)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_avatar_upload(request):
    prof = _get_or_create_profile(request.user)
    f = request.FILES.get("avatar")
    if not f:
        return JsonResponse({"error": "Selecione uma imagem."}, status=400)
    ctype = (getattr(f, "content_type", "") or "").lower()
    if not ctype.startswith("image/"):
        return JsonResponse({"error": "Arquivo inválido."}, status=400)
    if f.size > 5 * 1024 * 1024:
        return JsonResponse({"error": "Imagem muito grande (máx 5MB)."}, status=400)
    prof.avatar = f
    from django.core.files.base import ContentFile
    prof.avatar_choice = ""
    # Read file content before saving (Django moves the file pointer)
    f.seek(0)
    avatar_bytes = f.read()
    f.seek(0)
    prof.save(update_fields=["avatar", "avatar_choice"])
    # Auto-post with a copy of the file
    SocialPost.objects.create(
        user=request.user,
        text="🤳 Nova foto de perfil!",
        photo=ContentFile(avatar_bytes, name="avatar.jpg"),
    )
    return JsonResponse({"url": prof.avatar.url})


# ---------------------------------------------------------------
# Social unread counts (GET → JSON) — para badge nos avatares
# ---------------------------------------------------------------
@login_required
def social_unread_counts(request):
    """
    Retorna quantos posts novos cada usuário publicou desde
    que o viewer viu o perfil dele pela última vez.
    Também detecta posts publicados nos últimos 30s (balão).
    """
    from django.core.cache import cache
    from django.utils import timezone as tz
    from datetime import timedelta

    # Pegar os user_ids que nos interessam (query param ids=1,2,3)
    ids_param = (request.GET.get("ids") or "").strip()
    if not ids_param:
        return JsonResponse({"counts": {}, "fresh": []})

    try:
        user_ids = [int(i) for i in ids_param.split(",") if i.strip().isdigit()]
    except ValueError:
        return JsonResponse({"counts": {}, "fresh": []})

    if not user_ids:
        return JsonResponse({"counts": {}, "fresh": []})

    now = tz.now()
    fresh_threshold = now - timedelta(seconds=40)  # posts dos últimos 40s

    # Mapa de last_seen_post_at por target_user_id
    seen_map = {
        s.target_user_id: s.last_seen_post_at
        for s in SocialPostSeen.objects.filter(
            viewer=request.user,
            target_user_id__in=user_ids,
        )
    }

    counts = {}
    fresh = []  # user_ids com post fresquinho (balão)

    posts_qs = SocialPost.objects.filter(
        user_id__in=user_ids, is_active=True
    ).values("user_id", "created_at", "text").order_by("user_id", "-created_at")

    from collections import defaultdict
    posts_by_user = defaultdict(list)
    for p in posts_qs:
        posts_by_user[p["user_id"]].append(p)

    fresh_texts = {}  # uid -> text do post fresquinho
    fresh_ts = {}     # uid -> timestamp ISO do post (chave única para sessionStorage)

    for uid in user_ids:
        last_seen = seen_map.get(uid)
        user_posts = posts_by_user.get(uid, [])

        if last_seen:
            unread = sum(1 for p in user_posts if p["created_at"] > last_seen)
        else:
            unread = len(user_posts)

        if unread > 0:
            counts[str(uid)] = unread

        # Balão: tem post publicado nos últimos 40s que o viewer ainda não viu?
        for p in user_posts:
            if p["created_at"] > fresh_threshold:
                if last_seen is None or p["created_at"] > last_seen:
                    fresh.append(uid)
                    fresh_texts[str(uid)] = (p["text"] or "").strip()[:80]
                    fresh_ts[str(uid)] = p["created_at"].isoformat()
                    break

    # Comentários não vistos nas MINHAS publicações
    my_comment_count = SocialPostComment.objects.filter(
        post__user=request.user,
        seen_by_owner=False,
    ).exclude(user=request.user).count()

    # Respostas não vistas aos meus comentários
    my_reply_count = SocialPostComment.objects.filter(
        reply_to__user=request.user,
        reply_seen=False,
    ).exclude(user=request.user).count()

    return JsonResponse({
        "counts": counts,
        "fresh": fresh,
        "fresh_texts": fresh_texts,
        "fresh_ts": fresh_ts,
        "my_comment_count": my_comment_count + my_reply_count,
    })


# ---------------------------------------------------------------
# Pills poll (GET → JSON) — atualiza pílulas sem F5
# ---------------------------------------------------------------
@login_required
def social_pills_poll(request):
    """
    Retorna pílulas de comentários/respostas não vistas para polling JS.
    Usado pelo front a cada 15 s para mostrar novos alertas sem recarregar.
    """
    from django.db.models import Count

    comment_pills = []
    unseen_qs = (
        SocialPostComment.objects
        .filter(post__user=request.user, seen_by_owner=False)
        .exclude(user=request.user)
        .values("post_id", "post__text")
        .annotate(count=Count("id"))
        .order_by("-post_id")
    )
    for row in unseen_qs:
        comment_pills.append({
            "post_id": row["post_id"],
            "text": (row["post__text"] or "")[:50],
            "count": row["count"],
        })

    reply_pills = []
    reply_qs = (
        SocialPostComment.objects
        .filter(reply_to__user=request.user, reply_seen=False)
        .exclude(user=request.user)
        .select_related("user")
        .order_by("-created_at")[:10]
    )
    for r in reply_qs:
        prof = _get_or_create_profile(r.user)
        reply_pills.append({
            "id": r.id,
            "post_owner_id": r.post_id,  # para navegar ao post
            "replier_name": prof.display_name or r.user.email,
        })

    # Convites de amizade pendentes
    friend_pills = []
    for fs in SocialFriendship.objects.filter(
        receiver=request.user, status="pending"
    ).select_related("requester", "requester__profile").order_by("-created_at"):
        prof = _get_or_create_profile(fs.requester)
        friend_pills.append({
            "user_id": fs.requester_id,
            "name": prof.display_name or fs.requester.email,
        })

    return JsonResponse({
        "comment_pills": comment_pills,
        "reply_pills": reply_pills,
        "friend_pills": friend_pills,
    })


# ---------------------------------------------------------------
# Definir unidade (onboarding)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_set_unidade(request):
    unidade = (request.POST.get("unidade") or "").strip()[:80]
    prof = _get_or_create_profile(request.user)
    fields_to_update = ["unidade"]
    prof.unidade = unidade
    # Se pulou (unidade vazia), marca onboarding como feito para não repetir
    if not unidade:
        prof.onboarding_done = True
        fields_to_update.append("onboarding_done")
    prof.save(update_fields=fields_to_update)
    ctx = _build_social_context(request, request.user)
    return render(request, "boards/social_panel.html", ctx)


@login_required
@require_POST
def social_dismiss_task(request, card_id: int):
    """Registra que o usuário dispensou um card das pendências hoje."""
    today = timezone.localdate()
    SocialCardDismiss.objects.get_or_create(
        user=request.user,
        card_id=card_id,
        dismissed_on=today,
    )
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------
# Amizades Sociais
# ---------------------------------------------------------------

def _board_member_ids(user):
    """IDs de todos os co-membros de quadros do usuário (excluindo ele mesmo)."""
    from django.db.models import Q
    my_board_ids = BoardMembership.objects.filter(user=user).values_list("board_id", flat=True)
    return set(
        BoardMembership.objects
        .filter(board_id__in=my_board_ids)
        .exclude(user=user)
        .values_list("user_id", flat=True)
        .distinct()
    )


def _friendship_status(me, other):
    """Retorna (status, is_requester) entre me e other. None se não existir."""
    fs = SocialFriendship.objects.filter(
        requester_id__in=[me.id, other.id],
        receiver_id__in=[me.id, other.id],
    ).first()
    if not fs:
        return None, False
    return fs.status, (fs.requester_id == me.id)


def _user_card(user):
    """Dict resumido de um usuário para JSON."""
    from django.templatetags.static import static
    try:
        prof = user.profile
    except Exception:
        prof = None
    avatar = None
    if prof and prof.avatar:
        avatar = prof.avatar.url
    elif prof and prof.avatar_choice:
        avatar = static(f"images/avatar/{prof.avatar_choice}")
    return {
        "id": user.id,
        "name": (prof.display_name if prof else None) or user.get_full_name() or user.email,
        "handle": (prof.handle if prof else "") or "",
        "avatar": avatar,
    }


def _accepted_friend_ids(user):
    """IDs dos amigos aceitos (SocialFriendship com status='accepted')."""
    from_req = set(
        SocialFriendship.objects.filter(
            requester=user, status=SocialFriendship.STATUS_ACCEPTED,
        ).values_list("receiver_id", flat=True)
    )
    from_rec = set(
        SocialFriendship.objects.filter(
            receiver=user, status=SocialFriendship.STATUS_ACCEPTED,
        ).values_list("requester_id", flat=True)
    )
    return from_req | from_rec


@login_required
def social_user_network(request, user_id: int):
    """
    Retorna a rede de um usuário: seus amigos aceitos,
    separados em 'em comum comigo' e 'outros'.
    """
    target = get_object_or_404(User, id=user_id)
    target_friend_ids = _accepted_friend_ids(target)
    my_friend_ids     = _accepted_friend_ids(request.user)

    common = []
    others = []
    users  = User.objects.filter(id__in=target_friend_ids).select_related("profile")

    for u in users:
        if u.id == request.user.id:
            continue
        card = _user_card(u)
        if u.id in my_friend_ids:
            common.append(card)
        else:
            others.append(card)

    status, is_req = _friendship_status(request.user, target)
    return JsonResponse({
        "profile": _user_card(target),
        "common": common,
        "others": others,
        "friendship_status": status,
        "i_am_requester": is_req,
    })


@login_required
@require_POST
def social_friend_request(request, user_id: int):
    """Envia ou cancela um convite de amizade."""
    target = get_object_or_404(User, id=user_id)
    if target == request.user:
        return JsonResponse({"error": "Não pode adicionar a si mesmo."}, status=400)

    fs = SocialFriendship.objects.filter(
        requester=request.user, receiver=target
    ).first()

    if fs:
        # Já enviou → cancela
        fs.delete()
        return JsonResponse({"action": "cancelled"})
    else:
        SocialFriendship.objects.create(requester=request.user, receiver=target)
        from boards.services.notifications import notify_friendship_event
        notify_friendship_event(recipient=target, actor=request.user, kind="invite")
        return JsonResponse({"action": "sent"})


@login_required
@require_POST
def social_friend_accept(request, user_id: int):
    """Aceita um convite recebido de user_id."""
    fs = get_object_or_404(SocialFriendship, requester_id=user_id, receiver=request.user)
    fs.status = SocialFriendship.STATUS_ACCEPTED
    fs.save(update_fields=["status"])
    from boards.services.notifications import notify_friendship_event
    notify_friendship_event(recipient=fs.requester, actor=request.user, kind="accepted")

    # ── Auto-post de amizade no feed ──
    my_prof = _get_or_create_profile(request.user)
    friend_prof = _get_or_create_profile(fs.requester)
    my_name = my_prof.display_name or request.user.get_full_name() or request.user.email
    friend_name = friend_prof.display_name or fs.requester.get_full_name() or fs.requester.email
    SocialPost.objects.create(
        user=request.user,
        text=f"__friendship__:{fs.requester_id}",
        visibility="all",
    )

    return JsonResponse({"action": "accepted"})


@login_required
@require_POST
def social_friend_reject(request, user_id: int):
    """Rejeita (deleta) um convite recebido de user_id."""
    # Busca antes de deletar para notificar
    fs = SocialFriendship.objects.filter(
        requester_id=user_id, receiver=request.user, status="pending"
    ).select_related("requester").first()
    if fs:
        requester = fs.requester
        fs.delete()
        from boards.services.notifications import notify_friendship_event
        notify_friendship_event(recipient=requester, actor=request.user, kind="rejected")
        return JsonResponse({"action": "rejected", "deleted": 1})
    return JsonResponse({"action": "rejected", "deleted": 0})


@login_required
@require_POST
def social_friend_remove(request, user_id: int):
    """Remove uma amizade aceita (de qualquer lado)."""
    from django.db.models import Q
    deleted, _ = SocialFriendship.objects.filter(
        Q(requester=request.user, receiver_id=user_id)
        | Q(requester_id=user_id, receiver=request.user)
    ).delete()
    return JsonResponse({"action": "removed", "deleted": deleted})


@login_required
@require_POST
def social_board_share(request):
    """Adiciona um usuário a um quadro do qual o solicitante é owner/editor."""
    board_id = (request.POST.get("board_id") or "").strip()
    target_id = (request.POST.get("user_id") or "").strip()
    if not board_id or not target_id:
        return JsonResponse({"error": "Parâmetros inválidos."}, status=400)

    board = get_object_or_404(Board, id=board_id)
    target = get_object_or_404(User, id=target_id)

    my_mem = BoardMembership.objects.filter(board=board, user=request.user).first()
    if not my_mem or my_mem.role == BoardMembership.Role.VIEWER:
        return JsonResponse({"error": "Sem permissão."}, status=403)

    _, created = BoardMembership.objects.get_or_create(
        board=board, user=target,
        defaults={"role": BoardMembership.Role.EDITOR},
    )
    return JsonResponse({"ok": True, "created": created, "board": board.name})


# ---------------------------------------------------------------
# Camila.AI — Página de treinamento (staff only)
# ---------------------------------------------------------------
@login_required
@staff_member_required
def camila_admin(request):
    """Página de treinamento da Camila.AI — CRUD da base de conhecimento."""
    entries = CamilaKnowledge.objects.all()
    categories = CamilaKnowledge.CATEGORY_CHOICES
    config = CamilaConfig.get()

    total_chars = sum(len(e.content) + len(e.title) for e in entries if e.is_active)

    ctx = {
        "entries": entries,
        "categories": categories,
        "config": config,
        "model_choices": CamilaConfig.MODEL_CHOICES,
        "total_entries": entries.count(),
        "active_entries": entries.filter(is_active=True).count(),
        "total_chars": total_chars,
    }
    return render(request, "boards/camila_admin.html", ctx)


@login_required
@staff_member_required
@require_POST
def camila_config_save(request):
    """Salva configurações da Camila (prompts, modelo, temperatura)."""
    cfg = CamilaConfig.get()
    cfg.prompt_react = (request.POST.get("prompt_react") or "").strip() or cfg.prompt_react
    cfg.prompt_chat = (request.POST.get("prompt_chat") or "").strip() or cfg.prompt_chat
    cfg.prompt_coach = (request.POST.get("prompt_coach") or "").strip() or cfg.prompt_coach
    cfg.model = (request.POST.get("model") or "").strip() or cfg.model
    try:
        cfg.temperature = float(request.POST.get("temperature", cfg.temperature))
    except (ValueError, TypeError):
        pass
    try:
        cfg.max_tokens = int(request.POST.get("max_tokens", cfg.max_tokens))
    except (ValueError, TypeError):
        pass
    cfg.save()
    return JsonResponse({"ok": True, "model": cfg.model, "temperature": cfg.temperature})


@login_required
@staff_member_required
@require_POST
def camila_knowledge_save(request):
    """Cria ou atualiza uma entrada de conhecimento."""
    entry_id = request.POST.get("entry_id")
    title = (request.POST.get("title") or "").strip()
    category = (request.POST.get("category") or "about").strip()
    content = (request.POST.get("content") or "").strip()
    is_active = request.POST.get("is_active") == "1"

    if not title or not content:
        return JsonResponse({"error": "Título e conteúdo são obrigatórios."}, status=400)

    if entry_id:
        entry = get_object_or_404(CamilaKnowledge, id=entry_id)
        entry.title = title
        entry.category = category
        entry.content = content
        entry.is_active = is_active
        entry.save()
    else:
        entry = CamilaKnowledge.objects.create(
            title=title,
            category=category,
            content=content,
            is_active=is_active,
            created_by=request.user,
        )

    return JsonResponse({
        "id": entry.id,
        "title": entry.title,
        "category": entry.category,
        "category_label": entry.get_category_display(),
        "content": entry.content,
        "is_active": entry.is_active,
    })


@login_required
@staff_member_required
@require_POST
def camila_knowledge_delete(request, entry_id: int):
    """Remove uma entrada de conhecimento."""
    entry = get_object_or_404(CamilaKnowledge, id=entry_id)
    entry.delete()
    return JsonResponse({"ok": True})


@login_required
@staff_member_required
@require_POST
def camila_knowledge_toggle(request, entry_id: int):
    """Ativa/desativa uma entrada."""
    entry = get_object_or_404(CamilaKnowledge, id=entry_id)
    entry.is_active = not entry.is_active
    entry.save(update_fields=["is_active"])
    return JsonResponse({"id": entry.id, "is_active": entry.is_active})


@login_required
@staff_member_required
@require_POST
def camila_test_chat(request):
    """Testa a Camila com a base de conhecimento atual — com histórico de conversa."""
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    message = (data.get("message") or "").strip()
    history = data.get("history") or []
    if not message:
        return JsonResponse({"error": "Mensagem vazia."}, status=400)

    cfg = CamilaConfig.get()
    prompt = cfg.prompt_chat + _camila_knowledge_prompt(message)
    messages = [*history[-10:], {"role": "user", "content": message}]
    response = _groq_chat(messages, prompt, config=cfg)
    return JsonResponse({"response": response or "Sem resposta da IA."})


# Mapeamento de categorias externas → categorias internas do CamilaKnowledge
_CATEGORY_MAP = {
    "about": "about",
    "sobre": "about",
    "services": "services",
    "servicos": "services",
    "serviços": "services",
    "products": "services",
    "produtos": "services",
    "planos": "services",
    "financeiro": "services",
    "financeiro_planos": "services",
    "rules": "rules",
    "regras": "rules",
    "politicas": "rules",
    "políticas": "rules",
    "processes": "processes",
    "processos": "processes",
    "faq": "faq",
    "perguntas": "faq",
    "contacts": "contacts",
    "contatos": "contacts",
    "enderecos": "contacts",
    "endereços": "contacts",
    "culture": "culture",
    "cultura": "culture",
    "valores": "culture",
    "other": "other",
    "outros": "other",
    "geral": "other",
}

_VALID_CATEGORIES = {c[0] for c in CamilaKnowledge.CATEGORY_CHOICES}


def _map_category(raw: str) -> str:
    if not raw:
        return "other"
    raw_lower = raw.strip().lower()
    if raw_lower in _VALID_CATEGORIES:
        return raw_lower
    return _CATEGORY_MAP.get(raw_lower, "other")


@login_required
@staff_member_required
@require_POST
def camila_import_json(request):
    """Importa base de conhecimento a partir de JSON (fixture Django ou array simples)."""
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    items = data.get("items")
    mode = (data.get("mode") or "skip").strip()

    if not isinstance(items, list):
        return JsonResponse({"error": "Campo 'items' deve ser uma lista."}, status=400)

    imported = 0
    skipped = 0
    overwritten = 0
    errors = []

    for idx, item in enumerate(items):
        try:
            # Suporta tanto fixture Django quanto objeto simples
            if "fields" in item:
                fields = item["fields"]
            else:
                fields = item

            title = (fields.get("topic") or fields.get("title") or "").strip()
            content = (fields.get("content") or "").strip()
            raw_category = fields.get("category") or ""
            query_patterns = fields.get("query_patterns") or []
            is_active = fields.get("is_active", True)

            if not title or not content:
                errors.append(f"Item {idx + 1}: título ou conteúdo vazio, ignorado.")
                continue

            # Anexa query_patterns ao conteúdo para enriquecer o contexto
            if query_patterns:
                if isinstance(query_patterns, list):
                    patterns_str = ", ".join(str(p) for p in query_patterns if p)
                else:
                    patterns_str = str(query_patterns).strip()
                if patterns_str:
                    content = content + "\n\nPerguntas relacionadas: " + patterns_str

            category = _map_category(raw_category)

            existing = CamilaKnowledge.objects.filter(title=title).first()

            if existing:
                if mode == "skip":
                    skipped += 1
                    continue
                elif mode == "overwrite":
                    existing.content = content
                    existing.category = category
                    existing.is_active = bool(is_active)
                    existing.save(update_fields=["content", "category", "is_active", "updated_at"])
                    overwritten += 1
                else:  # add — duplica mesmo assim
                    CamilaKnowledge.objects.create(
                        title=title,
                        content=content,
                        category=category,
                        is_active=bool(is_active),
                        created_by=request.user,
                    )
                    imported += 1
            else:
                CamilaKnowledge.objects.create(
                    title=title,
                    content=content,
                    category=category,
                    is_active=bool(is_active),
                    created_by=request.user,
                )
                imported += 1

        except Exception as exc:
            errors.append(f"Item {idx + 1}: {exc}")

    return JsonResponse({
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "overwritten": overwritten,
        "errors": errors,
    })


@login_required
@staff_member_required
def camila_pop_list(request):
    """Retorna lista de POPs em JSON, agrupada por categoria."""
    pops = CamilaPOP.objects.all().order_by("category", "code", "title")
    data = []
    for p in pops:
        data.append({
            "id": p.id,
            "title": p.title,
            "code": p.code,
            "category": p.category,
            "is_active": p.is_active,
            "pdf_url": p.pdf_file.url if p.pdf_file else "",
            "chars": len(p.extracted_text),
            "created_at": p.created_at.strftime("%d/%m/%Y"),
        })
    return JsonResponse({"pops": data})


_CLAUDE_SUMMARIZE_PROMPT = """Você recebeu o texto bruto de um POP (Procedimento Operacional Padrão) interno da CAMIM.

Gere um resumo estruturado e objetivo, otimizado para ser usado como contexto em uma IA de atendimento interno. O resumo deve:
- Ser conciso (máximo 600 palavras)
- Manter TODAS as regras críticas, condições de decisão e exceções
- Preservar valores, prazos, telefones, e-mails e dados específicos
- Usar linguagem direta, sem floreios ou introduções desnecessárias
- Estruturar nas seções: **Objetivo**, **Quando aplicar**, **Passos**, **Regras críticas**, **Contatos/Escalação**
- Manter qualquer código, número de matrícula ou referência sistêmica mencionada

Responda APENAS com o resumo estruturado, sem comentários adicionais."""


def _extract_text_pdfplumber(pdf_bytes: bytes) -> str:
    """Extrai texto bruto do PDF usando pdfplumber (melhor qualidade que pypdf)."""
    import io
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages.append(text)
            return "\n".join(pages).strip()
    except ImportError:
        # fallback para pypdf se pdfplumber não estiver disponível
        try:
            from pypdf import PdfReader
            import io as _io
            reader = PdfReader(_io.BytesIO(pdf_bytes))
            return "\n".join(p.extract_text() or "" for p in reader.pages).strip()
        except Exception as exc:
            return f"[Erro na extração: {exc}]"
    except Exception as exc:
        return f"[Erro na extração: {exc}]"


def _summarize_with_claude(raw_text: str, title: str) -> str:
    """Sumariza o texto do POP.
    Prioridade: Claude (ANTHROPIC_API_KEY) → Groq (GROQ_API_KEY) → truncamento.
    """
    user_content = (
        f"{_CLAUDE_SUMMARIZE_PROMPT}\n\n"
        f"Título do POP: {title}\n\n"
        f"Texto extraído do PDF:\n\n{raw_text[:12000]}"
    )

    # 1. Claude (melhor qualidade, mais barato por token)
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{"role": "user", "content": user_content}],
            )
            return message.content[0].text.strip()
        except Exception:
            pass  # cai para Groq

    # 2. Groq (fallback)
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        summary = _groq_chat(
            [{"role": "user", "content": user_content}],
            system_prompt="Você é um especialista em documentação operacional. Responda apenas com o resumo estruturado, sem comentários adicionais.",
        )
        if summary and not summary.startswith("Erro"):
            return summary

    # 3. OpenAI (fallback)
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=1024,
                messages=[
                    {
                        "role": "system",
                        "content": "Você é um especialista em documentação operacional. Responda apenas com o resumo estruturado, sem comentários adicionais.",
                    },
                    {"role": "user", "content": user_content},
                ],
            )
            text = resp.choices[0].message.content.strip()
            if text:
                return text
        except Exception:
            pass

    # 4. Último recurso: texto bruto truncado
    return raw_text[:4000]


@login_required
@staff_member_required
@require_POST
def camila_pop_upload(request):
    """Upload de ZIP (com vários PDFs) ou PDF individual.
    Extrai texto com pdfplumber e sumariza com Claude antes de salvar."""
    import zipfile
    import io
    import re

    uploaded = request.FILES.get("file")
    if not uploaded:
        return JsonResponse({"error": "Nenhum arquivo enviado."}, status=400)

    results = {"imported": 0, "errors": [], "summarized": 0}

    def _parse_name(filename: str):
        """Extrai título e código do nome do arquivo.
        Aceita: POP-001, TI-17001, ENF-001, CA-001, etc."""
        name = filename
        for ext in (".pdf", ".PDF"):
            name = name.removesuffix(ext)
        # Código: 2-5 letras + hífen + 3-6 dígitos no início do nome
        code_match = re.match(r"^([A-ZÀ-Ú]{1,5}[\s\-_]\d{3,6})", name, re.IGNORECASE)
        code = re.sub(r"[\s_]", "-", code_match.group(1)).upper() if code_match else ""
        return name.strip(), code

    def _extract_category(member_path: str) -> str:
        """Extrai a categoria (pasta) do caminho do arquivo dentro do ZIP.
        Ex: 'ENFERMAGEM/ENF-001.pdf' → 'ENFERMAGEM'
            'T.I/subpasta/TI-001.pdf' → 'T.I'
        """
        parts = member_path.replace("\\", "/").split("/")
        # Ignora o arquivo em si (último elemento) e pega a primeira pasta
        if len(parts) >= 2:
            return parts[0].strip()
        return ""

    def _save_pop(member_path: str, pdf_bytes: bytes, category: str = ""):
        from django.core.files.base import ContentFile
        filename = member_path.replace("\\", "/").split("/")[-1]
        title, code = _parse_name(filename)
        # Texto completo — base de conhecimento real
        raw = _extract_text_pdfplumber(pdf_bytes)
        # Resumo estruturado — índice compacto para quando há muitos POPs
        summary = _summarize_with_claude(raw, title)
        if summary != raw[:4000]:
            results["summarized"] += 1
        pop = CamilaPOP(
            title=title,
            code=code,
            category=category,
            raw_text=raw,            # texto integral
            extracted_text=summary,  # resumo IA
            is_active=True,
            uploaded_by=request.user,
        )
        safe_cat = re.sub(r"[^\w\s\-\.]", "", category).strip() or "geral"
        pop.pdf_file.save(f"{safe_cat}/{filename}", ContentFile(pdf_bytes), save=False)
        pop.save()
        results["imported"] += 1

    fname = uploaded.name.lower()

    if fname.endswith(".zip"):
        raw = uploaded.read()
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for member in zf.infolist():
                    mname = member.filename
                    if mname.lower().endswith(".pdf") and "__MACOSX" not in mname:
                        pdf_bytes = zf.read(mname)
                        category = _extract_category(mname)
                        try:
                            _save_pop(mname, pdf_bytes, category)
                        except Exception as exc:
                            results["errors"].append(f"{mname}: {exc}")
        except zipfile.BadZipFile:
            return JsonResponse({"error": "Arquivo ZIP inválido."}, status=400)

    elif fname.endswith(".pdf"):
        try:
            _save_pop(uploaded.name, uploaded.read(), category="")
        except Exception as exc:
            results["errors"].append(f"{uploaded.name}: {exc}")
    else:
        return JsonResponse({"error": "Envie um arquivo .pdf ou .zip com PDFs."}, status=400)

    results["ok"] = True
    return JsonResponse(results)


@login_required
@staff_member_required
@require_POST
def camila_pop_resummarize(request, pop_id: int):
    """Re-extrai texto completo E re-sumariza um POP existente."""
    pop = get_object_or_404(CamilaPOP, id=pop_id)
    try:
        pdf_bytes = pop.pdf_file.read()
        raw = _extract_text_pdfplumber(pdf_bytes)
        summary = _summarize_with_claude(raw, pop.title)
        pop.raw_text = raw
        pop.extracted_text = summary
        pop.save(update_fields=["raw_text", "extracted_text", "updated_at"])
        return JsonResponse({"ok": True, "chars": len(raw), "summary_chars": len(summary)})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)


@login_required
@staff_member_required
@require_POST
def camila_pop_delete(request, pop_id: int):
    """Remove um POP."""
    pop = get_object_or_404(CamilaPOP, id=pop_id)
    pop.pdf_file.delete(save=False)
    pop.delete()
    return JsonResponse({"ok": True})


@login_required
@staff_member_required
@require_POST
def camila_pop_toggle(request, pop_id: int):
    """Ativa/desativa um POP."""
    pop = get_object_or_404(CamilaPOP, id=pop_id)
    pop.is_active = not pop.is_active
    pop.save(update_fields=["is_active"])
    return JsonResponse({"ok": True, "is_active": pop.is_active})


# ===============================================================
# CHAT DIRETO ENTRE AMIGOS
# ===============================================================

@login_required
@require_POST
def social_onboarding_done(request):
    """Marca o onboarding tour como concluído."""
    prof = _get_or_create_profile(request.user)
    prof.onboarding_done = True
    prof.save(update_fields=["onboarding_done"])
    return JsonResponse({"ok": True})


def _are_friends(user_a, user_b):
    """Verifica se dois usuários são amigos aceitos."""
    return SocialFriendship.objects.filter(
        models.Q(requester=user_a, receiver=user_b, status="accepted")
        | models.Q(requester=user_b, receiver=user_a, status="accepted")
    ).exists()


def _get_or_create_conversation(user_a, user_b):
    """Retorna a conversa entre dois usuários, criando se necessário.
    user_a sempre tem o menor ID para manter a unicidade."""
    if user_a.id > user_b.id:
        user_a, user_b = user_b, user_a
    conv, _ = ChatConversation.objects.get_or_create(
        user_a=user_a, user_b=user_b,
    )
    return conv


@login_required
def chat_list(request):
    """Lista de conversas do usuário (JSON)."""
    me = request.user
    convs = ChatConversation.objects.filter(
        models.Q(user_a=me) | models.Q(user_b=me)
    ).select_related(
        "user_a", "user_a__profile", "user_b", "user_b__profile"
    ).order_by("-updated_at")

    result = []
    for c in convs:
        is_a = c.user_a_id == me.id
        # Filtrar conversas deletadas para este usuario
        if (is_a and c.deleted_by_a) or (not is_a and c.deleted_by_b):
            continue
        archived = (is_a and c.archived_by_a) or (not is_a and c.archived_by_b)
        other = c.other_user(me)
        prof = getattr(other, "profile", None)
        # Última mensagem visível
        hide_field = "hidden_by_a" if is_a else "hidden_by_b"
        last_msg = (
            c.messages
            .filter(is_active=True, **{hide_field: False})
            .order_by("-created_at")
            .first()
        )
        unread = c.messages.filter(
            is_active=True, seen=False, **{hide_field: False}
        ).exclude(sender=me).count()

        result.append({
            "conversation_id": c.id,
            "other_user_id": other.id,
            "other_name": prof.display_name if prof else other.email,
            "other_avatar": prof.avatar.url if prof and prof.avatar else "",
            "other_handle": prof.handle if prof else "",
            "last_message": last_msg.text[:60] if last_msg else "",
            "last_message_gif": bool(last_msg and last_msg.gif_url) if last_msg else False,
            "last_message_sticker": bool(last_msg and last_msg.sticker_url) if last_msg else False,
            "last_time": timezone.localtime(last_msg.created_at).strftime("%d/%m %H:%M") if last_msg else "",
            "unread": unread,
            "archived": archived,
        })
    return JsonResponse({"conversations": result})


@login_required
def chat_messages(request, user_id: int):
    """Retorna mensagens de uma conversa com outro usuário (JSON)."""
    me = request.user
    other = get_object_or_404(User, id=user_id)

    conv = _get_or_create_conversation(me, other)
    is_a = conv.user_a_id == me.id
    hide_field = "hidden_by_a" if is_a else "hidden_by_b"

    msgs = list(
        conv.messages
        .filter(is_active=True, **{hide_field: False})
        .select_related("sender", "sender__profile")
        .order_by("-created_at")[:80]
    )
    msgs.reverse()

    # Marcar como lido
    conv.messages.filter(
        is_active=True, seen=False
    ).exclude(sender=me).update(seen=True)

    result = []
    for m in msgs:
        prof = getattr(m.sender, "profile", None)
        result.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "sender_name": prof.display_name if prof else m.sender.email,
            "sender_avatar": prof.avatar.url if prof and prof.avatar else "",
            "text": m.text,
            "gif_url": m.gif_url,
            "sticker_url": m.sticker_url,
            "created_at": timezone.localtime(m.created_at).strftime("%d/%m %H:%M"),
            "is_mine": m.sender_id == me.id,
            "seen": m.seen,
        })

    other_prof = getattr(other, "profile", None)
    return JsonResponse({
        "messages": result,
        "conversation_id": conv.id,
        "other_name": other_prof.display_name if other_prof else other.email,
        "other_avatar": other_prof.avatar.url if other_prof and other_prof.avatar else "",
    })


@login_required
@require_POST
def chat_send(request, user_id: int):
    """Envia uma mensagem para outro usuário."""
    me = request.user
    other = get_object_or_404(User, id=user_id)

    text = (request.POST.get("text") or "").strip()
    gif_url = (request.POST.get("gif_url") or "").strip()
    sticker_url = (request.POST.get("sticker_url") or "").strip()

    if not text and not gif_url and not sticker_url:
        return JsonResponse({"error": "Mensagem vazia."}, status=400)

    conv = _get_or_create_conversation(me, other)

    # Verifica se é a primeira mensagem não lida (para notificar)
    has_recent_unread = ChatMessage.objects.filter(
        conversation=conv, sender=me, seen=False,
    ).exists()

    msg = ChatMessage.objects.create(
        conversation=conv,
        sender=me,
        text=text,
        gif_url=gif_url,
        sticker_url=sticker_url,
    )
    conv.save()  # atualiza updated_at
    # Notificação é feita pelo cron chat_notify_unseen (a cada minuto)

    prof = getattr(me, "profile", None)
    return JsonResponse({
        "id": msg.id,
        "sender_id": me.id,
        "sender_name": prof.display_name if prof else me.email,
        "text": msg.text,
        "gif_url": msg.gif_url,
        "sticker_url": msg.sticker_url,
        "created_at": timezone.localtime(msg.created_at).strftime("%d/%m %H:%M"),
        "is_mine": True,
        "seen": False,
    })


@login_required
@require_POST
def chat_delete_message(request, message_id: int):
    """
    Apaga mensagem.
    mode=me  → esconde só para o usuário (soft delete individual)
    mode=all → desativa a mensagem para todos (is_active=False), só o remetente pode
    Nada é realmente apagado — apenas desativado/escondido.
    """
    me = request.user
    msg = get_object_or_404(ChatMessage, id=message_id)
    conv = msg.conversation
    mode = request.POST.get("mode", "me")

    if mode == "all" and msg.sender_id == me.id:
        # Desativa para todos (mas não apaga do banco)
        msg.is_active = False
        msg.save(update_fields=["is_active"])
        return JsonResponse({"ok": True})

    # Esconde só para mim
    if conv.user_a_id == me.id:
        msg.hidden_by_a = True
    elif conv.user_b_id == me.id:
        msg.hidden_by_b = True
    else:
        return JsonResponse({"error": "Sem permissão."}, status=403)

    msg.save(update_fields=["hidden_by_a", "hidden_by_b"])
    return JsonResponse({"ok": True})


@login_required
@require_POST
def chat_forward_message(request, message_id: int):
    """Encaminha uma mensagem para outro usuário."""
    me = request.user
    original = get_object_or_404(ChatMessage, id=message_id)
    to_user_id = request.POST.get("to_user_id")
    if not to_user_id:
        return JsonResponse({"error": "Destinatário não informado."}, status=400)
    other = get_object_or_404(User, id=int(to_user_id))

    conv = _get_or_create_conversation(me, other)
    # Cria cópia da mensagem na conversa de destino
    fwd_text = original.text
    if fwd_text:
        fwd_text = "↪ " + fwd_text
    ChatMessage.objects.create(
        conversation=conv,
        sender=me,
        text=fwd_text,
        gif_url=original.gif_url,
        sticker_url=original.sticker_url,
    )
    conv.save()
    return JsonResponse({"ok": True})


@login_required
def chat_poll(request, user_id: int):
    """Poll para novas mensagens (GET → JSON)."""
    me = request.user
    other = get_object_or_404(User, id=user_id)
    after_id = int(request.GET.get("after", 0))

    conv = _get_or_create_conversation(me, other)
    is_a = conv.user_a_id == me.id
    hide_field = "hidden_by_a" if is_a else "hidden_by_b"

    new_msgs = list(
        conv.messages
        .filter(is_active=True, id__gt=after_id, **{hide_field: False})
        .select_related("sender", "sender__profile")
        .order_by("created_at")[:50]
    )

    # Marcar como lido
    conv.messages.filter(
        is_active=True, seen=False, id__gt=after_id
    ).exclude(sender=me).update(seen=True)

    # Último ID de mensagem minha que o outro já leu (para atualizar ✓ → ✓✓)
    last_seen = (
        conv.messages.filter(
            sender=me, seen=True, is_active=True,
        ).order_by("-id").values_list("id", flat=True).first()
    ) or 0

    result = []
    for m in new_msgs:
        prof = getattr(m.sender, "profile", None)
        result.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "sender_name": prof.display_name if prof else m.sender.email,
            "sender_avatar": prof.avatar.url if prof and prof.avatar else "",
            "text": m.text,
            "gif_url": m.gif_url,
            "sticker_url": m.sticker_url,
            "created_at": timezone.localtime(m.created_at).strftime("%d/%m %H:%M"),
            "is_mine": m.sender_id == me.id,
            "seen": m.seen,
        })
    return JsonResponse({"messages": result, "last_seen_id": last_seen})


@login_required
def chat_unread_total(request):
    """Total de mensagens não lidas em todas as conversas (para badge)."""
    me = request.user
    total = ChatMessage.objects.filter(
        is_active=True, seen=False,
    ).filter(
        models.Q(conversation__user_a=me, hidden_by_a=False, conversation__deleted_by_a=False)
        | models.Q(conversation__user_b=me, hidden_by_b=False, conversation__deleted_by_b=False)
    ).exclude(sender=me).count()
    return JsonResponse({"unread": total})


# ---------------------------------------------------------------
# Stickers — criar e listar figurinhas do usuário
# ---------------------------------------------------------------
@login_required
@require_POST
def chat_sticker_create(request):
    """Upload de imagem/gif/webp/mp4 para criar figurinha pessoal."""
    image = request.FILES.get("image")
    if not image:
        return JsonResponse({"error": "Nenhum arquivo enviado."}, status=400)
    if image.size > 5 * 1024 * 1024:
        return JsonResponse({"error": "Arquivo muito grande (máx 5 MB)."}, status=400)
    allowed = {"image/png", "image/jpeg", "image/gif", "image/webp", "video/mp4"}
    ct = (image.content_type or "").lower()
    if ct not in allowed:
        return JsonResponse({"error": "Formato não suportado. Use PNG, JPG, GIF, WebP ou MP4."}, status=400)
    sticker = ChatSticker.objects.create(owner=request.user, image=image)
    return JsonResponse({
        "id": sticker.id,
        "url": sticker.image.url,
    })


@login_required
def chat_sticker_list(request):
    """Lista as figurinhas do usuário."""
    stickers = ChatSticker.objects.filter(owner=request.user, is_active=True)[:50]
    return JsonResponse({
        "stickers": [{"id": s.id, "url": s.image.url} for s in stickers],
    })


@login_required
@require_POST
def chat_sticker_delete(request, sticker_id: int):
    """Soft-delete de figurinha."""
    sticker = get_object_or_404(ChatSticker, id=sticker_id, owner=request.user)
    sticker.is_active = False
    sticker.save(update_fields=["is_active"])
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------
# Compartilhar post — repost na própria página
# ---------------------------------------------------------------
@login_required
@require_POST
def social_post_repost(request, post_id: int):
    """Cria um repost na página do usuário."""
    original = get_object_or_404(SocialPost, id=post_id, is_active=True)
    # Não reposta o próprio post
    if original.user_id == request.user.id:
        return JsonResponse({"error": "Não é possível compartilhar o próprio post."}, status=400)
    # Se o original é um repost, aponta para o original raiz
    root = original.shared_from if original.shared_from_id else original
    # Verifica se já repostou
    already = SocialPost.objects.filter(
        user=request.user, shared_from=root, is_active=True,
    ).exists()
    if already:
        return JsonResponse({"error": "Você já compartilhou este post."}, status=400)
    repost = SocialPost.objects.create(
        user=request.user,
        shared_from=root,
        text="",
        visibility=SocialPost.VISIBILITY_ALL,
    )
    return JsonResponse({"ok": True, "repost_id": repost.id})


# ---------------------------------------------------------------
# Quem curtiu um post (GET → JSON)
# ---------------------------------------------------------------
@login_required
def social_post_reactors(request, post_id: int):
    """Retorna lista de quem reagiu a um post com seus avatares."""
    reactions = (
        SocialPostReaction.objects
        .filter(post_id=post_id)
        .select_related("user", "user__profile")
        .order_by("-created_at")
    )
    result = []
    for r in reactions:
        prof = getattr(r.user, "profile", None)
        result.append({
            "user_id": r.user_id,
            "name": prof.display_name if prof else r.user.email,
            "avatar": prof.avatar.url if prof and prof.avatar else "",
            "avatar_choice": prof.avatar_choice if prof else "",
            "reaction": r.reaction,
            "emoji": r.emoji,
        })
    return JsonResponse({"reactors": result})


# ---------------------------------------------------------------
# Quem viu o post (GET → JSON)
# ---------------------------------------------------------------
@login_required
def social_post_viewers(request, post_id: int):
    """Retorna lista de quem visualizou um post com seus avatares."""
    views = (
        SocialPostView.objects
        .filter(post_id=post_id)
        .select_related("viewer", "viewer__profile")
        .order_by("-viewed_at")
    )
    result = []
    for v in views:
        prof = getattr(v.viewer, "profile", None)
        result.append({
            "user_id": v.viewer_id,
            "name": prof.display_name if prof else v.viewer.email,
            "avatar": prof.avatar.url if prof and prof.avatar else "",
            "avatar_choice": prof.avatar_choice if prof else "",
        })
    return JsonResponse({"viewers": result})


# ---------------------------------------------------------------
# Lista de amigos para iniciar chat (GET → JSON)
# ---------------------------------------------------------------
@login_required
def chat_friends_list(request):
    """Retorna amigos aceitos para selecionar destinatário de chat."""
    me = request.user
    accepted_out = set(SocialFriendship.objects.filter(
        requester=me, status="accepted"
    ).values_list("receiver_id", flat=True))
    accepted_in = set(SocialFriendship.objects.filter(
        receiver=me, status="accepted"
    ).values_list("requester_id", flat=True))
    friend_ids = accepted_out | accepted_in

    friends = []
    if friend_ids:
        for u in User.objects.filter(id__in=friend_ids).select_related("profile"):
            prof = getattr(u, "profile", None)
            friends.append({
                "user_id": u.id,
                "name": prof.display_name if prof else u.email,
                "avatar": prof.avatar.url if prof and prof.avatar else "",
                "handle": prof.handle if prof else "",
            })
    return JsonResponse({"friends": friends})


# ---------------------------------------------------------------
# Ação em conversa: arquivar / apagar (soft)
# ---------------------------------------------------------------
@login_required
@require_POST
def chat_conversation_action(request, conv_id: int):
    """
    action=archive → arquiva conversa para o usuário
    action=delete  → marca como deletada para o usuário
    action=unarchive → desarquiva
    Nada é apagado de verdade.
    """
    conv = get_object_or_404(ChatConversation, id=conv_id)
    me = request.user
    action = request.POST.get("action", "")

    is_a = conv.user_a_id == me.id
    is_b = conv.user_b_id == me.id
    if not is_a and not is_b:
        return JsonResponse({"error": "Sem permissão."}, status=403)

    if action == "archive":
        if is_a:
            conv.archived_by_a = True
        else:
            conv.archived_by_b = True
        conv.save(update_fields=["archived_by_a", "archived_by_b"])
    elif action == "unarchive":
        if is_a:
            conv.archived_by_a = False
        else:
            conv.archived_by_b = False
        conv.save(update_fields=["archived_by_a", "archived_by_b"])
    elif action == "delete":
        if is_a:
            conv.deleted_by_a = True
        else:
            conv.deleted_by_b = True
        conv.save(update_fields=["deleted_by_a", "deleted_by_b"])
    else:
        return JsonResponse({"error": "Ação inválida."}, status=400)

    return JsonResponse({"ok": True})


# ---------------------------------------------------------------
# Buscar usuários para @menção social (GET ?q=...)
# ---------------------------------------------------------------
@login_required
def social_mention_search(request):
    """Busca usuários por handle ou display_name para @menção em posts/comentários."""
    q = (request.GET.get("q") or "").strip()
    if len(q) < 1:
        return JsonResponse([], safe=False)

    q_lower = q.lower()
    users = (
        User.objects
        .exclude(id=request.user.id)
        .select_related("profile")
        .filter(
            models.Q(profile__handle__icontains=q_lower)
            | models.Q(profile__display_name__icontains=q_lower)
        )
        .order_by("profile__handle")[:15]
    )

    results = []
    for u in users:
        p = getattr(u, "profile", None)
        handle = (getattr(p, "handle", "") or "").strip()
        if not handle:
            continue
        display_name = (getattr(p, "display_name", "") or "").strip()
        results.append({
            "id": u.id,
            "handle": handle,
            "display_name": display_name,
            "avatar_url": p.avatar.url if (p and getattr(p, "avatar", None)) else "",
        })

    return JsonResponse(results, safe=False)
