from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from django.urls import reverse
from django.core.mail import send_mail

from tracktime.models import TimeEntry


class Command(BaseCommand):
    help = "Processa timers longos: envia email em 1h e auto-stop em 1h15."

    def handle(self, *args, **options):
        now = timezone.now()

        base_url = (getattr(settings, "SITE_URL", "") or "").strip()
        if not base_url:
            base_url = "http://localhost:8000"

        # 1) Auto-stop (>= auto_stop_at)
        stop_qs = TimeEntry.objects.filter(
            ended_at__isnull=True,
            auto_stop_at__isnull=False,
            auto_stop_at__lte=now,
        )
        stopped = 0
        for entry in stop_qs.iterator():
            entry.stop()
            stopped += 1

        # 2) Email de confirmação (>= confirm_due_at e ainda antes do auto_stop_at)
        confirm_qs = TimeEntry.objects.filter(
            ended_at__isnull=True,
            confirm_due_at__isnull=False,
            confirm_due_at__lte=now,
        ).exclude(
            auto_stop_at__isnull=False,
            auto_stop_at__lte=now,
        ).filter(
            confirmation_sent_at__isnull=True
        )

        emailed = 0
        for entry in confirm_qs.iterator():
            to_email = (getattr(entry.user, "email", "") or "").strip()
            if not to_email:
                continue

            raw = entry.generate_confirmation_token()
            entry.confirmation_sent_at = now
            entry.save(update_fields=["confirmation_token_hash", "confirmation_sent_at"])

            link_path = reverse("tracktime:confirm_link", kwargs={"entry_id": entry.id, "token": raw})
            confirm_url = f"{base_url}{link_path}"

            subject = "Você ainda está nesta tarefa?"
            body = (
                "Estamos com um timer rodando há 1h.\n\n"
                "Confirme para adicionar mais 1h:\n"
                f"{confirm_url}\n\n"
                "Se você não confirmar, vamos parar automaticamente em 15 minutos."
            )

            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email], fail_silently=True)
            emailed += 1

        self.stdout.write(self.style.SUCCESS(f"tracktime_tick: stopped={stopped} emailed={emailed}"))
