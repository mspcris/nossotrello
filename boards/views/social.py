# boards/views/social.py
"""
Espaço social: scrapbook, check-in de humor e chatbot motivacional.
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

from ..models import BoardMembership, SocialPost, SocialPostSeen

User = get_user_model()

_GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_MODEL_DEFAULT = "llama-3.3-70b-versatile"


def _groq_chat(messages: list[dict], system_prompt: str = "") -> str:
    """Chama a Groq API e retorna o texto da resposta."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return "⚠️ Recurso de IA não configurado. Adicione GROQ_API_KEY no .env."
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
        return f"⚠️ Erro ao contatar a IA: {exc}"


def _can_see_social(request, target_user) -> bool:
    if request.user == target_user or request.user.is_staff:
        return True
    return BoardMembership.objects.filter(
        user=request.user,
        board__memberships__user=target_user,
    ).exists()


# ---------------------------------------------------------------
# Painel de posts (GET)
# ---------------------------------------------------------------
@login_required
def social_posts_panel(request, user_id: int):
    target_user = get_object_or_404(User, id=user_id)
    if not _can_see_social(request, target_user):
        raise Http404

    posts = SocialPost.objects.filter(user=target_user).order_by("-created_at")[:30]

    # Marca que o viewer viu os posts agora
    if request.user != target_user and posts.exists():
        SocialPostSeen.objects.update_or_create(
            viewer=request.user,
            target_user=target_user,
            defaults={"last_seen_post_at": timezone.now()},
        )

    return render(request, "boards/social_panel.html", {
        "target_user": target_user,
        "posts": posts,
        "is_me": request.user.id == target_user.id,
    })


# ---------------------------------------------------------------
# Criar post (POST)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_post_create(request):
    text = (request.POST.get("text") or "").strip()
    photo = request.FILES.get("photo")

    if not text and not photo:
        return render(request, "boards/social_panel.html", {
            "target_user": request.user,
            "posts": SocialPost.objects.filter(user=request.user).order_by("-created_at")[:30],
            "is_me": True,
            "post_error": "Adicione um texto ou foto antes de publicar.",
        })

    SocialPost.objects.create(user=request.user, text=text, photo=photo or None)

    posts = SocialPost.objects.filter(user=request.user).order_by("-created_at")[:30]
    return render(request, "boards/social_panel.html", {
        "target_user": request.user,
        "posts": posts,
        "is_me": True,
    })


# ---------------------------------------------------------------
# Deletar post (POST)
# ---------------------------------------------------------------
@login_required
@require_POST
def social_post_delete(request, post_id: int):
    post = get_object_or_404(SocialPost, id=post_id, user=request.user)
    post.delete()

    posts = SocialPost.objects.filter(user=request.user).order_by("-created_at")[:30]
    return render(request, "boards/social_panel.html", {
        "target_user": request.user,
        "posts": posts,
        "is_me": True,
    })


# ---------------------------------------------------------------
# Mood check-in (POST → JSON)
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

    # Mantém apenas as últimas 10 mensagens para não explodir o contexto
    messages = [*history[-10:], {"role": "user", "content": message}]
    response = _groq_chat(messages, system_prompt)
    return JsonResponse({"response": response})
