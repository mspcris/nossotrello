from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model

from .models import Board, Column, Card, CardLog, UserProfile

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
