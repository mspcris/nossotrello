"""Conta desativada no IDCamim some do Tarefas (boards/services/idcamim_status.py)."""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from boards.models import Board, BoardMembership, RevokedBoardMembership, UserProfile
from boards.services.idcamim_status import apply_idcamim_inactive, apply_idcamim_reactivated
from boards.services.social_activity import is_socially_active

User = get_user_model()
FETCH = "boards.management.commands.sync_idcamim_status.fetch_inactive_users"


class IdcamimStatusTests(TestCase):
    def setUp(self):
        self.dono = User.objects.create_user("dono", "dono@camim.com.br")
        self.vini = User.objects.create_user("vini", "vinicius.gama@clinicacamim.com.br")
        UserProfile.objects.update_or_create(user=self.vini, defaults={"camim_sub": "sub-vini"})
        self.quadro_do_dono = Board.objects.create(name="Inteligência", created_by=self.dono)
        self.quadro_do_vini = Board.objects.create(name="Meu quadro", created_by=self.vini)
        BoardMembership.objects.create(board=self.quadro_do_dono, user=self.dono, role="owner")
        BoardMembership.objects.create(board=self.quadro_do_dono, user=self.vini, role="editor")
        BoardMembership.objects.create(board=self.quadro_do_vini, user=self.vini, role="owner")
        BoardMembership.objects.create(board=self.quadro_do_vini, user=self.dono, role="viewer")

    def _sync(self, usuarios):
        out = StringIO()
        with patch(FETCH, return_value=(usuarios, "")):
            call_command("sync_idcamim_status", stdout=out)
        return out.getvalue()

    def test_desativado_sai_dos_quadros_dos_outros_e_mantem_os_proprios(self):
        self._sync([{"sub": "sub-vini", "email": "vinicius.gama@clinicacamim.com.br"}])

        self.vini.refresh_from_db()
        self.assertFalse(self.vini.is_active)
        self.assertTrue(self.vini.profile.idcamim_inativo)
        self.assertFalse(
            BoardMembership.objects.filter(board=self.quadro_do_dono, user=self.vini).exists()
        )
        # Quadro próprio intacto, e quem ele compartilhou continua lá.
        self.assertTrue(
            BoardMembership.objects.filter(board=self.quadro_do_vini, user=self.vini, role="owner").exists()
        )
        self.assertTrue(
            BoardMembership.objects.filter(board=self.quadro_do_vini, user=self.dono).exists()
        )
        revogado = RevokedBoardMembership.objects.get(user=self.vini)
        self.assertEqual((revogado.board_id, revogado.role), (self.quadro_do_dono.id, "editor"))
        self.assertFalse(is_socially_active(self.vini))

    def test_reativado_no_idcamim_volta_com_os_compartilhamentos(self):
        self._sync([{"sub": "sub-vini", "email": "x"}])
        self._sync([])

        self.vini.refresh_from_db()
        self.assertTrue(self.vini.is_active)
        self.assertFalse(self.vini.profile.idcamim_inativo)
        self.assertTrue(
            BoardMembership.objects.filter(board=self.quadro_do_dono, user=self.vini, role="editor").exists()
        )
        self.assertFalse(RevokedBoardMembership.objects.exists())

    def test_idcamim_fora_do_ar_nao_reativa_ninguem(self):
        apply_idcamim_inactive(self.vini)
        with patch(FETCH, return_value=(None, "timeout")):
            with self.assertRaises(Exception):
                call_command("sync_idcamim_status", stdout=StringIO())
        self.vini.refresh_from_db()
        self.assertFalse(self.vini.is_active)

    def test_banido_pela_moderacao_nao_e_reativado(self):
        apply_idcamim_inactive(self.vini)
        UserProfile.objects.filter(user=self.vini).update(account_blocked=True)
        self.vini.refresh_from_db()
        self.assertEqual(apply_idcamim_reactivated(self.vini), 0)
        self.vini.refresh_from_db()
        self.assertFalse(self.vini.is_active)

    def test_casa_por_email_quem_nao_tem_sub(self):
        sem_sub = User.objects.create_user("novo", "Novo@Camim.com.br")
        BoardMembership.objects.create(board=self.quadro_do_dono, user=sem_sub, role="viewer")
        self._sync([{"sub": "outro-sub", "email": "novo@camim.com.br"}])
        sem_sub.refresh_from_db()
        self.assertFalse(sem_sub.is_active)
        self.assertFalse(BoardMembership.objects.filter(user=sem_sub).exists())

    def test_compartilhamento_novo_com_inativo_e_retirado_no_proximo_sync(self):
        usuarios = [{"sub": "sub-vini", "email": "x"}]
        self._sync(usuarios)
        outro = Board.objects.create(name="Outro", created_by=self.dono)
        BoardMembership.objects.create(board=outro, user=self.vini, role="editor")
        self._sync(usuarios)
        self.assertFalse(BoardMembership.objects.filter(board=outro, user=self.vini).exists())

    def test_dry_run_nao_altera(self):
        out = StringIO()
        with patch(FETCH, return_value=([{"sub": "sub-vini", "email": "x"}], "")):
            call_command("sync_idcamim_status", "--dry-run", stdout=out)
        self.vini.refresh_from_db()
        self.assertTrue(self.vini.is_active)
        self.assertIn("desativar: ", out.getvalue())
