from django.conf import settings
from django.db import models
from django.utils import timezone


User = settings.AUTH_USER_MODEL


class Project(models.Model):
    """
    Projeto de track-time.
    Pode ou não estar ligado a boards/cards.
    """

    name = models.CharField(max_length=255)
    client_name = models.CharField(max_length=255, blank=True)
    git_url = models.URLField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ActivityType(models.Model):
    """
    Tipo de atividade (Brainstorm, Dev, Bugfix, etc).
    """

    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    # FUTURO (fora do MVP)
    is_billable = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Team(models.Model):
    """
    Time de trabalho (conceito lógico).
    """

    name = models.CharField(max_length=255, unique=True)
    members = models.ManyToManyField(
        User,
        related_name="tracktime_teams",
        blank=True,
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class TimeEntry(models.Model):
    """
    Lançamento de tempo.
    É IMUTÁVEL em referência: mesmo que o card suma, o registro fica.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="time_entries",
    )

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="time_entries",
    )

    activity_type = models.ForeignKey(
        ActivityType,
        on_delete=models.PROTECT,
        related_name="time_entries",
    )

    # Tempo efetivo (sempre preenchido)
    minutes = models.PositiveIntegerField(help_text="Tempo em minutos")

    # Para timer (opcional no MVP, mas já preparado)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    # ===== Referência ao card (cache) =====
    board_id = models.PositiveIntegerField(null=True, blank=True)
    card_id = models.PositiveIntegerField(null=True, blank=True)

    card_title_cache = models.CharField(max_length=255, blank=True)
    card_url_cache = models.URLField(blank=True)

    is_card_deleted_cache = models.BooleanField(default=False)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project"]),
            models.Index(fields=["user"]),
            models.Index(fields=["card_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} • {self.project} • {self.minutes}min"

    # =========================================================
    # Helpers
    # =========================================================

    @property
    def duration_hours(self) -> float:
        return round(self.minutes / 60, 2)

    @classmethod
    def create_manual(
        cls,
        *,
        user,
        project,
        activity_type,
        minutes: int,
        board_id=None,
        card_id=None,
        card_title_cache="",
        card_url_cache="",
    ):
        """
        Criação manual (sem timer).
        """
        return cls.objects.create(
            user=user,
            project=project,
            activity_type=activity_type,
            minutes=minutes,
            board_id=board_id,
            card_id=card_id,
            card_title_cache=card_title_cache or "",
            card_url_cache=card_url_cache or "",
        )

    @classmethod
    def create_from_timer(
        cls,
        *,
        user,
        project,
        activity_type,
        started_at,
        ended_at=None,
        board_id=None,
        card_id=None,
        card_title_cache="",
        card_url_cache="",
    ):
        """
        Criação via timer (start/stop).
        """
        end = ended_at or timezone.now()
        delta = end - started_at
        minutes = max(int(delta.total_seconds() // 60), 1)

        return cls.objects.create(
            user=user,
            project=project,
            activity_type=activity_type,
            minutes=minutes,
            started_at=started_at,
            ended_at=end,
            board_id=board_id,
            card_id=card_id,
            card_title_cache=card_title_cache or "",
            card_url_cache=card_url_cache or "",
        )
