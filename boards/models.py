from django.db import models
from django.utils import timezone


# ============================================================
# BOARD (Quadro)
# ============================================================
class Board(models.Model):
    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to="board_covers/", null=True, blank=True)

    background_image = models.ImageField(
        upload_to="board_backgrounds/",
        null=True,
        blank=True
    )
    background_url = models.URLField(null=True, blank=True)

    def __str__(self):
        return self.name


# ============================================================
# COLUMN (Coluna)
# ============================================================
class Column(models.Model):
    board = models.ForeignKey(Board, related_name="columns", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    THEME_CHOICES = [
        ("gray", "Cinza"),
        ("blue", "Azul"),
        ("green", "Verde"),
        ("purple", "Roxo"),
        ("amber", "Bege"),
        ("red", "Vermelho"),
        ("pink", "Rosa"),
        ("teal", "Verde-água"),
        ("indigo", "Índigo"),
    ]

    theme = models.CharField(
        max_length=20,
        choices=THEME_CHOICES,
        default="gray",
    )

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"{self.board.name} - {self.name}"


# ============================================================
# CARD MANAGER (apenas ativos)
# ============================================================
class ActiveCardManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


# ============================================================
# CARD
# ============================================================
class Card(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    tags = models.CharField(max_length=255, blank=True, null=True)

    # ⚠️ REMOVIDO: attachment único
    # attachment = models.FileField(...)

    column = models.ForeignKey(Column, related_name="cards", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)

    # Lixeira
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)

    # Managers
    objects = ActiveCardManager()       # apenas ativos
    all_objects = models.Manager()      # todos (incluindo deletados)

    def __str__(self):
        return self.title


# ============================================================
# CARD LOG (atividades)
# ============================================================
class CardLog(models.Model):
    card = models.ForeignKey(Card, related_name="logs", on_delete=models.CASCADE)
    content = models.TextField(blank=True)
    attachment = models.FileField(upload_to="logs/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Log do card {self.card.id} em {self.created_at}"


# ============================================================
# CARD ATTACHMENT — múltiplos anexos por card
# ============================================================
class CardAttachment(models.Model):
    card = models.ForeignKey(Card, related_name="attachments", on_delete=models.CASCADE)
    file = models.FileField(upload_to="attachments/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Anexo do card {self.card.id}: {self.file.name}"
