from django.conf import settings
from django.db import models
from django.utils import timezone


# ============================================================
# ORGANIZATION (dona dos boards)
# ============================================================
class Organization(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="owned_organizations",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # slug simples a partir do nome, se não vier preenchido
        if not self.slug:
            from django.utils.text import slugify

            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


# ============================================================
# ORGANIZATION MEMBERSHIP (usuário participante da organização)
# ============================================================
class OrganizationMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    organization = models.ForeignKey(
        Organization,
        related_name="memberships",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="organization_memberships",
        on_delete=models.CASCADE,
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    home_wallpaper_filename = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        unique_together = ("organization", "user")

    def __str__(self):
        return f"{self.user} em {self.organization} ({self.role})"


# ============================================================
# BOARD (Quadro)
# ============================================================
class Board(models.Model):
    # Nova relação: organização dona do board
    organization = models.ForeignKey(
        Organization,
        related_name="boards",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    # Quem criou o board
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="created_boards",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to="board_covers/", null=True, blank=True)

    background_image = models.ImageField(
        upload_to="board_backgrounds/",
        null=True,
        blank=True,
    )
    background_url = models.URLField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    home_wallpaper_filename = models.CharField(max_length=255, blank=True, default="")


    # SOFT DELETE
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name


# ============================================================
# BOARD MEMBERSHIP (usuário com acesso ao board)
# ============================================================
class BoardMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        EDITOR = "editor", "Editor"
        VIEWER = "viewer", "Viewer"

    board = models.ForeignKey(
        Board,
        related_name="memberships",
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="board_memberships",
        on_delete=models.CASCADE,
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.EDITOR,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("board", "user")

    def __str__(self):
        return f"{self.user} em {self.board} ({self.role})"


# ============================================================
# COLUMN (Coluna)
# ============================================================
class Column(models.Model):
    board = models.ForeignKey(Board, related_name="columns", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    # Soft delete
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

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


# ============================================================
# CHECKLIST (grupo de itens por card)
# ============================================================
class Checklist(models.Model):
    card = models.ForeignKey(
        Card,
        related_name="checklists",
        on_delete=models.CASCADE,
    )
    title = models.CharField(max_length=255)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "created_at"]

    def __str__(self):
        return f"Checklist '{self.title}' do card {self.card.id}"


# ============================================================
# CHECKLIST ITEM
# ============================================================
class ChecklistItem(models.Model):
    # Mantém o vínculo direto com o card (retrocompatibilidade)
    card = models.ForeignKey(
        Card,
        related_name="checklist_items",
        on_delete=models.CASCADE,
    )

    # Novo: checklist pai
    checklist = models.ForeignKey(
        Checklist,
        related_name="items",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    text = models.CharField(max_length=255)
    is_done = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "created_at"]

    def __str__(self):
        return self.text
