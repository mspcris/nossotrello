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
)

User = get_user_model()

_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL_DEFAULT = "llama-3.3-70b-versatile"


def _groq_chat(messages: list[dict], system_prompt: str = "") -> str:
    """Chama a Groq API e retorna o texto da resposta."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return ""
    model = os.getenv("GROQ_MODEL", "").strip() or _GROQ_MODEL_DEFAULT
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages,
        ],
        "max_tokens": 500,
        "temperature": 0.8,
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

    # AI react trigger
    parts = []
    if checkin.mood:
        mood_labels = dict(DailyCheckIn.MOOD_CHOICES)
        parts.append(f"Humor: {mood_labels.get(checkin.mood, checkin.mood)}")
    if checkin.lunch_text:
        parts.append(f"Almoço: {checkin.lunch_text}")
    if checkin.daily_posto:
        parts.append(f"Posto: {checkin.daily_posto}")
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
        prof.cover_photo = f
        prof.save(update_fields=["cover_photo"])
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

    system_prompt = (
        "Você é Tuca, um coach de bem-estar gentil e prático. "
        "Seu foco é motivação, hábitos saudáveis e saúde mental. "
        "Converse de forma leve, positiva e acolhedora. "
        "Nunca diagnostique doenças. Se perceber sofrimento intenso, "
        "sugira buscar apoio profissional. "
        "Respostas curtas e diretas (máximo 3 parágrafos). Português brasileiro."
    )

    messages = [*history[-10:], {"role": "user", "content": message}]
    response = _groq_chat(messages, system_prompt)
    return JsonResponse({"response": response})


# ---------------------------------------------------------------
# Camila.AI — reação inteligente a ações do usuário (POST → JSON)
# ---------------------------------------------------------------
_CAMILA_SYSTEM = (
    "Você é Camila, a IA simpática da rede social de trabalho da CAMIM. "
    "O colega acabou de compartilhar algo na rede. Faça um comentário CURTO "
    "(1-2 frases no máximo), divertido, engajador e caloroso. Use emojis. "
    "Se ele falou o que vai almoçar, comente sobre a comida de forma "
    "descontraída (ex: 'Que delícia!', 'Tá de dieta ou tá se dando bem?'). "
    "Se falou o humor, acolha. Se postou algo, incentive. "
    "Seja leve, profissional e NUNCA chata. Português brasileiro."
)


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

    response = _groq_chat(
        [{"role": "user", "content": context}],
        _CAMILA_SYSTEM,
    )
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

    comment = SocialPostComment.objects.create(
        user=request.user, post=post, text=text,
    )
    prof = _get_or_create_profile(request.user)

    return JsonResponse({
        "id": comment.id,
        "user": prof.display_name or request.user.email,
        "text": comment.text,
        "created_at": comment.created_at.strftime("%d/%m %H:%M"),
    })
