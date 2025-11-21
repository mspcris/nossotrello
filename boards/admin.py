from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import Board, Column, Card, CardLog



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
