from django.db import models
from django.utils import timezone


# ============================================================
# BOARD (Quadro)
# ============================================================

class Board(models.Model):
    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to="board_covers/", null=True, blank=True)

    background_image = models.ImageField(upload_to="board_backgrounds/", null=True, blank=True)
    background_url = models.URLField(null=True, blank=True)



# ============================================================
# COLUMN (Coluna)
# ============================================================

class Column(models.Model):
    board = models.ForeignKey(Board, related_name="columns", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    # TEMA DEFINIDO (para cores controladas de fundo)
    THEME_CHOICES = [
        ("gray", "Cinza"),
        ("blue", "Azul"),
        ("green", "Verde"),
        ("purple", "Roxo"),
        ("amber", "Bege"),

        # Novas cores
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

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"{self.board.name} - {self.name}"


# ============================================================
# CARD MANAGERS (ativos e deletados)
# ============================================================

class ActiveCardManager(models.Manager):
    """Manager padrão: retorna apenas cards ativos (não deletados)."""
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


# ============================================================
# CARD
# ============================================================

class Card(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    tags = models.CharField(max_length=255, blank=True, null=True)

    # ARQUIVO / IMAGEM DO CARD (aparece dentro do card)
    attachment = models.FileField(upload_to="attachments/", blank=True, null=True)

    column = models.ForeignKey(Column, related_name="cards", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)

    # LIXEIRA
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)

    # MANAGERS
    objects = ActiveCardManager()   # padrão
    all_objects = models.Manager()  # inclui deletados

    def __str__(self):
        return self.title


# ============================================================
# CARD LOG
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



background_image = models.ImageField(
    upload_to="board_wallpapers/",
    blank=True,
    null=True
)

background_url = models.URLField(
    max_length=500,
    blank=True,
    null=True
)
