from django.contrib import admin
from .models import Project, ActivityType, Team, TimeEntry


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "client_name", "git_url", "is_active")
    search_fields = ("name", "client_name")
    list_filter = ("is_active",)


@admin.register(ActivityType)
class ActivityTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name",)
    filter_horizontal = ("members",)


@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "project",
        "activity_type",
        "minutes",
        "card_id",
        "created_at",
    )
    list_filter = ("project", "activity_type", "created_at")
    search_fields = ("card_title_cache",)
