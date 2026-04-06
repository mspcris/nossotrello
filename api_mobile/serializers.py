# api_mobile/serializers.py
"""Serializers REST para o app mobile — dados somente leitura + ações."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from boards.models import (
    Organization,
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
    CardFollow,
    BoardGroup,
    BoardGroupItem,
    NotificationBuffer,
)

User = get_user_model()


# ── helpers ──────────────────────────────────────────────────────
def _avatar_url(profile, request=None):
    if profile and profile.avatar:
        url = profile.avatar.url
        if request:
            return request.build_absolute_uri(url)
        return url
    return None


# ── User / Profile ──────────────────────────────────────────────
class UserMiniSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "display_name", "avatar_url"]

    def get_display_name(self, obj):
        profile = getattr(obj, "profile", None)
        if profile and profile.display_name:
            return profile.display_name
        full = f"{obj.first_name} {obj.last_name}".strip()
        return full or obj.username

    def get_avatar_url(self, obj):
        return _avatar_url(getattr(obj, "profile", None), self.context.get("request"))


class UserProfileSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(source="*")
    avatar_url = serializers.SerializerMethodField()
    cover_photo_url = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            "user",
            "display_name",
            "handle",
            "avatar_url",
            "cover_photo_url",
            "unidade",
            "posto",
            "setor",
            "ramal",
            "telefone",
            "share_posto",
            "share_setor",
            "share_ramal",
            "share_telefone",
            "notify_whatsapp",
            "notify_email",
            "notify_social",
            "activity_sidebar",
            "board_col_width",
            "activity_counts",
            "terms_accepted",
            "onboarding_done",
        ]

    def get_avatar_url(self, obj):
        return _avatar_url(obj, self.context.get("request"))

    def get_cover_photo_url(self, obj):
        if obj.cover_photo:
            req = self.context.get("request")
            url = obj.cover_photo.url
            return req.build_absolute_uri(url) if req else url
        return None


# ── Organization ─────────────────────────────────────────────────
class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "created_at"]


# ── Board ────────────────────────────────────────────────────────
class BoardSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    organization_name = serializers.CharField(source="organization.name", default=None)

    class Meta:
        model = Board
        fields = [
            "id",
            "name",
            "image_url",
            "organization",
            "organization_name",
            "is_archived",
            "is_deleted",
            "version",
            "show_aggregator_column",
            "role",
            "created_at",
        ]

    def get_role(self, obj):
        user = self.context.get("request", {})
        if hasattr(user, "user"):
            user = user.user
        membership = getattr(obj, "_user_membership", None)
        if membership:
            return membership.role
        return None

    def get_image_url(self, obj):
        if obj.image:
            req = self.context.get("request")
            url = obj.image.url
            return req.build_absolute_uri(url) if req else url
        return None


# ── Column ───────────────────────────────────────────────────────
class ColumnSerializer(serializers.ModelSerializer):
    class Meta:
        model = Column
        fields = ["id", "name", "position", "theme", "board"]


# ── Checklist / Items ────────────────────────────────────────────
class ChecklistItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChecklistItem
        fields = ["id", "text", "is_done", "position", "checklist"]


class ChecklistSerializer(serializers.ModelSerializer):
    items = ChecklistItemSerializer(many=True, read_only=True)

    class Meta:
        model = Checklist
        fields = ["id", "title", "position", "card", "items"]


# ── Card Attachment ──────────────────────────────────────────────
class CardAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CardAttachment
        fields = ["id", "file_url", "description", "created_by_name", "created_at"]

    def get_file_url(self, obj):
        if obj.file:
            req = self.context.get("request")
            return req.build_absolute_uri(obj.file.url) if req else obj.file.url
        return None

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return None


# ── Card Log (Activity / Comments) ──────────────────────────────
class CardLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    actor_avatar = serializers.SerializerMethodField()

    class Meta:
        model = CardLog
        fields = [
            "id",
            "content_text",
            "content",
            "actor",
            "actor_name",
            "actor_avatar",
            "reply_to",
            "created_at",
        ]

    def get_actor_name(self, obj):
        if obj.actor:
            return obj.actor.get_full_name() or obj.actor.username
        return "Sistema"

    def get_actor_avatar(self, obj):
        if obj.actor:
            return _avatar_url(getattr(obj.actor, "profile", None), self.context.get("request"))
        return None


# ── Card ─────────────────────────────────────────────────────────
class CardSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    cover_image_url = serializers.SerializerMethodField()
    checklist_total = serializers.SerializerMethodField()
    checklist_done = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()
    attachments_count = serializers.SerializerMethodField()

    class Meta:
        model = Card
        fields = [
            "id",
            "title",
            "description",
            "tags",
            "tag_colors",
            "column",
            "position",
            "start_date",
            "due_date",
            "due_warn_date",
            "is_delivered",
            "delivered_at",
            "cover_image_url",
            "created_by_name",
            "checklist_total",
            "checklist_done",
            "comments_count",
            "attachments_count",
            "created_at",
        ]

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return None

    def get_cover_image_url(self, obj):
        if obj.cover_image:
            req = self.context.get("request")
            return req.build_absolute_uri(obj.cover_image.url) if req else obj.cover_image.url
        return None

    def get_checklist_total(self, obj):
        return getattr(obj, "_checklist_total", 0)

    def get_checklist_done(self, obj):
        return getattr(obj, "_checklist_done", 0)

    def get_comments_count(self, obj):
        return getattr(obj, "_comments_count", 0)

    def get_attachments_count(self, obj):
        return getattr(obj, "_attachments_count", 0)


class CardDetailSerializer(CardSerializer):
    checklists = ChecklistSerializer(many=True, read_only=True)
    attachments = CardAttachmentSerializer(many=True, read_only=True)

    class Meta(CardSerializer.Meta):
        fields = CardSerializer.Meta.fields + ["checklists", "attachments"]


# ── Social ───────────────────────────────────────────────────────
class SocialPostSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    user_avatar = serializers.SerializerMethodField()
    user_handle = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    reactions_summary = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()

    class Meta:
        model = SocialPost
        fields = [
            "id",
            "text",
            "photo_url",
            "video_url",
            "gif_url",
            "sticker_url",
            "text_style",
            "visibility",
            "shared_from",
            "user_name",
            "user_avatar",
            "user_handle",
            "reactions_summary",
            "comments_count",
            "created_at",
        ]

    def get_user_name(self, obj):
        profile = getattr(obj.user, "profile", None)
        if profile and profile.display_name:
            return profile.display_name
        return obj.user.get_full_name() or obj.user.username

    def get_user_avatar(self, obj):
        return _avatar_url(getattr(obj.user, "profile", None), self.context.get("request"))

    def get_user_handle(self, obj):
        profile = getattr(obj.user, "profile", None)
        return profile.handle if profile else None

    def get_photo_url(self, obj):
        if obj.photo:
            req = self.context.get("request")
            return req.build_absolute_uri(obj.photo.url) if req else obj.photo.url
        return None

    def get_video_url(self, obj):
        if obj.video:
            req = self.context.get("request")
            return req.build_absolute_uri(obj.video.url) if req else obj.video.url
        return None

    def get_reactions_summary(self, obj):
        return getattr(obj, "_reactions_summary", {})

    def get_comments_count(self, obj):
        return getattr(obj, "_comments_count", 0)


class SocialPostCommentSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    user_avatar = serializers.SerializerMethodField()

    class Meta:
        model = SocialPostComment
        fields = ["id", "text", "user", "user_name", "user_avatar", "reply_to", "created_at"]

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_user_avatar(self, obj):
        return _avatar_url(getattr(obj.user, "profile", None), self.context.get("request"))


# ── Chat ─────────────────────────────────────────────────────────
class ChatConversationSerializer(serializers.ModelSerializer):
    other_user = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = ChatConversation
        fields = ["id", "other_user", "last_message", "unread_count", "created_at"]

    def get_other_user(self, obj):
        me = self.context.get("request").user
        other = obj.other_user(me)
        return UserMiniSerializer(other, context=self.context).data

    def get_last_message(self, obj):
        msg = getattr(obj, "_last_message", None)
        if msg:
            return {"text": msg.text, "created_at": msg.created_at, "sender_id": msg.sender_id}
        return None

    def get_unread_count(self, obj):
        return getattr(obj, "_unread_count", 0)


class ChatMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ["id", "text", "gif_url", "sticker_url", "sender", "sender_name", "seen", "created_at"]

    def get_sender_name(self, obj):
        return obj.sender.get_full_name() or obj.sender.username


# ── Daily Check-in ───────────────────────────────────────────────
class DailyCheckInSerializer(serializers.ModelSerializer):
    mood_emoji = serializers.CharField(read_only=True)

    class Meta:
        model = DailyCheckIn
        fields = ["id", "mood", "mood_emoji", "lunch_text", "daily_posto", "date", "created_at"]


# ── Notifications ────────────────────────────────────────────────
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationBuffer
        fields = ["id", "actor_name", "event_summary", "card", "sent", "created_at"]
