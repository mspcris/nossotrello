# boards/models.py

from django.conf import settings
from django.db import models
from django.core.validators import RegexValidator


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
    home_wallpaper_filename = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


# ============================================================
# ORGANIZATION MEMBERSHIP
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

    class Meta:
        unique_together = ("organization", "user")

    def __str__(self):
        return f"{self.user} em {self.organization} ({self.role})"


# ============================================================
# BOARD
# ============================================================
class Board(models.Model):
    organization = models.ForeignKey(
        Organization,
        related_name="boards",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="created_boards",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    name = models.CharField(max_length=255)

    # controle de versão para polling/sync
    version = models.PositiveIntegerField(default=0)

    #+ ============================================================
    #+ PRAZOS (cores do badge por board)
    #+ ============================================================
    due_colors = models.JSONField(
        default=dict,
        blank=True,
        help_text="Cores do prazo: {'ok':'#..','warn':'#..','overdue':'#..'}",
    )


    image = models.ImageField(upload_to="board_covers/", null=True, blank=True)

    background_image = models.ImageField(
        upload_to="board_backgrounds/",
        null=True,
        blank=True,
    )
    background_url = models.URLField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # soft delete
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # legado
    home_wallpaper_filename = models.CharField(max_length=255, blank=True, default="")

    # coluna de agragacao
    show_aggregator_column = models.BooleanField(default=False)

    def __str__(self):
        return self.name


# ============================================================
# BOARD MEMBERSHIP
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
# COLUMN
# ============================================================
class Column(models.Model):
    board = models.ForeignKey(Board, related_name="columns", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

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
# CARD MANAGER
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
    tag_colors = models.JSONField(default=dict, blank=True)


    #+ ============================================================
    #+PRAZOS (vencimento)
    #+ ============================================================
    due_date = models.DateField(null=True, blank=True)
    due_warn_date = models.DateField(null=True, blank=True)
    due_notify = models.BooleanField(default=True)


    cover_image = models.ImageField(upload_to="card_covers/", null=True, blank=True)

    column = models.ForeignKey(Column, related_name="cards", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)

    objects = ActiveCardManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["position", "id"]

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


# ============================================================
# CARD ATTACHMENT
# ============================================================
class CardAttachment(models.Model):
    card = models.ForeignKey(Card, related_name="attachments", on_delete=models.CASCADE)
    file = models.FileField(upload_to="attachments/")
    description = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Anexo do card {self.card.id}: {self.file.name}"


# ============================================================
# CHECKLIST
# ============================================================
class Checklist(models.Model):
    card = models.ForeignKey(Card, related_name="checklists", on_delete=models.CASCADE)
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
    card = models.ForeignKey(
        Card,
        related_name="checklist_items",
        on_delete=models.CASCADE,
    )
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


# ============================================================
# USER PROFILE
# ============================================================
class UserProfile(models.Model):
    avatar_choice = models.CharField(max_length=60, blank=True, default="")
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="profile",
        on_delete=models.CASCADE,
    )

    display_name = models.CharField(max_length=120, blank=True, default="")
    handle = models.CharField(
        max_length=40,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^[a-z0-9_\.]+$",
                message="Use apenas letras minúsculas, números, _ ou .",
            )
        ],
        blank=True,
        null=True,
    )

    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)

    posto = models.CharField(max_length=120, blank=True, default="")
    setor = models.CharField(max_length=120, blank=True, default="")
    ramal = models.CharField(max_length=20, blank=True, default="")
    telefone = models.CharField(max_length=30, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["handle"]),
        ]

    def __str__(self):
        return self.handle or self.display_name or str(self.user)


# ============================================================
# MENTIONS
# ============================================================
class Mention(models.Model):
    class Source(models.TextChoices):
        ACTIVITY = "activity", "Atividade"
        DESCRIPTION = "description", "Descrição"

    board = models.ForeignKey(Board, related_name="mentions", on_delete=models.CASCADE)
    card = models.ForeignKey(Card, related_name="mentions", on_delete=models.CASCADE)

    source = models.CharField(max_length=20, choices=Source.choices)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="mentions_made",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    mentioned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="mentions_received",
        on_delete=models.CASCADE,
    )

    raw_text = models.TextField(blank=True, default="")
    card_log = models.ForeignKey(
        CardLog,
        related_name="mentions",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["card", "mentioned_user", "source", "card_log"],
                name="uniq_mention_per_card_user_source_log",
            )
        ]
        indexes = [
            models.Index(fields=["card", "mentioned_user"]),
            models.Index(fields=["board", "mentioned_user"]),
        ]

    def __str__(self):
        return f"{self.mentioned_user} mencionado em {self.card} ({self.source})"


    # ============================================================
    # PRAZOS (cores do badge por board)
    # ============================================================
    due_colors = models.JSONField(
        default=dict,
        blank=True,
        help_text="Cores do prazo: {'ok':'#..','warn':'#..','overdue':'#..'}",
    )


# ============================================================
# HOME GROUPS (agrupamentos pessoais de quadros)
# ============================================================

class BoardGroup(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="board_groups",
        on_delete=models.CASCADE,
    )

    organization = models.ForeignKey(
        Organization,
        related_name="board_groups",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    name = models.CharField(max_length=120, default="", blank=True)
    position = models.PositiveIntegerField(default=0)

    # Favoritos é um grupo especial (1 por usuário/org)
    is_favorites = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        indexes = [
            models.Index(fields=["user", "organization", "position"]),
            models.Index(fields=["user", "organization", "is_favorites"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.user})"


class BoardGroupItem(models.Model):
    group = models.ForeignKey(
        BoardGroup,
        related_name="items",
        on_delete=models.CASCADE,
    )
    board = models.ForeignKey(
        Board,
        related_name="group_items",
        on_delete=models.CASCADE,
    )
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["group", "board"], name="uniq_group_board"),
        ]
        indexes = [
            models.Index(fields=["group", "position"]),
            models.Index(fields=["board"]),
        ]

    def __str__(self):
        return f"{self.board} em {self.group}"


# ============================================================
# BOARD ACTIVITY READ STATE (lido/não lido do Histórico do quadro)
# ============================================================
class BoardActivityReadState(models.Model):
    board = models.ForeignKey(Board, related_name="read_states", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="board_read_states", on_delete=models.CASCADE)

    # Tudo acima disso é considerado "lido"
    last_seen_at = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("board", "user")
        indexes = [
            models.Index(fields=["board", "user"]),
            models.Index(fields=["board", "last_seen_at"]),
        ]

    def __str__(self):
        return f"{self.user} leu {self.board} até {self.last_seen_at}"
