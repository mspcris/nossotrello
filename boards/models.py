# boards/models.py

import uuid

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
            base = slugify(self.name) or "workspace"
            slug = base
            n = 2
            while Organization.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
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
    background_color = models.CharField(max_length=9, blank=True, default="")  # cor estática de fundo (hex)

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

    # ---- Auto-ordenação agendada (Trello-like) ----
    AUTOSORT_FREQ_CHOICES = [
        ("none", "Não ordenar automaticamente"),
        ("daily", "Todo dia"),
        ("weekly", "Toda semana"),
    ]
    AUTOSORT_FIELD_CHOICES = [
        ("due", "Data de entrega"),
        ("start", "Data de início"),
        ("created", "Data de criação"),
        ("title", "Nome (A→Z)"),
    ]
    autosort_freq = models.CharField(max_length=10, choices=AUTOSORT_FREQ_CHOICES, default="none")
    autosort_field = models.CharField(max_length=10, choices=AUTOSORT_FIELD_CHOICES, default="due")
    autosort_dir = models.CharField(
        max_length=4, choices=[("asc", "Crescente"), ("desc", "Decrescente")], default="asc"
    )
    autosort_weekday = models.PositiveSmallIntegerField(default=0)  # 0=segunda (p/ weekly)
    autosort_hour = models.PositiveSmallIntegerField(default=6)     # horário do disparo (hora local)
    autosort_minute = models.PositiveSmallIntegerField(default=0)
    autosort_last_run = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["position"]
        indexes = [
            models.Index(fields=["board", "is_deleted"], name="col_board_deleted_idx"),
            models.Index(fields=["board", "position"], name="col_board_position_idx"),
        ]

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
    cover_color = models.CharField(max_length=9, blank=True, default="")  # cor estática de capa (hex)

    # ---- Card contador (mostra um número grande, atualizado sozinho) ----
    COUNTER_MODE_CHOICES = [
        ("entered_recent", "Entraram na lista nos últimos X dias"),
        ("total", "Total de cards na lista"),
        ("done_recent", "Entregues nos últimos X dias"),
        ("delivered", "Entregues (total)"),
        ("not_delivered", "Não entregues"),
        ("overdue", "Com prazo vencido"),
        ("stale", "Parados há X+ dias"),
    ]
    counter_mode = models.CharField(max_length=20, blank=True, default="")  # "" = card normal
    counter_days = models.PositiveSmallIntegerField(default=15)

    column = models.ForeignKey(Column, related_name="cards", on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)
    # quando o card entrou na coluna atual (p/ automação "parado X dias")
    column_since = models.DateTimeField(null=True, blank=True)
    # quem colocou o card na coluna ATUAL (último a mover/criar aqui).
    # Usado pela automação "avisar quem colocou o card" quando ele sai da lista.
    column_entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(blank=True, null=True)

    is_delivered = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cards_delivered",
    )

    objects = ActiveCardManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ["position", "id"]
        indexes = [
            models.Index(fields=["column", "is_deleted"], name="card_col_deleted_idx"),
            models.Index(fields=["column", "position"], name="card_col_position_idx"),
            models.Index(fields=["due_date"], name="card_due_date_idx"),
        ]

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
    attachment_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["card", "created_at"], name="cardlog_card_created_idx"),
            models.Index(fields=["actor", "created_at"], name="cardlog_actor_created_idx"),
        ]


# ============================================================
# CARD SECRET (snippet/segredo criptografado)
# ============================================================
class CardSecret(models.Model):
    """
    Snippet/segredo de card (ex.: um `curl` com chave de API) criptografado em
    repouso com Fernet — ver boards/services/secret_crypto.py.

    Política de acesso ESTRITA: só o autor e os `viewers` marcados podem
    revelar o conteúdo. A validação é sempre feita no servidor; o template
    nunca recebe o plaintext de quem não pode ver.

    Soft-delete via `is_active` (regra do projeto — nunca delete físico).
    """
    card = models.ForeignKey(Card, related_name="secrets", on_delete=models.CASCADE)

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="authored_card_secrets",
    )

    title = models.CharField(max_length=200, blank=True, default="")

    # ciphertext Fernet (bytes). NUNCA gravar plaintext aqui.
    ciphertext = models.BinaryField()

    # dica de linguagem só pra rótulo/realce (curl, bash, json, ...). Cosmético.
    lang = models.CharField(max_length=20, blank=True, default="curl")

    # quem você marcou como autorizado a revelar
    viewers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="visible_card_secrets",
        blank=True,
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["card", "is_active", "created_at"],
                name="cardsecret_card_idx",
            ),
        ]

    def __str__(self):
        return f"Segredo #{self.pk} de {self.card_id}"

    def can_reveal(self, user) -> bool:
        """Regra estrita: SÓ autor ou viewer marcado — nem superuser revela."""
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if self.author_id and self.author_id == user.id:
            return True
        return self.viewers.filter(id=user.id).exists()


class CardSecretReveal(models.Model):
    """Auditoria: quem revelou qual segredo e quando (accountability)."""
    secret = models.ForeignKey(
        CardSecret, related_name="reveals", on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    revealed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["secret", "revealed_at"], name="cardsecretreveal_idx"
            ),
        ]


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
    description = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="attachments_created",
    )
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

    camim_sub = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Identificador imutável do usuário no IDCamim (OAuth sub). "
                  "Usado para casar o login mesmo que o email mude.",
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

    class CardModalTheme(models.TextChoices):
        GLASS = "glass", "Claro"
        DARK = "dark", "Escuro"

    card_modal_theme = models.CharField(
        max_length=10,
        choices=CardModalTheme.choices,
        default=CardModalTheme.GLASS,
        help_text="Tema do modal do card (claro/escuro). Vale para todos os cards do usuário.",
    )

    notify_whatsapp = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=True)
    notify_social = models.BooleanField(default=True)

    # Bit de privacidade: publicar no feed social o que é feito no Tarefas
    # (curtir card / compartilhar quadro). Marcado = continua publicando;
    # desmarcado = nada do Tarefas vai pra rede social e os "curtiu um card"
    # já existentes deste usuário somem do reel. Todos nascem marcados.
    share_tarefas_to_social = models.BooleanField(default=True)

    notify_only_owned_or_mentioned = models.BooleanField(default=False)

    unidade = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Unidade/setor onde trabalha — usado para sugestões de amigos",
    )

    tag_catalog = models.JSONField(
        default=dict,
        blank=True,
        help_text="Catálogo de etiquetas do usuário, por board, com cor"
    )

    code_block_style = models.JSONField(
        default=dict,
        blank=True,
        help_text="Cor do bloco de código do usuário: {bg, fg}. Vale só para "
                  "blocos criados daqui pra frente (a cor é gravada em cada bloco "
                  "novo); os antigos não mudam.",
    )



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

    # Flags de compartilhamento social (o que aparece no perfil público)
    share_posto = models.BooleanField(default=True)
    share_setor = models.BooleanField(default=True)
    share_ramal = models.BooleanField(default=False)
    share_telefone = models.BooleanField(default=False)

    # Capa do perfil social
    cover_photo = models.ImageField(upload_to="covers/", blank=True, null=True)

    # Posto fixo (se sempre vai ao mesmo, não pergunta todo dia)
    fixed_posto = models.BooleanField(default=False)

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

    

    # Track-time: limite por usuário (minutos até pedir confirmação)
    # 0 = usa o padrão do sistema (60 min confirmação, 75 min auto-stop)
    tracktime_limit_minutes = models.PositiveIntegerField(
        default=0,
        help_text="Tempo em minutos até pedir confirmação do timer. "
                  "0 = padrão do sistema (60 min).",
    )

    # ── Agenda de notificações ──
    notify_start_time = models.TimeField(
        default="08:00",
        help_text="Hora de início para receber notificações.",
    )
    notify_end_time = models.TimeField(
        default="17:00",
        help_text="Hora de fim para receber notificações.",
    )
    notify_days_mon = models.BooleanField(default=True)
    notify_days_tue = models.BooleanField(default=True)
    notify_days_wed = models.BooleanField(default=True)
    notify_days_thu = models.BooleanField(default=True)
    notify_days_fri = models.BooleanField(default=True)
    notify_days_sat = models.BooleanField(default=False)
    notify_days_sun = models.BooleanField(default=False)
    # Aceite de trabalho fora do horário padrão
    notify_offhours_accepted = models.BooleanField(default=False)
    notify_offhours_accepted_at = models.DateTimeField(null=True, blank=True)

    # Aceite dos Termos de Uso e Política de Privacidade
    terms_accepted = models.BooleanField(default=False)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.CharField(max_length=10, default="1.0", blank=True)

    # Onboarding tour concluído (rede social)
    onboarding_done = models.BooleanField(default=False)

    # Onboarding da home de quadros concluído (sample board + modal de boas-vindas)
    boards_onboarding_done = models.BooleanField(default=False)

    # Última vez que o usuário abriu o painel "Novidades" (What's new)
    last_whatsnew_seen_at = models.DateTimeField(null=True, blank=True)

    # ── Moderação social ──
    # social_blocked: usuário não pode publicar/comentar/usar chat. account_blocked:
    # nem pode logar localmente. idcamim_blocked: pedido de desativação no IDCamim
    # já foi feito (registro local, fonte de verdade é o IDCamim).
    social_blocked = models.BooleanField(default=False)
    social_blocked_until = models.DateTimeField(null=True, blank=True)
    social_blocked_reason = models.CharField(max_length=240, blank=True, default="")
    account_blocked = models.BooleanField(default=False)
    account_blocked_until = models.DateTimeField(null=True, blank=True)
    idcamim_blocked = models.BooleanField(default=False)
    idcamim_blocked_at = models.DateTimeField(null=True, blank=True)
    social_warn_count = models.PositiveIntegerField(default=0)
    social_block_count = models.PositiveIntegerField(default=0)
    last_offense_at = models.DateTimeField(null=True, blank=True)

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


class BoardOwnershipTransfer(models.Model):
    """Transferência de titularidade pendente de aceite do destinatário.

    Enquanto status=PENDING nada muda: o from_user continua OWNER. A troca de
    papéis só acontece no aceite. Diferente de BoardAccessRequest (que deleta a
    linha ao resolver), aqui o histórico é preservado — quem passou a
    titularidade de um quadro, pra quem e quando é dado de auditoria.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        ACCEPTED = "accepted", "Aceita"
        DECLINED = "declined", "Recusada"
        CANCELLED = "cancelled", "Cancelada"

    board = models.ForeignKey(
        "Board",
        on_delete=models.CASCADE,
        related_name="ownership_transfers",
    )
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ownership_transfers_sent",
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ownership_transfers_received",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["board"],
                condition=models.Q(status="pending"),
                name="uniq_pending_ownership_transfer_per_board",
            ),
        ]

    def __str__(self):
        return (
            f"{self.from_user} → {self.to_user} "
            f"({self.board.name}, {self.get_status_display()})"
        )


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


class NotificationBuffer(models.Model):
    """
    Buffer de notificações de atividade em cards.
    Acumula eventos por card+usuário e envia consolidado a cada 5 min.
    """
    card = models.ForeignKey("Card", on_delete=models.CASCADE, related_name="notification_buffer")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_buffer")
    actor_name = models.CharField(max_length=200, default="")
    event_summary = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    sent = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["sent", "created_at"]),
            models.Index(fields=["card", "recipient", "sent"]),
        ]

    def __str__(self):
        return f"buf:{self.card_id}→{self.recipient_id} [{self.event_summary[:40]}]"


class ColumnFollow(models.Model):
    column = models.ForeignKey("boards.Column", on_delete=models.CASCADE, related_name="follows")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="column_follows")
    include_new = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("column", "user"),)
        indexes = [
            models.Index(fields=["column", "include_new"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self):
        return f"{self.user_id} -> column {self.column_id} (include_new={self.include_new})"



class UserBoardPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    activity_filter = models.CharField(
        max_length=20,
        default="comments",
        choices=[
            ("comments", "Comentários"),
            ("files", "Arquivos"),
            ("system", "Sistema"),
            ("all", "Tudo"),
        ],
    )

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Prefs {self.user}"


# ============================================================
# SOCIAL (scrapbook / mood / chatbot)
# ============================================================
class SocialPost(models.Model):
    VISIBILITY_ALL = "all"
    VISIBILITY_FRIENDS = "friends"
    VISIBILITY_CHOICES = [
        ("all", "Todos"),
        ("friends", "Apenas amigos"),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="social_posts",
        on_delete=models.CASCADE,
    )
    text = models.TextField(blank=True, default="")
    photo = models.ImageField(upload_to="social/", blank=True, null=True)
    video = models.FileField(upload_to="social/videos/", blank=True, null=True)
    # Poster (1º frame) gerado por ffmpeg pra <video poster=...> — usuário
    # vê algo instantâneo enquanto o vídeo carrega.
    video_poster = models.ImageField(upload_to="social/posters/", blank=True, null=True)
    gif_url = models.URLField(blank=True, default="")
    sticker_url = models.URLField(blank=True, default="")
    text_style = models.JSONField(blank=True, null=True, default=None)
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default="all")
    shared_from = models.ForeignKey(
        "self", null=True, blank=True, related_name="reposts",
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    # Quando preenchido, indica que a foto deste post foi gerada por IA a
    # partir de um texto que foi reconhecido como prato (ex: "Strogonoff").
    # Usado para cota (1/dia/usuário) e auditoria.
    ai_food_dish = models.CharField(max_length=120, blank=True, default="")

    # Mood post: quando vem do daily_checkin_save, grava o mood code e a
    # variante (1..N) do Camilinho que foi sorteada — pra renderizar a mesma
    # imagem sempre, e pro front saber qual asset buscar.
    mood_code = models.CharField(max_length=16, blank=True, default="", db_index=True)
    camilinho_variant = models.PositiveSmallIntegerField(default=0)

    MOD_CLEAN = "clean"
    MOD_PENDING = "pending_review"
    MOD_BLOCKED = "blocked"
    MOD_REMOVED = "removed_by_moderator"
    MOD_CHOICES = [
        (MOD_CLEAN, "Liberado"),
        (MOD_PENDING, "Em análise"),
        (MOD_BLOCKED, "Bloqueado pela política"),
        (MOD_REMOVED, "Removido por moderador"),
    ]
    moderation_status = models.CharField(
        max_length=24, choices=MOD_CHOICES, default=MOD_CLEAN, db_index=True,
    )
    moderation_reason = models.CharField(max_length=160, blank=True, default="")
    moderation_clause = models.CharField(max_length=20, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["moderation_status", "-created_at"]),
        ]

    @property
    def has_media(self):
        return bool(self.photo) or bool(self.video)

    @property
    def camilinho_url(self):
        """URL static da imagem do mascote (modo individual PNG — legado/fallback)."""
        if not self.mood_code or not self.camilinho_variant:
            return ""
        from boards.services.camilinho import image_url
        return image_url(self.mood_code, self.camilinho_variant)

    @property
    def camilinho_sprite_class(self):
        """CSS class pra div renderizar via sprite WebP (preferido)."""
        if not self.mood_code or not self.camilinho_variant:
            return ""
        from boards.services.camilinho import sprite_class
        return sprite_class(self.mood_code, self.camilinho_variant)

    @property
    def camilinho_anim_class(self):
        if not self.mood_code:
            return ""
        from boards.services.camilinho import animation_class
        return animation_class(self.mood_code)

    def __str__(self):
        return f"{self.user} — {self.created_at:%Y-%m-%d}"


class SocialPostVersion(models.Model):
    """Histórico de edições — nunca apagar. Invisível para o usuário."""
    post = models.ForeignKey(
        SocialPost, related_name="versions", on_delete=models.CASCADE,
    )
    text = models.TextField(blank=True, default="")
    photo = models.ImageField(upload_to="social/versions/", blank=True, null=True)
    video = models.FileField(upload_to="social/versions/videos/", blank=True, null=True)
    gif_url = models.URLField(blank=True, default="")
    sticker_url = models.URLField(blank=True, default="")
    visibility = models.CharField(max_length=10, default="all")
    edited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-edited_at"]

    def __str__(self):
        return f"v{self.pk} of post {self.post_id} @ {self.edited_at:%Y-%m-%d %H:%M}"


class SocialPostSeen(models.Model):
    """Rastreia quando viewer viu os posts de target_user pela última vez (para o efeito de aura)."""
    viewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="social_seen",
        on_delete=models.CASCADE,
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="social_seen_by",
        on_delete=models.CASCADE,
    )
    last_seen_post_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("viewer", "target_user")
        indexes = [
            models.Index(fields=["viewer", "target_user"]),
        ]

    def __str__(self):
        return f"{self.viewer} viu posts de {self.target_user} até {self.last_seen_post_at}"


class SocialPostView(models.Model):
    """Registra quem visualizou cada post individual."""
    SOURCE_CHOICES = [
        ("profile", "Perfil"),
        ("feed", "Feed/Novidades"),
    ]
    post = models.ForeignKey(SocialPost, related_name="views", on_delete=models.CASCADE)
    viewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="social_post_views", on_delete=models.CASCADE,
    )
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="profile")
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("post", "viewer", "source")
        indexes = [
            models.Index(fields=["post", "viewer"]),
            models.Index(fields=["post", "source"]),
        ]

    def __str__(self):
        return f"{self.viewer} viu post {self.post_id} ({self.source})"


# ============================================================
# REACTIONS & COMMENTS em posts
# ============================================================
class SocialPostReaction(models.Model):
    REACTION_CHOICES = [
        ("like", "👍"),
        ("love", "❤️"),
        ("haha", "😂"),
        ("fire", "🔥"),
        ("clap", "👏"),
    ]
    PRESET_EMOJIS = dict(REACTION_CHOICES)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="social_reactions",
        on_delete=models.CASCADE,
    )
    post = models.ForeignKey(SocialPost, related_name="reactions", on_delete=models.CASCADE)
    reaction = models.CharField(max_length=16)  # preset key OR emoji character
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "post")

    @property
    def emoji(self):
        return self.PRESET_EMOJIS.get(self.reaction, self.reaction)

    def __str__(self):
        return f"{self.user} → {self.emoji} em post {self.post_id}"


class SocialPostComment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="social_comments",
        on_delete=models.CASCADE,
    )
    post = models.ForeignKey(SocialPost, related_name="comments", on_delete=models.CASCADE)
    text = models.TextField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    seen_by_owner = models.BooleanField(default=False)
    # Resposta a outro comentário
    reply_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replies",
    )
    # True quando o autor do comentário-pai viu esta resposta
    reply_seen = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.user} comentou em post {self.post_id}"


class SocialCommentReaction(models.Model):
    REACTION_CHOICES = [
        ("like", "👍"),
        ("love", "❤️"),
        ("haha", "😂"),
        ("fire", "🔥"),
        ("clap", "👏"),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="comment_reactions",
        on_delete=models.CASCADE,
    )
    comment = models.ForeignKey(
        SocialPostComment,
        related_name="reactions",
        on_delete=models.CASCADE,
    )
    reaction = models.CharField(max_length=10, choices=REACTION_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "comment")

    def __str__(self):
        return f"{self.user} → {self.get_reaction_display()} em comment {self.comment_id}"


# ============================================================
# DAILY CHECK-IN (humor, almoço, posto do dia)
# ============================================================
class DailyCheckIn(models.Model):
    MOOD_CHOICES = [
        ("excited", "Animado"),
        ("happy", "Bem"),
        ("calm", "Tranquilo"),
        ("neutral", "Normal"),
        ("tired", "Cansado"),
        ("stressed", "Estressado"),
        ("sick", "Indisposto"),
        ("sad", "Triste"),
        ("down", "Desanimado"),
        ("anxious", "Ansioso"),
        ("angry", "Com raiva"),
        ("inlove", "Apaixonado"),
        ("grateful", "Grato"),
    ]
    MOOD_EMOJIS = {
        "excited": "\U0001f929",   # 🤩
        "happy": "\U0001f60a",     # 😊
        "calm": "\U0001f60c",      # 😌
        "neutral": "\U0001f610",   # 😐
        "tired": "\U0001f614",     # 😔
        "stressed": "\U0001f624",  # 😤
        "sick": "\U0001f912",      # 🤒
        "sad": "\U0001f622",       # 😢
        "down": "\U0001f61e",      # 😞
        "anxious": "\U0001f630",   # 😰
        "angry": "\U0001f621",     # 😡
        "inlove": "\U0001f60d",    # 😍
        "grateful": "\U0001f64f",  # 🙏
    }

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="daily_checkins",
        on_delete=models.CASCADE,
    )
    date = models.DateField()

    mood = models.CharField(max_length=20, choices=MOOD_CHOICES, blank=True, default="")
    mood_note = models.CharField(max_length=300, blank=True, default="")

    lunch_text = models.CharField(max_length=200, blank=True, default="")
    lunch_photo = models.ImageField(upload_to="social/lunch/", blank=True, null=True)

    daily_posto = models.CharField(max_length=120, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "date")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["user", "-date"]),
        ]

    @property
    def mood_emoji(self):
        return self.MOOD_EMOJIS.get(self.mood, "")

    @property
    def mood_label(self):
        return dict(self.MOOD_CHOICES).get(self.mood, "")

    def __str__(self):
        return f"{self.user} — {self.date} — {self.mood_emoji} {self.mood_label}"

# ============================================================
# CAMILA.AI — Base de conhecimento
# ============================================================
class CamilaKnowledge(models.Model):
    CATEGORY_CHOICES = [
        ("about", "Sobre a CAMIM"),
        ("services", "Serviços e Produtos"),
        ("rules", "Regras e Políticas"),
        ("processes", "Processos Internos"),
        ("faq", "Perguntas Frequentes"),
        ("contacts", "Contatos e Endereços"),
        ("culture", "Cultura e Valores"),
        ("other", "Outros"),
    ]
    title = models.CharField(max_length=500)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="about")
    content = models.TextField(help_text="Conteúdo que a Camila deve saber")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "title"]
        verbose_name = "Camila — Conhecimento"
        verbose_name_plural = "Camila — Base de Conhecimento"

    def __str__(self):
        return f"[{self.get_category_display()}] {self.title}"


class CamilaConfig(models.Model):
    """Configuração singleton da Camila.AI — gerenciável pela interface."""
    MODEL_CHOICES = [
        ("openai/gpt-oss-20b", "GPT-OSS 20B (rápido)"),
        ("openai/gpt-oss-120b", "GPT-OSS 120B (potente)"),
        ("llama-3.3-70b-versatile", "Llama 3.3 70B"),
        ("llama-3.1-8b-instant", "Llama 3.1 8B"),
        ("llama3-70b-8192", "Llama 3 70B"),
        ("mixtral-8x7b-32768", "Mixtral 8x7B"),
    ]

    # Prompts
    prompt_react = models.TextField(
        verbose_name="Prompt — Reação a ações",
        default=(
            "Você é Camila, a IA simpática da rede social de trabalho da CAMIM. "
            "O colega acabou de compartilhar algo na rede. Faça um comentário CURTO "
            "(1-2 frases no máximo), divertido, engajador e caloroso. Use emojis. "
            "Se ele falou o que vai almoçar, comente sobre a comida de forma "
            "descontraída. Se falou o humor, acolha. Se postou algo, incentive. "
            "Seja leve, profissional e NUNCA chata. Português brasileiro."
        ),
    )
    prompt_chat = models.TextField(
        verbose_name="Prompt — Chat conversacional",
        default=(
            "Você é Camila, a IA simpática e inteligente da rede social de trabalho da CAMIM. "
            "Você é uma assistente conversacional. Os colaboradores podem falar com você "
            "sobre qualquer assunto: trabalho, dúvidas, desabafos, ideias, piadas, "
            "curiosidades, dicas de produtividade, etc. "
            "Seja calorosa, divertida, use emojis com moderação e mantenha um tom "
            "profissional mas descontraído. Respostas curtas e diretas (máx 3 parágrafos). "
            "Se perceber sofrimento intenso, sugira buscar apoio profissional. "
            "Português brasileiro. Nunca diagnostique doenças. "
            "Use a base de conhecimento abaixo para responder perguntas sobre a CAMIM "
            "quando relevante. Se não souber, diga que não tem essa informação ainda."
        ),
    )
    prompt_coach = models.TextField(
        verbose_name="Prompt — Camilo (coach)",
        default=(
            "Você é Camilo, um coach de bem-estar gentil e prático. "
            "Seu foco é motivação, hábitos saudáveis e saúde mental. "
            "Converse de forma leve, positiva e acolhedora. "
            "Nunca diagnostique doenças. Se perceber sofrimento intenso, "
            "sugira buscar apoio profissional. "
            "Respostas curtas e diretas (máximo 3 parágrafos). Português brasileiro."
        ),
    )

    # Parâmetros do modelo
    model = models.CharField(max_length=60, choices=MODEL_CHOICES, default="openai/gpt-oss-20b")
    temperature = models.FloatField(default=0.8)
    max_tokens = models.IntegerField(default=500)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Camila — Configuração"
        verbose_name_plural = "Camila — Configuração"

    def __str__(self):
        return f"Camila Config (model={self.model}, temp={self.temperature})"

    @classmethod
    def get(cls):
        """Retorna a config singleton (cria se não existir)."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SocialCardDismiss(models.Model):
    """Registra que o usuário ocultou um card das pendências sociais naquele dia."""
    user         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_dismissed_cards")
    card_id      = models.IntegerField()
    dismissed_on = models.DateField()

    class Meta:
        unique_together = [("user", "card_id", "dismissed_on")]

    def __str__(self):
        return f"{self.user} ocultou card {self.card_id} em {self.dismissed_on}"


class SocialFriendship(models.Model):
    """Convite/amizade explícita entre dois usuários."""
    STATUS_PENDING  = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_CHOICES  = [
        ("pending",  "Pendente"),
        ("accepted", "Amigos"),
    ]
    requester  = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="sent_friendships",     on_delete=models.CASCADE)
    receiver   = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="received_friendships", on_delete=models.CASCADE)
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("requester", "receiver")]
        verbose_name = "Amizade Social"

    def __str__(self):
        return f"{self.requester} → {self.receiver} ({self.status})"


# ============================================================
# CHAT DIRETO ENTRE AMIGOS
# ============================================================
class ChatConversation(models.Model):
    """Conversa 1:1 entre dois amigos."""
    user_a = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="chats_as_a", on_delete=models.CASCADE,
    )
    user_b = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="chats_as_b", on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Soft-delete / arquivamento por usuario (nada e apagado de verdade)
    archived_by_a = models.BooleanField(default=False)
    archived_by_b = models.BooleanField(default=False)
    deleted_by_a = models.BooleanField(default=False)
    deleted_by_b = models.BooleanField(default=False)

    class Meta:
        unique_together = [("user_a", "user_b")]
        ordering = ["-updated_at"]

    def other_user(self, me):
        return self.user_b if self.user_a_id == me.id else self.user_a

    def __str__(self):
        return f"Chat: {self.user_a} ↔ {self.user_b}"


class ChatMessage(models.Model):
    """Mensagem individual em uma conversa."""
    conversation = models.ForeignKey(
        ChatConversation, related_name="messages", on_delete=models.CASCADE,
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="chat_messages_sent", on_delete=models.CASCADE,
    )
    text = models.TextField(blank=True, default="")
    gif_url = models.URLField(blank=True, default="")
    sticker_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    # Soft delete individual: quem apagou só para si
    hidden_by_a = models.BooleanField(default=False)
    hidden_by_b = models.BooleanField(default=False)
    seen = models.BooleanField(default=False)
    notified = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self):
        return f"{self.sender} → msg em {self.conversation_id}"


class ChatSticker(models.Model):
    """Figurinha personalizada criada pelo usuário."""
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="chat_stickers", on_delete=models.CASCADE,
    )
    image = models.FileField(upload_to="chat/stickers/%Y/%m/")
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Sticker {self.id} by {self.owner_id}"


class CamilaPOP(models.Model):
    """POP — Procedimento Operacional Padrão armazenado como PDF."""
    title = models.CharField(max_length=500)
    code = models.CharField(max_length=50, blank=True, default="")
    category = models.CharField(max_length=100, blank=True, default="", verbose_name="Setor/Categoria")
    pdf_file = models.FileField(upload_to="camila/pops/")
    raw_text = models.TextField(blank=True, default="", verbose_name="Texto completo extraído do PDF")
    extracted_text = models.TextField(blank=True, default="", verbose_name="Resumo inteligente (IA)")
    is_active = models.BooleanField(default=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "code", "title"]
        verbose_name = "Camila — POP"
        verbose_name_plural = "Camila — POPs"

    def __str__(self):
        prefix = f"[{self.code}] " if self.code else ""
        cat = f"({self.category}) " if self.category else ""
        return f"{cat}{prefix}{self.title}"


class TermsAcceptanceLog(models.Model):
    """Registro imutável de cada aceite de termos — auditoria/compliance."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="terms_acceptance_logs",
    )
    version = models.CharField(max_length=10)
    accepted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    cookies_accepted = models.BooleanField(default=False)

    class Meta:
        ordering = ["-accepted_at"]
        verbose_name = "Aceite de Termos (log)"
        verbose_name_plural = "Aceites de Termos (log)"

    def __str__(self):
        return f"{self.user} v{self.version} @ {self.accepted_at}"


# ============================================================
# CARD MOVE HISTORY (sugestões de "Mover rápido")
# ============================================================
class CardMoveHistory(models.Model):
    """
    Registra cada movimentação entre colunas para aprender os
    padrões de cada usuário e sugerir atalhos de movimentação.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="card_moves",
    )
    from_column = models.ForeignKey(
        Column,
        on_delete=models.CASCADE,
        related_name="+",
    )
    to_column = models.ForeignKey(
        Column,
        on_delete=models.CASCADE,
        related_name="+",
    )
    from_board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="+",
    )
    to_board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["user", "from_column"],
                name="cmh_user_from_col_idx",
            ),
        ]
        verbose_name = "Histórico de movimentação"
        verbose_name_plural = "Históricos de movimentação"

    def __str__(self):
        return (
            f"{self.user} moveu de {self.from_column} "
            f"para {self.to_column}"
        )


# ============================================================
# HEALTH CHAT (Saúde e Bem Estar)
# ============================================================
class HealthChatMessage(models.Model):
    ROLE_CHOICES = [("user", "Usuário"), ("assistant", "IA")]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="health_messages", on_delete=models.CASCADE,
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user} [{self.role}] {self.created_at:%d/%m %H:%M}"


# ============================================================
# CAMILA CHAT (persiste conversa + reações automáticas)
# ============================================================
class CamilaChatMessage(models.Model):
    ROLE_CHOICES = [("user", "Usuário"), ("assistant", "Camila")]
    SOURCE_CHOICES = [
        ("chat", "Chat direto"),
        ("react", "Reação automática"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="camila_messages",
        on_delete=models.CASCADE,
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    text = models.TextField()
    source = models.CharField(
        max_length=10, choices=SOURCE_CHOICES, default="chat",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user} [{self.role}/{self.source}] {self.created_at:%d/%m %H:%M}"


# ============================================================
# CAMILA NEWS (notícias persistentes)
# ============================================================
class CamilaNews(models.Model):
    title = models.CharField(max_length=250)
    url = models.URLField(max_length=500)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fetched_at"]
        indexes = [
            models.Index(fields=["-fetched_at"]),
        ]

    def __str__(self):
        return f"{self.title[:60]} ({self.fetched_at:%d/%m %H:%M})"


# ============================================================
# STORED FILE (arquivos no banco de dados — bytea)
# ============================================================
class StoredFile(models.Model):
    """
    Armazena o conteúdo binário dos arquivos (imagens, vídeos, PDFs, etc.)
    diretamente no PostgreSQL (campo bytea), eliminando dependência do filesystem.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    original_name = models.CharField(max_length=500, blank=True, default="")
    content_type = models.CharField(max_length=200, blank=True, default="application/octet-stream")
    data = models.BinaryField()
    size = models.BigIntegerField(default=0)
    checksum = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Arquivo armazenado"
        verbose_name_plural = "Arquivos armazenados"
        indexes = [
            models.Index(fields=["checksum"], name="storedfile_checksum_idx"),
        ]

    def __str__(self):
        return f"{self.original_name} ({self.size} bytes)"


# ============================================================
# WHATS NEW — novidades do sistema (tipo Trello "What's new")
# ============================================================
class WhatsNewItem(models.Model):
    commit_hash = models.CharField(max_length=40, unique=True, blank=True, default="")
    emoji = models.CharField(max_length=8, blank=True, default="✨")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-published_at"]
        indexes = [
            models.Index(fields=["-published_at"]),
            models.Index(fields=["is_published", "-published_at"]),
        ]

    def __str__(self):
        return f"{self.emoji} {self.title}"


# ============================================================
# CARD EMBEDDING — vetor semântico para detectar cards similares
# ============================================================
class CardEmbedding(models.Model):
    card = models.OneToOneField(
        Card,
        related_name="embedding",
        on_delete=models.CASCADE,
    )
    content_hash = models.CharField(max_length=64, db_index=True)
    embedding = models.JSONField(default=list)
    model = models.CharField(max_length=64, default="text-embedding-3-small")
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()

    class Meta:
        indexes = [
            models.Index(fields=["content_hash"], name="cardemb_hash_idx"),
        ]

    def __str__(self):
        return f"emb(card={self.card_id})"


# ============================================================
# MODERATION — content review & banishment audit
# ============================================================
class BannedTerm(models.Model):
    """Lista de termos proibidos (Camada 1 — bloqueio determinístico).

    O termo é guardado em forma normalizada (minúsculas, sem acentos, sem
    separadores) — a normalização do conteúdo a ser checado é feita em
    boards/services/moderation/normalize.py.
    """
    SEVERITY_BLOCK = "block"
    SEVERITY_FLAG = "flag"
    SEVERITY_CHOICES = [
        (SEVERITY_BLOCK, "Bloqueia (HTTP 400)"),
        (SEVERITY_FLAG, "Sinaliza para revisão humana"),
    ]
    MATCH_SUBSTRING = "substring"
    MATCH_WORD = "word"
    MATCH_CHOICES = [
        (MATCH_SUBSTRING, "Substring (qualquer lugar)"),
        (MATCH_WORD, "Palavra inteira (evita falso positivo em termos curtos)"),
    ]
    CATEGORY_CHOICES = [
        ("hate", "Discurso de ódio"),
        ("sexual", "Conteúdo sexual"),
        ("violence", "Violência"),
        ("harassment", "Assédio"),
        ("spam", "Spam"),
        ("pii", "Dados pessoais sensíveis"),
        ("political", "Político/religioso/comercial externo"),
        ("other", "Outro"),
    ]
    term = models.CharField(
        max_length=80, unique=True,
        help_text="Termo normalizado (minúsculas, sem acentos/separadores)."
    )
    display = models.CharField(
        max_length=120, blank=True, default="",
        help_text="Forma humana do termo (só pra leitura no admin)."
    )
    severity = models.CharField(
        max_length=10, choices=SEVERITY_CHOICES, default=SEVERITY_BLOCK,
    )
    match_mode = models.CharField(
        max_length=10, choices=MATCH_CHOICES, default=MATCH_SUBSTRING,
        help_text="'substring' (padrão) casa em qualquer parte do texto. "
                  "'word' exige fronteira de palavra — use em termos curtos "
                  "(cu, pau, bunda) pra evitar falso positivo em palavras "
                  "normais (currículo, Paula, abundância).",
    )
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default="other", db_index=True,
    )
    terms_clause = models.CharField(
        max_length=20, blank=True, default="4.4",
        help_text="Cláusula dos Termos de Uso violada (ex: 4.4).",
    )
    active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["term"]
        verbose_name = "Termo banido"
        verbose_name_plural = "Termos banidos"

    def __str__(self):
        return f"{self.term} [{self.severity}/{self.category}]"


class ModerationCase(models.Model):
    """1 caso = 1 análise de conteúdo (qualquer tipo: post, comentário, chat, perfil).

    Identifica o conteúdo via (content_kind, object_id) — evitamos GenericFK
    formal pra não ter que carregar contenttypes em todo lugar.
    """
    KIND_SOCIAL_POST = "social_post"
    KIND_SOCIAL_COMMENT = "social_comment"
    KIND_CHAT_MESSAGE = "chat_message"
    KIND_USER_HANDLE = "user_handle"
    KIND_USER_NAME = "user_name"
    KIND_USER_BIO = "user_bio"
    KIND_CHOICES = [
        (KIND_SOCIAL_POST, "Post"),
        (KIND_SOCIAL_COMMENT, "Comentário"),
        (KIND_CHAT_MESSAGE, "Mensagem de chat"),
        (KIND_USER_HANDLE, "Handle"),
        (KIND_USER_NAME, "Nome do usuário"),
        (KIND_USER_BIO, "Bio"),
    ]

    STATUS_AUTO_BLOCKED = "auto_blocked"
    STATUS_PENDING_HUMAN = "pending_human"
    STATUS_HUMAN_APPROVED = "human_approved"
    STATUS_HUMAN_REJECTED = "human_rejected"
    STATUS_AUTO_CLEARED = "auto_cleared"
    STATUS_CHOICES = [
        (STATUS_AUTO_BLOCKED, "Bloqueado automaticamente (Camada 1)"),
        (STATUS_PENDING_HUMAN, "Aguardando revisão humana"),
        (STATUS_HUMAN_APPROVED, "Aprovado por moderador"),
        (STATUS_HUMAN_REJECTED, "Rejeitado por moderador"),
        (STATUS_AUTO_CLEARED, "Liberado automaticamente (Camada 2)"),
    ]

    content_kind = models.CharField(max_length=20, choices=KIND_CHOICES, db_index=True)
    object_id = models.PositiveIntegerField(db_index=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="moderation_cases",
        on_delete=models.CASCADE,
    )
    subject_text = models.TextField(
        blank=True, default="",
        help_text="Snapshot do texto analisado (evidência imutável).",
    )

    # Camada 1
    layer1_hit = models.BooleanField(default=False)
    layer1_term = models.ForeignKey(
        BannedTerm, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    # Camada 2
    layer2_provider = models.CharField(max_length=40, blank=True, default="")
    layer2_scores = models.JSONField(default=dict, blank=True)
    layer2_flagged = models.BooleanField(default=False)
    layer2_categories = models.JSONField(default=list, blank=True)
    layer2_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING_HUMAN, db_index=True,
    )
    decision_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    decision_at = models.DateTimeField(null=True, blank=True)
    decision_notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["content_kind", "object_id"]),
            models.Index(fields=["author", "-created_at"]),
        ]
        verbose_name = "Caso de moderação"
        verbose_name_plural = "Casos de moderação"

    def __str__(self):
        return f"#{self.pk} {self.content_kind} obj={self.object_id} [{self.status}]"


class BanLog(models.Model):
    """Registro imutável de cada ação punitiva — auditoria/compliance.

    Cada linha é uma punição aplicada (warn, post_block, social_block,
    account_block, idcamim_block). Pode estar ligada a um ModerationCase
    que originou a punição, ou ser aplicada manualmente pelo admin.
    """
    ACTION_WARN = "warn"
    ACTION_POST_BLOCK = "post_block"
    ACTION_SOCIAL_BLOCK = "social_block"
    ACTION_ACCOUNT_BLOCK = "account_block"
    ACTION_IDCAMIM_BLOCK = "idcamim_block"
    ACTION_CHOICES = [
        (ACTION_WARN, "Aviso"),
        (ACTION_POST_BLOCK, "Bloqueio do post"),
        (ACTION_SOCIAL_BLOCK, "Bloqueio do social (não publica/comenta)"),
        (ACTION_ACCOUNT_BLOCK, "Bloqueio da conta NossoTrello"),
        (ACTION_IDCAMIM_BLOCK, "Bloqueio do IDCamim"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="ban_logs",
        on_delete=models.CASCADE,
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, db_index=True)
    case = models.ForeignKey(
        ModerationCase, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ban_logs",
    )
    reason = models.TextField(
        help_text="Texto livre que vai pro email do usuário banido.",
    )
    terms_clause = models.CharField(
        max_length=40, blank=True, default="",
        help_text="Cláusula dos Termos de Uso violada (ex: 4.4).",
    )
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ban_logs_applied",
        help_text="Quem aplicou (null = sistema/automático).",
    )
    applied_at = models.DateTimeField(auto_now_add=True)
    effective_until = models.DateTimeField(
        null=True, blank=True,
        help_text="Quando expira (null = permanente até revogação).",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    revoke_reason = models.TextField(blank=True, default="")
    email_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-applied_at"]
        indexes = [
            models.Index(fields=["user", "-applied_at"]),
            models.Index(fields=["action", "-applied_at"]),
        ]
        verbose_name = "Punição aplicada"
        verbose_name_plural = "Punições aplicadas"

    def __str__(self):
        return f"{self.user} → {self.action} @ {self.applied_at:%Y-%m-%d %H:%M}"


class AllowedEmailDomain(models.Model):
    """Domínios de e-mail habilitados a criar login / receber convite automático.

    Complementa (faz UNION com) `settings.INSTITUTIONAL_EMAIL_DOMAINS`. A lista
    do settings continua valendo como base fixa; esta tabela permite a Direção
    liberar novos domínios pelo admin sem deploy. Ex.: gp5partners.com.br.

    O domínio é guardado normalizado: minúsculas, sem espaços e sem o '@'.
    """
    domain = models.CharField(
        max_length=255, unique=True,
        help_text="Apenas o domínio, sem '@'. Ex.: gp5partners.com.br",
    )
    active = models.BooleanField(default=True, db_index=True)
    notes = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Motivo / quem pediu (opcional).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["domain"]
        verbose_name = "Domínio de e-mail permitido"
        verbose_name_plural = "Domínios de e-mail permitidos"

    def __str__(self):
        return self.domain + ("" if self.active else " (inativo)")

    @staticmethod
    def normalize_domain(value: str) -> str:
        value = (value or "").strip().lower()
        if "@" in value:
            value = value.rsplit("@", 1)[-1]
        return value.strip().strip(".")

    def save(self, *args, **kwargs):
        self.domain = self.normalize_domain(self.domain)
        super().save(*args, **kwargs)


# ============================================================
# EMAIL INGEST — "Criar Card From Email"
# Caixa de entrada IMAP -> cards numa coluna do quadro.
# Senha guardada criptografada (boards/services/secret_crypto.py).
# ============================================================
class BoardEmailIngest(models.Model):
    board = models.OneToOneField(
        Board, related_name="email_ingest", on_delete=models.CASCADE
    )
    target_column = models.ForeignKey(
        Column, related_name="email_ingests", on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    PROTOCOL_CHOICES = [("imap", "IMAP"), ("pop", "POP3")]
    protocol = models.CharField(max_length=8, choices=PROTOCOL_CHOICES, default="imap")

    imap_host = models.CharField(max_length=255)
    imap_port = models.PositiveIntegerField(default=993)
    use_ssl = models.BooleanField(default=True)
    email_user = models.CharField(max_length=255)
    # token Fernet (bytes) da senha — nunca em texto puro
    password_encrypted = models.BinaryField(null=True, blank=True)

    sync_interval_minutes = models.PositiveIntegerField(default=15)
    is_active = models.BooleanField(default=True)

    # controle de sync / dedup
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_uid = models.CharField(max_length=64, blank=True, default="")  # IMAP (UID numérico)
    seen_uids = models.JSONField(default=list, blank=True)              # POP3 (UIDLs já vistos)
    last_error = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="email_ingests_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"EmailIngest[{self.board.name} <- {self.email_user}]"

    def is_due(self):
        """True se já passou o intervalo desde o último sync."""
        if not self.is_active:
            return False
        if not self.last_sync_at:
            return True
        delta = timezone.now() - self.last_sync_at
        return delta.total_seconds() >= self.sync_interval_minutes * 60


# ============================================================
# AUTOMAÇÃO DA COLUNA (estilo Trello, sem o construtor de regras)
# Gatilho: card ENTRA / SAI da lista -> executa uma ação.
# ============================================================
class ColumnAutomation(models.Model):
    TRIGGER_CHOICES = [
        ("enter", "Quando um card entra na lista"),
        ("leave", "Quando um card sai da lista"),
        ("count_below", "Quando a lista fica com MENOS de X cards"),
        ("count_above", "Quando a lista fica com MAIS de X cards"),
        ("stale", "Quando um card fica parado X dias nesta lista"),
    ]
    ACTION_CHOICES = [
        ("send_email", "Disparar e-mail avisando alguém"),
        ("send_whatsapp", "Enviar mensagem no WhatsApp"),
        ("notify_placer", "Avisar quem colocou o card aqui (WhatsApp/e-mail)"),
        ("assign_user", "Marcar uma pessoa (cria acompanhamento)"),
        ("move_to", "Mover o card para outra coluna"),
        ("copy_to", "Copiar o card para outra coluna"),
        ("set_due", "Definir data de entrega (+N dias)"),
        ("set_start", "Definir data de início (+N dias)"),
        ("add_label", "Adicionar etiqueta"),
        ("mark_delivered", "Marcar como entregue"),
        ("mark_undelivered", "Marcar como NÃO entregue (limpa a data de entrega)"),
    ]

    column = models.ForeignKey(
        Column, related_name="automations", on_delete=models.CASCADE
    )
    trigger = models.CharField(max_length=16, choices=TRIGGER_CHOICES)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    # parâmetros por ação: {email} | {target_column_id} | {days} | {label} | {user_id} | {count} | {message}
    params = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    # histerese p/ gatilhos de contagem: só dispara na transição (não repete)
    armed = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="column_automations_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.column.name}: {self.trigger} -> {self.action}"


# END boards/models.py
