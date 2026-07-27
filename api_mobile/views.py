# api_mobile/views.py
"""
Views REST para o app mobile.
Todas as rotas são novas — nenhuma rota existente é alterada.
Autenticação via token (TokenAuthentication do DRF).
"""

from django.contrib.auth import authenticate, get_user_model
from django.db.models import Count, Q, Prefetch, Max
from django.utils import timezone

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

import json as _json
import logging

from boards.models import (
    Board,
    BoardMembership,
    Column,
    Card,
    Checklist,
    ChecklistItem,
    CardLog,
    CardAttachment,
    UserProfile,
    SocialPost,
    SocialPostComment,
    SocialPostReaction,
    SocialFriendship,
    ChatConversation,
    ChatMessage,
    DailyCheckIn,
    Mention,
    NotificationBuffer,
    HealthChatMessage,
    CamilaNews,
)

from boards.views.social import (
    _groq_chat,
    _health_system_prompt,
    _health_food_context,
    _health_history_summary,
    _get_or_create_profile,
)
from boards.services.social_activity import is_socially_active

from .serializers import (
    UserProfileSerializer,
    BoardSerializer,
    ColumnSerializer,
    CardSerializer,
    CardDetailSerializer,
    CardLogSerializer,
    SocialPostSerializer,
    SocialPostCommentSerializer,
    ChatConversationSerializer,
    ChatMessageSerializer,
    DailyCheckInSerializer,
    NotificationSerializer,
    _avatar_url,
)

User = get_user_model()


# ════════════════════════════════════════════════════════════════
# AUTH — login por username/email + senha → retorna token
# ════════════════════════════════════════════════════════════════
@api_view(["POST"])
@permission_classes([AllowAny])
def api_login(request):
    """
    POST /api/mobile/auth/login/
    Body: {"username": "...", "password": "..."}
    """
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""

    if not username or not password:
        return Response({"error": "username e password obrigatórios"}, status=status.HTTP_400_BAD_REQUEST)

    user = authenticate(request=request._request, username=username, password=password)
    if user is None:
        return Response({"error": "Credenciais inválidas"}, status=status.HTTP_401_UNAUTHORIZED)

    if not user.is_active:
        return Response({"error": "Conta inativa"}, status=status.HTTP_403_FORBIDDEN)

    token, _ = Token.objects.get_or_create(user=user)
    profile = getattr(user, "profile", None)

    return Response({
        "token": token.key,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display_name": profile.display_name if profile else "",
            "avatar_url": _avatar_url(profile, request),
        },
    })


@api_view(["POST"])
@permission_classes([AllowAny])
def api_login_camim(request):
    """
    POST /api/mobile/auth/login-camim/
    Body: {"access_token": "..."}
    Recebe access_token do IDCamim e retorna token da API.
    """
    import requests as http_requests

    access_token = (request.data.get("access_token") or "").strip()
    if not access_token:
        return Response({"error": "access_token obrigatório"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        resp = http_requests.get(
            "https://auth.camim.com.br/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        userinfo = resp.json()
    except Exception:
        return Response({"error": "Falha ao validar token com IDCamim"}, status=status.HTTP_401_UNAUTHORIZED)

    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        return Response({"error": "Email não retornado pelo IDCamim"}, status=status.HTTP_400_BAD_REQUEST)

    sub = (userinfo.get("sub") or "").strip()

    name = (userinfo.get("name") or "").strip()
    first_name = (userinfo.get("given_name") or name.split()[0] if name else "").strip()
    last_name = (userinfo.get("family_name") or " ".join(name.split()[1:]) if name else "").strip()

    from boards.services.camim_identity import resolve_or_create_camim_user
    user = resolve_or_create_camim_user(
        sub=sub, email=email, first_name=first_name, last_name=last_name,
    )

    if not user.is_active:
        return Response({"error": "Conta inativa"}, status=status.HTTP_403_FORBIDDEN)

    token, _ = Token.objects.get_or_create(user=user)
    profile = getattr(user, "profile", None)

    return Response({
        "token": token.key,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "display_name": profile.display_name if profile else "",
            "avatar_url": _avatar_url(profile, request),
        },
    })


@api_view(["POST"])
def api_logout(request):
    try:
        request.user.auth_token.delete()
    except Exception:
        pass
    return Response({"ok": True})


# ════════════════════════════════════════════════════════════════
# PROFILE
# ════════════════════════════════════════════════════════════════
@api_view(["GET"])
def api_me(request):
    user = request.user
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    return Response(UserProfileSerializer(profile, context={"request": request}).data)


@api_view(["PATCH"])
def api_me_update(request):
    user = request.user
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)

    allowed = [
        "display_name", "handle", "unidade", "posto", "setor", "ramal", "telefone",
        "share_posto", "share_setor", "share_ramal", "share_telefone",
        "notify_whatsapp", "notify_email", "notify_social",
        "activity_sidebar", "board_col_width", "activity_counts",
    ]
    for field in allowed:
        if field in request.data:
            setattr(profile, field, request.data[field])
    profile.save()

    if "first_name" in request.data:
        user.first_name = request.data["first_name"]
    if "last_name" in request.data:
        user.last_name = request.data["last_name"]
    if "first_name" in request.data or "last_name" in request.data:
        user.save(update_fields=["first_name", "last_name"])

    return Response(UserProfileSerializer(profile, context={"request": request}).data)


# ════════════════════════════════════════════════════════════════
# BOARDS
# ════════════════════════════════════════════════════════════════
@api_view(["GET"])
def api_boards(request):
    user = request.user
    memberships = BoardMembership.objects.filter(user=user).select_related("board", "board__organization")
    boards = []
    for m in memberships:
        b = m.board
        if b.is_deleted:
            continue
        b._user_membership = m
        boards.append(b)
    return Response(BoardSerializer(boards, many=True, context={"request": request}).data)


@api_view(["GET"])
def api_board_detail(request, board_id):
    user = request.user
    try:
        membership = BoardMembership.objects.select_related("board").get(board__id=board_id, user=user)
    except BoardMembership.DoesNotExist:
        return Response({"error": "Board não encontrado"}, status=status.HTTP_404_NOT_FOUND)

    board = membership.board
    columns = Column.objects.filter(board=board, is_deleted=False).order_by("position")
    cards = (
        Card.objects
        .filter(column__board=board)
        .select_related("created_by", "column")
        .annotate(
            _checklist_total=Count("checklist_items"),
            _checklist_done=Count("checklist_items", filter=Q(checklist_items__is_done=True)),
            _comments_count=Count("logs"),
            # annotate ignora o manager: filtrar o soft-delete na mão
            _attachments_count=Count("attachments", filter=Q(attachments__is_active=True)),
        )
        .order_by("position")
    )

    cards_by_column = {}
    for card in cards:
        cards_by_column.setdefault(card.column_id, []).append(card)

    columns_data = []
    for col in columns:
        col_data = ColumnSerializer(col).data
        col_data["cards"] = CardSerializer(cards_by_column.get(col.id, []), many=True, context={"request": request}).data
        columns_data.append(col_data)

    board._user_membership = membership
    board_data = BoardSerializer(board, context={"request": request}).data
    board_data["columns"] = columns_data
    return Response(board_data)


# ════════════════════════════════════════════════════════════════
# CARDS
# ════════════════════════════════════════════════════════════════
@api_view(["GET"])
def api_card_detail(request, card_id):
    try:
        card = (
            Card.all_objects
            .select_related("created_by", "column", "column__board")
            .prefetch_related(
                Prefetch("checklists", queryset=Checklist.objects.prefetch_related("items").order_by("position")),
                Prefetch("attachments", queryset=CardAttachment.objects.order_by("-created_at")),
            )
            .annotate(
                _checklist_total=Count("checklist_items"),
                _checklist_done=Count("checklist_items", filter=Q(checklist_items__is_done=True)),
                _comments_count=Count("logs"),
                # annotate ignora o manager: filtrar o soft-delete na mão
                _attachments_count=Count("attachments", filter=Q(attachments__is_active=True)),
            )
            .get(id=card_id)
        )
    except Card.DoesNotExist:
        return Response({"error": "Card não encontrado"}, status=status.HTTP_404_NOT_FOUND)

    if not BoardMembership.objects.filter(board=card.column.board, user=request.user).exists():
        return Response({"error": "Sem acesso"}, status=status.HTTP_403_FORBIDDEN)

    return Response(CardDetailSerializer(card, context={"request": request}).data)


@api_view(["POST"])
def api_card_create(request, column_id):
    try:
        column = Column.objects.select_related("board").get(id=column_id, is_deleted=False)
    except Column.DoesNotExist:
        return Response({"error": "Coluna não encontrada"}, status=status.HTTP_404_NOT_FOUND)

    if not BoardMembership.objects.filter(board=column.board, user=request.user, role__in=["owner", "editor"]).exists():
        return Response({"error": "Sem permissão"}, status=status.HTTP_403_FORBIDDEN)

    title = (request.data.get("title") or "").strip()
    if not title:
        return Response({"error": "Título obrigatório"}, status=status.HTTP_400_BAD_REQUEST)

    max_pos = Card.objects.filter(column=column).aggregate(m=Max("position"))["m"] or 0
    card = Card.objects.create(
        column=column, title=title,
        description=request.data.get("description", ""),
        position=max_pos + 1, created_by=request.user,
    )
    Board.all_objects.filter(id=column.board_id).update(version=column.board.version + 1)
    return Response(CardSerializer(card, context={"request": request}).data, status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
def api_card_update(request, card_id):
    try:
        card = Card.all_objects.select_related("column__board").get(id=card_id)
    except Card.DoesNotExist:
        return Response({"error": "Card não encontrado"}, status=status.HTTP_404_NOT_FOUND)

    if not BoardMembership.objects.filter(board=card.column.board, user=request.user, role__in=["owner", "editor"]).exists():
        return Response({"error": "Sem permissão"}, status=status.HTTP_403_FORBIDDEN)

    for field in ["title", "description", "tags", "due_date", "start_date", "due_warn_date"]:
        if field in request.data:
            setattr(card, field, request.data[field])
    card.save()
    Board.all_objects.filter(id=card.column.board_id).update(version=card.column.board.version + 1)
    return Response(CardSerializer(card, context={"request": request}).data)


@api_view(["POST"])
def api_card_move(request, card_id):
    try:
        card = Card.all_objects.select_related("column__board").get(id=card_id)
    except Card.DoesNotExist:
        return Response({"error": "Card não encontrado"}, status=status.HTTP_404_NOT_FOUND)

    if not BoardMembership.objects.filter(board=card.column.board, user=request.user, role__in=["owner", "editor"]).exists():
        return Response({"error": "Sem permissão"}, status=status.HTTP_403_FORBIDDEN)

    new_column_id = request.data.get("column_id")
    if new_column_id:
        try:
            new_column = Column.objects.get(id=new_column_id, board=card.column.board, is_deleted=False)
            card.column = new_column
        except Column.DoesNotExist:
            return Response({"error": "Coluna não encontrada"}, status=status.HTTP_404_NOT_FOUND)

    card.position = request.data.get("position", 0)
    card.save()
    Board.all_objects.filter(id=card.column.board_id).update(version=card.column.board.version + 1)
    return Response({"ok": True})


@api_view(["POST"])
def api_card_deliver(request, card_id):
    """Move o card para uma coluna E marca como Entregue, executando TUDO o que a
    interface executaria (automações da coluna, feed, seguidores, e-mail/WhatsApp
    de entrega).

    Existe porque o HESK precisa disso ao resolver um chamado, e os caminhos
    atuais não servem: `api_card_move` não roda as automações e `api_card_update`
    não aceita `is_delivered`. Escrever direto no Postgres também não resolveria —
    a notificação de entrega é in-process.

    Corpo: {"column_id": <int, opcional>, "deliver": <bool, default true>,
            "actor_email": "<e-mail, opcional>"}

    `actor_email` permite atribuir a ação à PESSOA que resolveu o chamado no
    outro sistema, em vez de ao usuário do token. Só é aceito se essa pessoa
    também tiver acesso de escrita ao quadro."""
    from boards.services.card_delivery import mover_e_entregar

    try:
        card = Card.all_objects.select_related("column__board").get(id=card_id)
    except Card.DoesNotExist:
        return Response({"error": "Card não encontrado"}, status=status.HTTP_404_NOT_FOUND)

    board = card.column.board
    if not BoardMembership.objects.filter(
            board=board, user=request.user, role__in=["owner", "editor"]).exists():
        return Response({"error": "Sem permissão"}, status=status.HTTP_403_FORBIDDEN)

    coluna = card.column
    col_id = request.data.get("column_id")
    if col_id:
        try:
            coluna = Column.objects.get(id=col_id, board=board, is_deleted=False)
        except Column.DoesNotExist:
            return Response({"error": "Coluna não encontrada neste quadro"},
                            status=status.HTTP_404_NOT_FOUND)

    # Autoria: por padrão o dono do token; se vier actor_email de alguém com
    # acesso de escrita ao quadro, a ação sai no nome dessa pessoa.
    actor = request.user
    email = (request.data.get("actor_email") or "").strip().lower()
    if email:
        cand = User.objects.filter(email__iexact=email).first()
        if cand and BoardMembership.objects.filter(
                board=board, user=cand, role__in=["owner", "editor"]).exists():
            actor = cand

    deliver = request.data.get("deliver", True)
    if isinstance(deliver, str):
        deliver = deliver.strip().lower() in ("1", "true", "on", "yes")

    r = mover_e_entregar(card=card, coluna_destino=coluna, actor=actor,
                         request=request, entregar=bool(deliver))
    return Response({"ok": True, "card_id": card.id, "actor": actor.get_username(), **r})


@api_view(["POST"])
def api_card_description(request, card_id):
    """Troca a descrição do card REGISTRANDO Antes/Depois no feed, igual à
    interface. O `api_card_update` também aceita `description`, mas grava em
    silêncio — e quem edita pelo HESK precisa aparecer no histórico do card.

    Corpo: {"description": "<html>", "actor_email": "<e-mail, opcional>"}"""
    from boards.services.card_description import atualizar_descricao

    try:
        card = Card.all_objects.select_related("column__board").get(id=card_id)
    except Card.DoesNotExist:
        return Response({"error": "Card não encontrado"}, status=status.HTTP_404_NOT_FOUND)

    board = card.column.board
    if not BoardMembership.objects.filter(
            board=board, user=request.user, role__in=["owner", "editor"]).exists():
        return Response({"error": "Sem permissão"}, status=status.HTTP_403_FORBIDDEN)

    if "description" not in request.data:
        return Response({"error": "description obrigatório"},
                        status=status.HTTP_400_BAD_REQUEST)

    actor = request.user
    email = (request.data.get("actor_email") or "").strip().lower()
    if email:
        cand = User.objects.filter(email__iexact=email).first()
        if cand and BoardMembership.objects.filter(
                board=board, user=cand, role__in=["owner", "editor"]).exists():
            actor = cand

    mudou = atualizar_descricao(card=card, descricao=request.data.get("description") or "",
                                actor=actor, request=request)
    return Response({"ok": True, "card_id": card.id, "alterada": mudou,
                     "actor": actor.get_username()})


# ════════════════════════════════════════════════════════════════
# CARD ACTIVITY
# ════════════════════════════════════════════════════════════════
@api_view(["GET"])
def api_card_activity(request, card_id):
    logs = (
        CardLog.objects.filter(card_id=card_id)
        .select_related("actor", "actor__profile")
        .order_by("-created_at")[:50]
    )
    return Response(CardLogSerializer(logs, many=True, context={"request": request}).data)


@api_view(["POST"])
def api_card_comment(request, card_id):
    text = (request.data.get("text") or "").strip()
    if not text:
        return Response({"error": "Texto obrigatório"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        card = Card.all_objects.get(id=card_id)
    except Card.DoesNotExist:
        return Response({"error": "Card não encontrado"}, status=status.HTTP_404_NOT_FOUND)

    log = CardLog.objects.create(card=card, actor=request.user, content_text=text, content=f"<p>{text}</p>")
    return Response(CardLogSerializer(log, context={"request": request}).data, status=status.HTTP_201_CREATED)


# ════════════════════════════════════════════════════════════════
# CHECKLIST
# ════════════════════════════════════════════════════════════════
@api_view(["POST"])
def api_checklist_toggle(request, item_id):
    try:
        item = ChecklistItem.objects.get(id=item_id)
    except ChecklistItem.DoesNotExist:
        return Response({"error": "Item não encontrado"}, status=status.HTTP_404_NOT_FOUND)
    item.is_done = not item.is_done
    item.save()
    return Response({"is_done": item.is_done})


# ════════════════════════════════════════════════════════════════
# SOCIAL FEED
# ════════════════════════════════════════════════════════════════
@api_view(["GET"])
def api_social_feed(request):
    user = request.user
    page = int(request.query_params.get("page", 1))
    per_page = 20
    offset = (page - 1) * per_page
    owner_only = request.query_params.get("owner") == "true"

    if owner_only:
        posts = (
            SocialPost.objects
            .filter(user=user)
            .select_related("user", "user__profile")
            .annotate(_comments_count=Count("comments"))
            .order_by("-created_at")[offset:offset + per_page]
        )
    else:
        friends_ids = set()
        for f in SocialFriendship.objects.filter(Q(requester=user) | Q(receiver=user), status="accepted"):
            friends_ids.add(f.requester_id if f.receiver_id == user.id else f.receiver_id)

        posts = (
            SocialPost.objects
            .filter(Q(user=user) | Q(visibility="all") | Q(user_id__in=friends_ids))
            .select_related("user", "user__profile")
            .annotate(_comments_count=Count("comments"))
            .order_by("-created_at")[offset:offset + per_page]
        )
    for post in posts:
        reactions = SocialPostReaction.objects.filter(post=post).values("emoji").annotate(c=Count("id"))
        post._reactions_summary = {r["emoji"]: r["c"] for r in reactions}

    serialized = SocialPostSerializer(posts, many=True, context={"request": request}).data

    # Annotate friendship posts
    User = get_user_model()
    hidden_ids = set()
    for item in serialized:
        text = item.get("text") or ""
        if text.startswith("__friendship__:"):
            item["is_friendship"] = True
            try:
                friend_uid = int(text.split(":")[1])
                friend_user = User.objects.select_related("profile").get(id=friend_uid)
                # Find the post author profile
                post_obj = next((p for p in posts if p.id == item["id"]), None)
                # Some se um dos dois não loga há +30d (some socialmente).
                if (not is_socially_active(friend_user)
                        or (post_obj and not is_socially_active(post_obj.user))):
                    hidden_ids.add(item["id"])
                    continue
                friend_prof = getattr(friend_user, "profile", None)
                post_prof = getattr(post_obj.user, "profile", None) if post_obj else None
                item["friendship"] = {
                    "friend_name": friend_prof.display_name if friend_prof and friend_prof.display_name else friend_user.get_full_name(),
                    "friend_avatar": _avatar_url(friend_prof, request) or "",
                    "friend_id": friend_uid,
                    "user_name": post_prof.display_name if post_prof and post_prof.display_name else (post_obj.user.get_full_name() if post_obj else ""),
                    "user_avatar": _avatar_url(post_prof, request) or "",
                }
                item["text"] = ""  # Hide internal text
            except Exception:
                item["friendship"] = None
        else:
            item["is_friendship"] = False
            item["friendship"] = None

    if hidden_ids:
        serialized = [i for i in serialized if i["id"] not in hidden_ids]
    return Response(serialized)


@api_view(["POST"])
def api_social_post_create(request):
    text = (request.data.get("text") or "").strip()
    text_style = request.data.get("text_style")
    post = SocialPost.objects.create(
        user=request.user,
        text=text,
        visibility=request.data.get("visibility", "all"),
        text_style=text_style if isinstance(text_style, dict) else None,
    )
    return Response(SocialPostSerializer(post, context={"request": request}).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def api_social_react(request, post_id):
    emoji = request.data.get("emoji", "like")
    reaction, created = SocialPostReaction.objects.get_or_create(
        user=request.user, post_id=post_id, defaults={"emoji": emoji},
    )
    if not created:
        if reaction.emoji == emoji:
            reaction.delete()
            return Response({"removed": True})
        reaction.emoji = emoji
        reaction.save()
    return Response({"emoji": emoji, "created": created})


@api_view(["GET"])
def api_social_comments(request, post_id):
    comments = (
        SocialPostComment.objects.filter(post_id=post_id)
        .select_related("user", "user__profile").order_by("created_at")
    )
    return Response(SocialPostCommentSerializer(comments, many=True, context={"request": request}).data)


@api_view(["POST"])
def api_social_comment_create(request, post_id):
    text = (request.data.get("text") or "").strip()
    if not text:
        return Response({"error": "Texto obrigatório"}, status=status.HTTP_400_BAD_REQUEST)
    comment = SocialPostComment.objects.create(
        post_id=post_id, user=request.user, text=text, reply_to_id=request.data.get("reply_to"),
    )
    return Response(SocialPostCommentSerializer(comment, context={"request": request}).data, status=status.HTTP_201_CREATED)


# ════════════════════════════════════════════════════════════════
# CHAT
# ════════════════════════════════════════════════════════════════
@api_view(["GET"])
def api_chat_conversations(request):
    user = request.user
    convs = (
        ChatConversation.objects
        .filter(Q(user_a=user) | Q(user_b=user))
        .select_related("user_a", "user_a__profile", "user_b", "user_b__profile")
        .order_by("-updated_at")
    )
    for conv in convs:
        conv._last_message = ChatMessage.objects.filter(conversation=conv).order_by("-created_at").first()
        conv._unread_count = ChatMessage.objects.filter(conversation=conv, seen=False).exclude(sender=user).count()
    return Response(ChatConversationSerializer(convs, many=True, context={"request": request}).data)


@api_view(["GET"])
def api_chat_messages(request, conversation_id):
    user = request.user
    try:
        conv = ChatConversation.objects.get(Q(user_a=user) | Q(user_b=user), id=conversation_id)
    except ChatConversation.DoesNotExist:
        return Response({"error": "Conversa não encontrada"}, status=status.HTTP_404_NOT_FOUND)

    ChatMessage.objects.filter(conversation=conv, seen=False).exclude(sender=user).update(seen=True)
    messages = ChatMessage.objects.filter(conversation=conv).select_related("sender").order_by("-created_at")[:100]
    return Response(ChatMessageSerializer(messages, many=True, context={"request": request}).data)


@api_view(["POST"])
def api_chat_send(request, conversation_id):
    user = request.user
    try:
        conv = ChatConversation.objects.get(Q(user_a=user) | Q(user_b=user), id=conversation_id)
    except ChatConversation.DoesNotExist:
        return Response({"error": "Conversa não encontrada"}, status=status.HTTP_404_NOT_FOUND)

    text = (request.data.get("text") or "").strip()
    if not text:
        return Response({"error": "Texto obrigatório"}, status=status.HTTP_400_BAD_REQUEST)

    msg = ChatMessage.objects.create(conversation=conv, sender=user, text=text)
    conv.save()
    return Response(ChatMessageSerializer(msg, context={"request": request}).data, status=status.HTTP_201_CREATED)


# ════════════════════════════════════════════════════════════════
# DAILY CHECK-IN
# ════════════════════════════════════════════════════════════════
@api_view(["GET", "POST"])
def api_daily_checkin(request):
    today = timezone.localdate()
    user = request.user

    if request.method == "GET":
        try:
            checkin = DailyCheckIn.objects.get(user=user, date=today)
            return Response(DailyCheckInSerializer(checkin).data)
        except DailyCheckIn.DoesNotExist:
            return Response(None, status=status.HTTP_204_NO_CONTENT)

    checkin, _ = DailyCheckIn.objects.update_or_create(
        user=user, date=today,
        defaults={
            "mood": request.data.get("mood", "neutral"),
            "lunch_text": request.data.get("lunch_text", ""),
            "daily_posto": request.data.get("daily_posto", ""),
        },
    )
    return Response(DailyCheckInSerializer(checkin).data)


# ════════════════════════════════════════════════════════════════
# NOTIFICATIONS / MENTIONS / SEARCH
# ════════════════════════════════════════════════════════════════
@api_view(["GET"])
def api_notifications(request):
    notifs = NotificationBuffer.objects.filter(recipient=request.user).order_by("-created_at")[:50]
    return Response(NotificationSerializer(notifs, many=True).data)


@api_view(["GET"])
def api_mentions(request):
    mentions = (
        Mention.objects.filter(mentioned_user=request.user, seen_count=0)
        .select_related("card", "actor").order_by("-created_at")[:30]
    )
    return Response([{
        "id": m.id, "card_id": m.card_id,
        "card_title": m.card.title if m.card else "",
        "actor_name": m.actor.get_full_name() if m.actor else "",
        "source": m.source, "created_at": m.created_at,
    } for m in mentions])


@api_view(["POST"])
def api_mentions_mark_seen(request):
    Mention.objects.filter(mentioned_user=request.user, seen_count=0).update(seen_count=1)
    return Response({"ok": True})


@api_view(["GET"])
def api_search(request):
    q = (request.query_params.get("q") or "").strip()
    if len(q) < 2:
        return Response({"boards": [], "cards": []})

    board_ids = BoardMembership.objects.filter(user=request.user).values_list("board_id", flat=True)
    boards = Board.all_objects.filter(id__in=board_ids, name__icontains=q, is_deleted=False)[:10]
    cards = Card.objects.filter(column__board_id__in=board_ids, title__icontains=q).select_related("column__board")[:20]

    return Response({
        "boards": [{"id": b.id, "name": b.name} for b in boards],
        "cards": [{"id": c.id, "title": c.title, "board_name": c.column.board.name, "column_name": c.column.name} for c in cards],
    })


# ════════════════════════════════════════════════════════════════
# SAÚDE E BEM ESTAR
# ════════════════════════════════════════════════════════════════
@api_view(["GET"])
def api_health_analyze(request):
    user = request.user
    profile = _get_or_create_profile(user)
    user_name = profile.display_name or user.email.split("@")[0]

    food_context = _health_food_context(user)
    history_summary, prev_messages = _health_history_summary(user)

    if history_summary:
        user_msg = "Retomando nossa conversa! Faça um resumo breve do que já conversamos e continue de onde paramos."
    elif food_context:
        user_msg = "Olá! Analise minha alimentação recente e me dê dicas."
    else:
        user_msg = "Olá! Quero começar a cuidar mais da minha saúde e alimentação."

    prompt = _health_system_prompt(user_name, food_context, history_summary)
    messages = [*prev_messages[-6:], {"role": "user", "content": user_msg}]

    try:
        from boards.models import CamilaConfig
        cfg = CamilaConfig.get()
        response = _groq_chat(messages, prompt, config=cfg)
    except Exception as exc:
        logging.getLogger(__name__).error("Health analyze error: %s", exc)
        response = ""

    if not response or response.startswith("Erro"):
        response = (
            f"Olá, {user_name}! Vamos falar sobre sua saúde e bem-estar? "
            "Me conta: o que você vai comer hoje no almoço?"
        )

    HealthChatMessage.objects.create(user=user, role="assistant", text=response)

    recent = list(HealthChatMessage.objects.filter(user=user).order_by("-created_at")[:30])
    recent.reverse()
    chat_history = [
        {"role": m.role, "text": m.text, "time": m.created_at.strftime("%d/%m %H:%M")}
        for m in recent
    ]

    return Response({"response": response, "user_name": user_name, "history": chat_history})


@api_view(["POST"])
def api_health_chat(request):
    message = (request.data.get("message") or "").strip()
    if not message:
        return Response({"error": "Mensagem vazia."}, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    profile = _get_or_create_profile(user)
    user_name = profile.display_name or user.email.split("@")[0]

    HealthChatMessage.objects.create(user=user, role="user", text=message)

    recent_db = list(HealthChatMessage.objects.filter(user=user).order_by("-created_at")[:12])
    db_messages = [{"role": m.role, "content": m.text} for m in reversed(recent_db)]

    food_context = _health_food_context(user)
    prompt = _health_system_prompt(user_name, food_context)

    try:
        from boards.models import CamilaConfig
        cfg = CamilaConfig.get()
        response = _groq_chat(db_messages, prompt, config=cfg)
    except Exception as exc:
        logging.getLogger(__name__).error("Health chat error: %s", exc)
        response = "Desculpe, não consegui processar. Tente novamente."

    if response and not response.startswith("Erro"):
        HealthChatMessage.objects.create(user=user, role="assistant", text=response)

    return Response({"response": response})


# ════════════════════════════════════════════════════════════════
# CAMILA CHAT
# ════════════════════════════════════════════════════════════════
@api_view(["POST"])
def api_camila_chat(request):
    """Chat com a Camila.AI — assistente interna da CAMIM."""
    message = (request.data.get("message") or "").strip()
    history = request.data.get("history") or []
    if not message:
        return Response({"error": "Mensagem vazia."}, status=status.HTTP_400_BAD_REQUEST)

    from boards.models import CamilaConfig, CamilaKnowledge, CamilaPOP
    from boards.views.social import _groq_chat, _camila_knowledge_prompt, _get_weather_context

    cfg = CamilaConfig.get()

    social_ctx = (
        "\n\n[REGRAS IMPORTANTES]\n"
        "1. Você está DENTRO da rede social interna da CAMIM (tarefas.camim.com.br/social/).\n"
        "2. NUNCA diga 'não entendi'. Se a mensagem for curta (ex: 'como?', 'como fazer?', 'sim'), "
        "INTERPRETE pelo contexto da conversa anterior (history).\n"
        "3. Respostas CURTAS e DIRETAS. Máximo 3-4 frases. Sem enrolação.\n"
        "4. NUNCA redirecione para Central de Atendimento para dúvidas sobre a rede social.\n"
        "\n[COMO USAR A REDE SOCIAL]\n"
        "- PUBLICAR: tocar no botão de caneta (roxo) → escrever texto, "
        "escolher foto/vídeo da galeria → enviar.\n"
        "- REAGIR: nos posts do feed, tocar em emojis.\n"
        "- COMENTAR: campo abaixo de cada post → digitar → enviar.\n"
        "- PERFIL: menu lateral → Perfil → editar dados.\n"
        "- HUMOR: aba Check-in → escolher emoji.\n"
    )

    prompt = cfg.prompt_chat + social_ctx + _camila_knowledge_prompt(message) + _get_weather_context()
    messages = [*history[-10:], {"role": "user", "content": message}]
    response = _groq_chat(messages, prompt, config=cfg)
    return Response({"response": response})


# ════════════════════════════════════════════════════════════════
# CAMILA NEWS
# ════════════════════════════════════════════════════════════════
@api_view(["GET"])
def api_camila_news(request):
    """Retorna todas as notícias salvas pela Camila."""
    qs = CamilaNews.objects.order_by("-fetched_at").values("title", "url", "fetched_at")[:200]
    items = [
        {
            "title": n["title"],
            "url": n["url"],
            "date": timezone.localtime(n["fetched_at"]).strftime("%d/%m/%Y %H:%M"),
        }
        for n in qs
    ]
    return Response({"news": items})
