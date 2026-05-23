from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model

from .models import (
    Board, Column, Card, CardLog, UserProfile, WhatsNewItem,
    BannedTerm, ModerationCase, BanLog, TermsAcceptanceLog,
)
from .services.moderation.blocklist import invalidate_cache as _invalidate_blocklist_cache

User = get_user_model()


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    fields = (
        "tracktime_limit_minutes",
        "notify_whatsapp", "notify_email",
        "notify_start_time", "notify_end_time",
        "notify_days_mon", "notify_days_tue", "notify_days_wed",
        "notify_days_thu", "notify_days_fri", "notify_days_sat", "notify_days_sun",
        "notify_offhours_accepted", "notify_offhours_accepted_at",
    )
    readonly_fields = ("notify_offhours_accepted_at",)
    verbose_name = "Perfil & Notificações"
    verbose_name_plural = "Perfil & Notificações"


class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)



@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "image", "background_image", "background_url")


@admin.register(Column)
class ColumnAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "board", "position", "theme")
    list_filter = ("board", "theme")
    search_fields = ("name",)


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "column", "position", "is_deleted")
    list_filter = ("column", "is_deleted")
    search_fields = ("title", "tags")


@admin.register(CardLog)
class CardLogAdmin(admin.ModelAdmin):
    list_display = ("id", "card", "created_at")
    search_fields = ("content",)


@admin.register(WhatsNewItem)
class WhatsNewItemAdmin(admin.ModelAdmin):
    list_display = ("id", "emoji", "title", "published_at", "is_published", "commit_hash")
    list_filter = ("is_published",)
    search_fields = ("title", "description", "commit_hash")
    date_hierarchy = "published_at"
    fields = ("emoji", "title", "description", "published_at", "is_published", "commit_hash")


@admin.register(BannedTerm)
class BannedTermAdmin(admin.ModelAdmin):
    list_display = ("term", "display", "severity", "category", "terms_clause", "active", "created_at")
    list_filter = ("severity", "category", "active")
    search_fields = ("term", "display", "notes")
    ordering = ("term",)

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        _invalidate_blocklist_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        _invalidate_blocklist_cache()


@admin.register(ModerationCase)
class ModerationCaseAdmin(admin.ModelAdmin):
    list_display = ("id", "content_kind", "author", "status", "layer1_hit", "layer2_flagged", "created_at")
    list_filter = ("status", "content_kind", "layer1_hit", "layer2_flagged")
    search_fields = ("subject_text", "author__email", "author__username", "decision_notes")
    date_hierarchy = "created_at"
    readonly_fields = (
        "content_kind", "object_id", "author", "subject_text",
        "layer1_hit", "layer1_term", "layer2_provider", "layer2_scores",
        "layer2_categories", "layer2_flagged", "layer2_at", "created_at",
    )


@admin.register(BanLog)
class BanLogAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "action", "terms_clause", "applied_by", "applied_at", "revoked_at")
    list_filter = ("action",)
    search_fields = ("user__email", "user__username", "reason", "terms_clause")
    date_hierarchy = "applied_at"
    readonly_fields = (
        "user", "action", "case", "reason", "terms_clause",
        "applied_by", "applied_at", "effective_until", "email_sent_at",
    )


@admin.register(TermsAcceptanceLog)
class TermsAcceptanceLogAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "version", "accepted_at", "ip_address", "cookies_accepted")
    list_filter = ("version", "cookies_accepted")
    search_fields = ("user__email", "user__username", "ip_address")
    date_hierarchy = "accepted_at"
    readonly_fields = ("user", "version", "accepted_at", "ip_address", "user_agent", "cookies_accepted")
