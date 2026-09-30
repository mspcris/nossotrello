"""Sincroniza o status das contas com o IDCamim.

Quem está desativado no IDCamim sai dos quadros dos outros, perde o login e
some da rede social; quem foi reativado lá volta (com os compartilhamentos).
Roda pelo celery beat a cada 10 min (settings.CELERY_BEAT_SCHEDULE).

    python manage.py sync_idcamim_status            # aplica
    python manage.py sync_idcamim_status --dry-run  # só mostra
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from boards.models import BoardMembership, UserProfile
from boards.services.idcamim_status import (
    apply_idcamim_inactive,
    apply_idcamim_reactivated,
    is_moderation_banned,
)
from boards.services.moderation.camim_admin import fetch_inactive_users


class Command(BaseCommand):
    help = "Aplica no Tarefas as desativações/reativações de conta do IDCamim."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Só lista, não altera nada.")

    def handle(self, *args, dry_run=False, **opts):
        usuarios, erro = fetch_inactive_users()
        if usuarios is None:
            # Sem a lista não dá para saber quem foi reativado: não mexe em nada.
            raise CommandError(f"IDCamim indisponível: {erro}")

        subs = {str(u.get("sub") or "").strip() for u in usuarios} - {""}
        emails = {str(u.get("email") or "").strip().lower() for u in usuarios} - {""}

        User = get_user_model()

        # Casa pelo sub (imutável); o e-mail só vale para quem nunca logou pelo
        # IDCamim aqui (sem camim_sub) — ex.: criado ao receber um compartilhamento.
        alvo_ids = set(
            User.objects.filter(profile__camim_sub__in=subs).values_list("id", flat=True)
        )
        if emails:
            sem_sub = User.objects.filter(
                Q(profile__isnull=True) | Q(profile__camim_sub__isnull=True) | Q(profile__camim_sub="")
            ).values_list("id", "email")
            alvo_ids |= {uid for uid, email in sem_sub if (email or "").strip().lower() in emails}

        ja_inativos = set(
            UserProfile.objects.filter(idcamim_inativo=True).values_list("user_id", flat=True)
        )

        desativar = User.objects.filter(id__in=alvo_ids - ja_inativos)
        # Quem já estava marcado mas ganhou compartilhamento novo depois.
        recompartilhados = User.objects.filter(
            id__in=BoardMembership.objects
            .filter(user_id__in=alvo_ids & ja_inativos)
            .exclude(role=BoardMembership.Role.OWNER)
            .values("user_id")
        )
        reativar = User.objects.filter(id__in=ja_inativos - alvo_ids).select_related("profile")

        n_des = n_shares = n_rea = n_back = 0
        for user in desativar.order_by("id"):
            shares = BoardMembership.objects.filter(user=user).exclude(role=BoardMembership.Role.OWNER).count()
            self.stdout.write(f"desativar: {user.pk} {user.email} ({shares} compartilhamento(s))")
            if not dry_run:
                n_shares += apply_idcamim_inactive(user)
            n_des += 1

        for user in recompartilhados:
            if not dry_run:
                n_shares += apply_idcamim_inactive(user)

        for user in reativar.order_by("id"):
            if is_moderation_banned(user.profile):
                continue
            self.stdout.write(f"reativar: {user.pk} {user.email}")
            if not dry_run:
                n_back += apply_idcamim_reactivated(user)
            n_rea += 1

        prefixo = "[dry-run] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefixo}IDCamim: {len(usuarios)} inativo(s) lá; "
            f"{n_des} desativado(s) aqui ({n_shares} compartilhamento(s) retirado(s)); "
            f"{n_rea} reativado(s) ({n_back} compartilhamento(s) devolvido(s))."
        ))

