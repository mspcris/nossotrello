# boards/models.py

from django.conf import settings
from django.db import models
from django.core.validators import RegexValidator
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
# BOARD ACTIVE OR ARQUIVED OR DELETED
# ============================================================
class ActiveBoardManager(models.Manager):
    def get_queryset(self):
        # Só quadros "vivos" e visíveis na home / navegação normal
        return super().get_queryset().filter(is_deleted=False, is_archived=False)

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
    # Soft delete (já existe no seu projeto; mantenha)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # NOVO: Arquivo
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    # Managers
    objects = ActiveBoardManager()   # uso padrão (home/normal)
    all_objects = models.Manager()   # para buscar arquivados/excluídos

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

    # ✅ convite/aceite (FORA do enum)
    invited_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

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
        return super().get_queryset().filter(is_deleted=False, is_archived=False)


# ============================================================
# CARD
# ============================================================
class Card(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="created_cards",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    tags = models.CharField(max_length=255, blank=True, null=True)
    tag_colors = models.JSONField(default=dict, blank=True)

    #+ ============================================================
    #+PRAZOS (vencimento) + DATA INÍCIO
    #+ ============================================================
    start_date = models.DateField(null=True, blank=True)   # ✅ DATA DE INÍCIO
    due_date = models.DateField(null=True, blank=True)
    due_warn_date = models.DateField(null=True, blank=True)
    due_notify = models.BooleanField(default=True)

    cover_image = models.ImageField(upload_to="card_covers/", null=True, blank=True)

    column = models.ForeignKey(Column, related_name="cards", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(blank=True, null=True)

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

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="card_logs",
    )
    reply_to = models.ForeignKey(
        "self",
        related_name="replies",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    # legado (HTML)
    content = models.TextField(blank=True, default="")

    # ✅ novo: source of truth do Quill
    content_delta = models.JSONField(blank=True, default=dict)
    content_text = models.TextField(blank=True, default="")

    attachment = models.FileField(upload_to="logs/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)


# ============================================================
# CARD BADGED
# ============================================================
class CardSeen(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("card", "user")


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
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="profile",
        on_delete=models.CASCADE,
    )

    activity_sidebar = models.BooleanField(
        default=True,
        help_text="Mostrar atividade fixa na lateral do modal do card (estilo Trello)",
    )
    
    board_col_width = models.PositiveSmallIntegerField(default=240)

    activity_counts = models.BooleanField(
        default=True,
        help_text="Mostrar contadores de atividade (comentários/itens) no modal do card",
    )

    notify_whatsapp = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=True)

    notify_only_owned_or_mentioned = models.BooleanField(default=False)



    avatar_choice = models.CharField(max_length=60, blank=True, default="")
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

    preferred_identity_label = models.CharField(
        max_length=20,
        choices=[
            ("display_name", "Nome amigável"),
            ("email", "Email"),
            ("handle", "Handle"),
        ],
        default="display_name",
        blank=True,
    )

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

    board = models.ForeignKey(
        Board,
        related_name="mentions",
        on_delete=models.CASCADE,
    )
    card = models.ForeignKey(
        Card,
        related_name="mentions",
        on_delete=models.CASCADE,
    )
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
    )

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

    # Contadores
    seen_count = models.PositiveIntegerField(default=0)
    emailed_count = models.PositiveIntegerField(default=0)

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
                fields=["card", "mentioned_user", "source"],
                name="uniq_mention_card_user_source",
            ),
        ]
        indexes = [
            models.Index(fields=["card", "mentioned_user"]),
            models.Index(fields=["board", "mentioned_user"]),
            models.Index(fields=["card", "source"]),
        ]

    def __str__(self):
        return f"{self.mentioned_user} ({self.emailed_count}/{self.seen_count}) em {self.card}"


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


from django.conf import settings

class BoardAccessRequest(models.Model):
    board = models.ForeignKey(
        "Board",
        on_delete=models.CASCADE,
        related_name="access_requests",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("board", "user")
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user.email} pediu acesso ao board {self.board.name}"



class CardNotificationLog(models.Model):
    class Kind(models.TextChoices):
        WARN = "warn", "Data aviso"
        WARN_MINUS_1 = "warn_minus_1", "Véspera do aviso"
        DUE_MINUS_1 = "due_minus_1", "Véspera do vencimento"
        DUE = "due", "Vencimento"

    card = models.ForeignKey(Card, related_name="notification_logs", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="card_notification_logs", on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    run_date = models.DateField()  # dia que o command rodou (08:00)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["card", "user", "kind", "run_date"],
                name="uniq_card_user_kind_rundate",
            ),
        ]
        indexes = [
            models.Index(fields=["run_date", "kind"]),
            models.Index(fields=["card", "kind"]),
            models.Index(fields=["user", "run_date"]),
        ]


class CardFollow(models.Model):
    card = models.ForeignKey("Card", on_delete=models.CASCADE, related_name="follows")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="card_follows")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("card", "user")
        indexes = [
            models.Index(fields=["card", "user"]),
        ]

    def __str__(self):
        return f"{self.user_id} follows {self.card_id}"

# END boards/models.py
