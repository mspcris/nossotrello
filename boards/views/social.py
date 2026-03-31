# boards/views/social.py
"""
Espaço social: rede social de trabalho — check-in diário, humor,
almoço, pendências do dia, feed de fotos do trabalho.
"""
import json
import os

import requests as http_requests
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model
from django.utils import timezone

from collections import Counter, defaultdict

from ..models import (
    BoardMembership, SocialPost, SocialPostSeen,
    SocialPostReaction, SocialPostComment,
    DailyCheckIn, Card, CardFollow, UserProfile,
    CamilaKnowledge, CamilaConfig,
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
    """Retorna cards que o usuário segue com vencimento hoje ou pendentes."""
    today = timezone.localdate()

    # Cards que o usuário segue, não deletados, não arquivados, não entregues
    followed_ids = CardFollow.objects.filter(user=user).values_list("card_id", flat=True)

    cards = (
        Card.objects
        .filter(id__in=followed_ids, is_deleted=False, is_archived=False, is_delivered=False)
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

    # Pílulas de comentários não vistos (só para o dono)
    unread_comment_posts = []
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
    }
    if extra:
        ctx.update(extra)
    return ctx


# ---------------------------------------------------------------
# Página social standalone (GET) — /social/ ou /social/<user_id>/
# ---------------------------------------------------------------
@login_required
def social_page(request, user_id: int = None):
    """Página standalone do espaço social — pode dar F5 e continuar."""
    if user_id:
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

    # seen_by_owner=True se quem comenta é o próprio dono do post
    comment = SocialPostComment.objects.create(
        user=request.user,
        post=post,
        text=text,
        seen_by_owner=(request.user.id == post.user_id),
    )
    prof = _get_or_create_profile(request.user)

    return JsonResponse({
        "id": comment.id,
        "user": prof.display_name or request.user.email,
        "text": comment.text,
        "created_at": comment.created_at.strftime("%d/%m %H:%M"),
    })


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

    return JsonResponse({"counts": counts, "fresh": fresh, "fresh_texts": fresh_texts, "fresh_ts": fresh_ts})


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

    prompt = _CAMILA_CHAT_BASE + _camila_knowledge_prompt()
    response = _groq_chat(
        [{"role": "user", "content": message}],
        prompt,
    )
    return JsonResponse({"response": response, "prompt_preview": prompt[:500] + "..."})
