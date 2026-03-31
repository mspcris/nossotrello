# boards/views/social.py
"""
Espaço social: rede social de trabalho — check-in diário, humor,
almoço, pendências do dia, feed de fotos do trabalho.
"""
import json
import os
import xml.etree.ElementTree as ET

import requests as http_requests
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model
from django.utils import timezone

from collections import Counter, defaultdict

from ..models import (
    Board, BoardMembership, SocialPost, SocialPostSeen,
    SocialPostReaction, SocialPostComment,
    DailyCheckIn, Card, CardFollow, UserProfile,
    CamilaKnowledge, CamilaConfig, SocialFriendship, SocialCardDismiss, CamilaPOP,
)

User = get_user_model()

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
    posts = list(SocialPost.objects.filter(user=target_user).order_by("-created_at")[:30])

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

        # Annotate each post
        for post in posts:
            post_reactions = reactions_by_post.get(post.id, [])
            post.reaction_counts = dict(Counter(r.reaction for r in post_reactions))
            post.total_reactions = len(post_reactions)
            post.my_reaction = next(
                (r.reaction for r in post_reactions if r.user_id == request.user.id), None
            )
            post.comment_list = comments_by_post.get(post.id, [])
            post.comment_count = len(post.comment_list)

    # Marca visto
    if not is_me and posts:
        SocialPostSeen.objects.update_or_create(
            viewer=request.user,
            target_user=target_user,
            defaults={"last_seen_post_at": timezone.now()},
        )

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
    unit_suggestions = []
    available_units = []
    if is_me:
        show_unit_tutorial = not prof.unidade
        available_units = list(
            UserProfile.objects
            .exclude(unidade="")
            .values_list("unidade", flat=True)
            .distinct()
            .order_by("unidade")
        )
        if prof.unidade:
            # IDs já na minha rede (board + amigos aceitos)
            my_net_ids = set(_board_member_ids(target_user))
            accepted = SocialFriendship.objects.filter(
                requester=target_user, status="accepted"
            ).values_list("receiver_id", flat=True)
            accepted2 = SocialFriendship.objects.filter(
                receiver=target_user, status="accepted"
            ).values_list("requester_id", flat=True)
            my_net_ids.update(accepted)
            my_net_ids.update(accepted2)
            my_net_ids.add(target_user.id)

            unit_suggestions = list(
                User.objects.filter(profile__unidade=prof.unidade)
                .exclude(id__in=my_net_ids)
                .select_related("profile")
                .order_by("profile__display_name")[:20]
            )

    # Amigos (co-membros de quadros) — só para o dono
    board_friends = []
    my_boards = []
    if is_me:
        friend_ids = _board_member_ids(target_user)
        board_friends = list(
            User.objects.filter(id__in=friend_ids)
            .select_related("profile")
            .order_by("profile__display_name")
        )
        # Quadros que o usuário pode compartilhar (owner ou editor)
        my_boards = list(
            Board.objects.filter(
                memberships__user=target_user,
                memberships__role__in=["owner", "editor"],
            ).values("id", "name").distinct()
        )

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
        "my_boards": my_boards,
        "show_unit_tutorial": show_unit_tutorial,
        "unit_suggestions": unit_suggestions,
        "available_units": available_units,
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

    extra = {}
    if not text and not photo and not video:
        extra["post_error"] = "Adicione um texto, foto ou vídeo antes de publicar."
    else:
        SocialPost.objects.create(
            user=request.user,
            text=text,
            photo=photo or None,
            video=video or None,
        )
        # AI react trigger
        parts = []
        if text:
            parts.append(f"Publicou: {text}")
        if photo:
            parts.append("Enviou uma foto")
        if video:
            parts.append("Enviou um vídeo")
        extra["ai_react_text"] = "; ".join(parts)

    ctx = _build_social_context(request, request.user, extra)
    return render(request, "boards/social_panel.html", ctx)


# ---------------------------------------------------------------
# Deletar post (POST)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_post_delete(request, post_id: int):
    post = get_object_or_404(SocialPost, id=post_id, user=request.user)
    post.delete()
    ctx = _build_social_context(request, request.user)
    return render(request, "boards/social_panel.html", ctx)


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
def _camila_knowledge_prompt():
    """Monta bloco de conhecimento a partir do banco."""
    entries = CamilaKnowledge.objects.filter(is_active=True)
    if not entries.exists():
        return ""
    lines = ["\n\n--- BASE DE CONHECIMENTO DA CAMIM ---"]
    for e in entries:
        lines.append(f"\n[{e.get_category_display()}] {e.title}:\n{e.content}")
    lines.append("\n--- FIM DA BASE DE CONHECIMENTO ---\n")

    # POPs — Procedimentos Operacionais Padrão (agrupados por categoria)
    pops = CamilaPOP.objects.filter(is_active=True).exclude(extracted_text="").order_by("category", "code")
    if pops.exists():
        lines.append("\n\n--- POPs — PROCEDIMENTOS OPERACIONAIS PADRÃO ---")
        lines.append("Ao citar um POP: informe código, título, setor e ofereça o link de download do PDF.")
        current_cat = None
        for pop in pops:
            if pop.category != current_cat:
                current_cat = pop.category
                lines.append(f"\n## Setor: {current_cat or 'Geral'}")
            prefix = f"[{pop.code}] " if pop.code else ""
            lines.append(f"\n### {prefix}{pop.title}")
            if pop.pdf_file:
                lines.append(f"PDF para download: /media/{pop.pdf_file.name}")
            lines.append(pop.extracted_text[:3000])

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
    prompt = cfg.prompt_chat + _camila_knowledge_prompt()
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

    valid = dict(SocialPostReaction.REACTION_CHOICES)
    if reaction_type not in valid:
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
            reply_to = SocialPostComment.objects.get(id=int(reply_to_id), post=post)
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
        user_id__in=user_ids
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
# Definir unidade (onboarding)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_set_unidade(request):
    unidade = (request.POST.get("unidade") or "").strip()[:80]
    prof = _get_or_create_profile(request.user)
    prof.unidade = unidade
    prof.save(update_fields=["unidade"])
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


@login_required
def social_user_network(request, user_id: int):
    """
    Retorna a rede de um usuário: seus co-membros de quadros,
    separados em 'em comum comigo' e 'outros'.
    """
    target = get_object_or_404(User, id=user_id)
    target_friend_ids = _board_member_ids(target)
    my_friend_ids     = _board_member_ids(request.user)

    common = []
    others = []
    users  = User.objects.filter(id__in=target_friend_ids).select_related("profile")

    for u in users:
        if u.id == request.user.id:
            continue  # não mostrar a si mesmo
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
        return JsonResponse({"action": "sent"})


@login_required
@require_POST
def social_friend_accept(request, user_id: int):
    """Aceita um convite recebido de user_id."""
    fs = get_object_or_404(SocialFriendship, requester_id=user_id, receiver=request.user)
    fs.status = SocialFriendship.STATUS_ACCEPTED
    fs.save(update_fields=["status"])
    return JsonResponse({"action": "accepted"})


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
    """Testa a Camila com a base de conhecimento atual."""
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido."}, status=400)

    message = (data.get("message") or "").strip()
    if not message:
        return JsonResponse({"error": "Mensagem vazia."}, status=400)

    cfg = CamilaConfig.get()
    prompt = cfg.prompt_chat + _camila_knowledge_prompt()
    response = _groq_chat(
        [{"role": "user", "content": message}],
        prompt,
        config=cfg,
    )
    return JsonResponse({"response": response or "Sem resposta da IA.", "prompt_preview": prompt[:500] + "..."})


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
        raw_text = _extract_text_pdfplumber(pdf_bytes)
        summary = _summarize_with_claude(raw_text, title)
        if summary != raw_text[:4000]:
            results["summarized"] += 1
        pop = CamilaPOP(
            title=title,
            code=code,
            category=category,
            extracted_text=summary,
            is_active=True,
            uploaded_by=request.user,
        )
        # Salva dentro de subpasta por categoria para organizar os arquivos
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
    """Re-sumariza um POP existente com Claude (re-processa o PDF salvo)."""
    import io
    pop = get_object_or_404(CamilaPOP, id=pop_id)
    try:
        pdf_bytes = pop.pdf_file.read()
        raw_text = _extract_text_pdfplumber(pdf_bytes)
        summary = _summarize_with_claude(raw_text, pop.title)
        pop.extracted_text = summary
        pop.save(update_fields=["extracted_text", "updated_at"])
        return JsonResponse({"ok": True, "chars": len(summary)})
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
