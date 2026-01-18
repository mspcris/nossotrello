#tracktime/models.py

from django.conf import settings
from django.db import models
from django.utils import timezone
import hashlib
import secrets

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

    # Para timer
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    # ===== Ciclo de confirmação (timer longo) =====
    confirm_due_at = models.DateTimeField(null=True, blank=True)
    auto_stop_at = models.DateTimeField(null=True, blank=True)

    confirmation_sent_at = models.DateTimeField(null=True, blank=True)
    confirmation_token_hash = models.CharField(max_length=128, blank=True, default="")

    last_confirmed_at = models.DateTimeField(null=True, blank=True)
    confirm_cycle = models.PositiveIntegerField(default=0)

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
    # Estado do timer
    # =========================================================

    @property
    def is_running(self) -> bool:
        """
        Retorna True se o timer estiver em execução.
        """
        return self.started_at is not None and self.ended_at is None

    # =========================================================
    # Helpers
    # =========================================================

    @property
    def duration_hours(self) -> float:
        return round(self.minutes / 60, 2)

    def stop(self):
        """
        Finaliza o timer atual e acumula os minutos.
        NÃO cria novo registro.
        NÃO perde minutos já existentes.
        """
        if not self.is_running:
            return

        end = timezone.now()
        delta = end - self.started_at
        extra_minutes = max(int(delta.total_seconds() // 60), 1)

        self.minutes += extra_minutes
        self.ended_at = end
        self.started_at = None

        self.save(update_fields=["minutes", "ended_at", "started_at"])

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
        Criação via timer (start/stop direto).
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


    # =========================================================
    # Confirmação / extensões do timer
    # =========================================================

    def set_confirmation_window(self, *, now=None):
        """
        Define a janela:
        - pedir confirmação em 1h
        - auto-stop em 1h15m
        """
        now = now or timezone.now()
        self.confirm_due_at = now + timezone.timedelta(hours=1)
        self.auto_stop_at = now + timezone.timedelta(hours=1, minutes=15)

    def needs_confirmation(self, *, now=None) -> bool:
        now = now or timezone.now()
        return (
            self.is_running
            and self.confirm_due_at is not None
            and now >= self.confirm_due_at
            and (self.auto_stop_at is None or now < self.auto_stop_at)
        )

    def is_past_auto_stop(self, *, now=None) -> bool:
        now = now or timezone.now()
        return self.is_running and self.auto_stop_at is not None and now >= self.auto_stop_at

    def _hash_token(self, raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def generate_confirmation_token(self) -> str:
        """
        Gera token de uso único (armazenando apenas hash).
        """
        raw = secrets.token_urlsafe(32)
        self.confirmation_token_hash = self._hash_token(raw)
        return raw

    def check_confirmation_token(self, raw: str) -> bool:
        if not raw or not self.confirmation_token_hash:
            return False
        return self._hash_token(raw) == self.confirmation_token_hash

    def extend_one_hour(self, *, now=None):
        """
        Confirma + estende por mais 1h, rearmando o ciclo.
        """
        now = now or timezone.now()

        # Se não está rodando, não faz nada
        if not self.is_running:
            return

        self.confirm_cycle = (self.confirm_cycle or 0) + 1
        self.last_confirmed_at = now

        # Rearma janela a partir de agora (não do started_at)
        self.confirm_due_at = now + timezone.timedelta(hours=1)
        self.auto_stop_at = now + timezone.timedelta(hours=1, minutes=15)

        # Permite novo e-mail no próximo ciclo
        self.confirmation_sent_at = None
        self.confirmation_token_hash = ""

        self.save(
            update_fields=[
                "confirm_cycle",
                "last_confirmed_at",
                "confirm_due_at",
                "auto_stop_at",
                "confirmation_sent_at",
                "confirmation_token_hash",
            ]
        )


#END tracktime/models.py