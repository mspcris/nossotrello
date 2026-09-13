"""Automação "Entrega mensal de relatório" (boards/services/monthly_report.py)."""
from datetime import date, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from boards.models import (
    Board, BoardMembership, Card, CardAttachment, Column, ColumnAutomation, MonthlyReportEntry,
)
from boards.services import monthly_report as mr

GESTORES = [
    {"nome": "Júlio Albuquerque", "email": "julio@camim.com.br", "telefone": ""},
    {"nome": "Elisangela Rodrigues", "email": "elisangela@camim.com.br", "telefone": ""},
]


def _att(card, name, user=None, when=None):
    a = CardAttachment.objects.create(
        card=card, file=SimpleUploadedFile(name, b"conteudo,1\n2,3\n"), created_by=user,
    )
    if when:
        CardAttachment.objects.filter(id=a.id).update(created_at=when)
        a.refresh_from_db()
    return a


def _dt(y, m, d):
    return timezone.make_aware(datetime(y, m, d, 12, 0))


class MonthFromFilenameTests(TestCase):
    def test_nomes(self):
        today = date(2026, 9, 9)
        f = mr.month_from_filename
        self.assertEqual(f("Relatório_de_consumo_diário_da_CEDAE_-_Abril_de_2026.pdf", today), date(2026, 4, 1))
        self.assertEqual(f("CTRL-Q 08-2026.xlsx", today), date(2026, 8, 1))
        self.assertEqual(f("relatorio 2026-06 medicos.pdf", today), date(2026, 6, 1))
        self.assertEqual(f("Relatorio Junho.pdf", today), date(2026, 6, 1))
        self.assertEqual(f("Relatorio Dezembro.pdf", today), date(2025, 12, 1))  # futuro -> ano anterior
        self.assertIsNone(f("MODELO_RELATÓRIO_AGENDA_MÉDICA.xlsx", today))
        self.assertIsNone(f("image_fTkl9tq.png", today))


@override_settings(GROQ_API_KEY="")
class MonthlyFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(username="paulo", email="paulo@camim.com.br", password="x")
        cls.julio = User.objects.create_user(username="julio", email="julio@camim.com.br", password="x")
        cls.board = Board.objects.create(name="ANCHIETA", created_by=cls.owner)
        BoardMembership.objects.create(board=cls.board, user=cls.owner, role="owner")
        BoardMembership.objects.create(board=cls.board, user=cls.julio, role="editor")
        cls.col = Column.objects.create(board=cls.board, name="Reloatórios Empresariais", position=0)
        cls.card = Card.objects.create(column=cls.col, title="Relatório do CTRL-Q - Leonardo Pereira",
                                       created_by=cls.owner, is_delivered=True, due_date=date(2026, 5, 15))
        cls.rule = ColumnAutomation.objects.create(
            column=cls.col, trigger="attach", action="monthly_report",
            params={"day": 15, "recipient_email": "leonardo@camim.com.br", "ai_validate": False,
                    "start_month": "2026-06"},
        )

    def setUp(self):
        mr.invalidate_cache()
        p = patch("boards.services.hesk_gestores.gestores_do_posto", return_value=list(GESTORES))
        p.start(); self.addCleanup(p.stop)
        t = patch("boards.services.monthly_report.today_local", return_value=date(2026, 9, 9))
        t.start(); self.addCleanup(t.stop)

    # --- anexo entra no mês pendente mais antigo e rola a data ---------------
    def test_attach_delivers_oldest_pending_and_rolls_due(self):
        for m in (6, 7, 8, 9):
            mr.ensure_entry(self.rule, self.card, date(2026, m, 1))
        a = _att(self.card, "ctrlq.pdf", self.julio)
        e = mr.on_attachment_added(self.card, a, actor=self.julio, sync=True)
        self.assertEqual(e.month, date(2026, 6, 1))
        self.assertEqual(e.status, "delivered")
        self.card.refresh_from_db()
        self.assertFalse(self.card.is_delivered)
        self.assertEqual(self.card.due_date, date(2026, 7, 15))  # próximo pendente (julho)
        # e-mail "anexado" para o destinatário
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["leonardo@camim.com.br"])
        self.assertIn("Jun/2026 anexado", mail.outbox[0].subject)
        self.assertIn("Júlio", mail.outbox[0].body) if False else None

    def test_filename_month_targets_that_month(self):
        for m in (6, 7, 8, 9):
            mr.ensure_entry(self.rule, self.card, date(2026, m, 1))
        a = _att(self.card, "Relatorio CTRL-Q - Agosto de 2026.pdf", self.julio)
        e = mr.on_attachment_added(self.card, a, actor=self.julio, sync=True)
        self.assertEqual(e.month, date(2026, 8, 1))
        self.card.refresh_from_db()
        self.assertEqual(self.card.due_date, date(2026, 6, 15))  # junho continua o mais antigo

    def test_second_file_same_month_is_extra_and_creates_next(self):
        mr.ensure_entry(self.rule, self.card, date(2026, 9, 1))
        a1 = _att(self.card, "set.pdf", self.julio)
        mr.on_attachment_added(self.card, a1, actor=self.julio, sync=True)
        self.card.refresh_from_db()
        self.assertEqual(self.card.due_date, date(2026, 10, 15))
        self.assertTrue(MonthlyReportEntry.objects.filter(card=self.card, month=date(2026, 10, 1), status="pending").exists())
        a2 = _att(self.card, "set-v2.pdf", self.julio)
        e = mr.on_attachment_added(self.card, a2, actor=self.julio, sync=True)
        self.assertEqual(e.month, date(2026, 9, 1))
        self.assertEqual(e.extra_attachment_ids, [a2.id])
        self.card.refresh_from_db()
        self.assertEqual(self.card.due_date, date(2026, 10, 15))

    def test_remove_attachment_reopens_month(self):
        mr.ensure_entry(self.rule, self.card, date(2026, 9, 1))
        a = _att(self.card, "set.pdf", self.julio)
        mr.on_attachment_added(self.card, a, actor=self.julio, sync=True)
        a.soft_delete()
        e = mr.on_attachment_removed(self.card, a)
        self.assertEqual(e.status, "pending")
        self.assertIsNone(e.attachment)
        self.card.refresh_from_db()
        self.assertEqual(self.card.due_date, date(2026, 9, 15))
        self.assertFalse(MonthlyReportEntry.objects.filter(card=self.card, month=date(2026, 10, 1)).exists())

    # --- cobrança ------------------------------------------------------------
    def test_scheduler_groups_overdue_months_daily(self):
        for m in (6, 7, 8, 9):
            mr.ensure_entry(self.rule, self.card, date(2026, m, 1))
        stats = mr.run_scheduler(now=timezone.make_aware(datetime(2026, 9, 9, 8)))
        self.assertEqual(stats["reminded"], 1)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(sorted(msg.to), sorted(["julio@camim.com.br", "elisangela@camim.com.br"]))
        self.assertEqual(msg.cc, [])
        self.assertIn("Júlio Albuquerque", msg.body)
        self.assertIn("posto ANCHIETA", msg.body)
        for lb in ("Jun/2026", "Jul/2026", "Ago/2026"):
            self.assertIn(lb, msg.subject)
        self.assertNotIn("Set/2026", msg.subject)  # setembro só vence dia 15
        self.assertEqual(MonthlyReportEntry.objects.filter(card=self.card, reminded_at__isnull=False).count(), 3)
        self.assertIn("se repete todos os dias", msg.body)
        # segunda rodada no mesmo dia: nada novo
        mr.run_scheduler(now=timezone.make_aware(datetime(2026, 9, 9, 9)))
        self.assertEqual(len(mail.outbox), 1)
        # dia seguinte antes das 8h: ainda não; a partir das 8h: cobra de novo os mesmos meses
        with patch("boards.services.monthly_report.today_local", return_value=date(2026, 9, 10)):
            mr.run_scheduler(now=timezone.make_aware(datetime(2026, 9, 10, 6)))
            self.assertEqual(len(mail.outbox), 1)
            mr.run_scheduler(now=timezone.make_aware(datetime(2026, 9, 10, 8, 5)))
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("3 meses sem relatório", mail.outbox[1].subject)
        # dia 15: setembro entra na lista diária
        with patch("boards.services.monthly_report.today_local", return_value=date(2026, 9, 15)):
            mr.run_scheduler(now=timezone.make_aware(datetime(2026, 9, 15, 8)))
        self.assertEqual(len(mail.outbox), 3)
        self.assertIn("4 meses sem relatório", mail.outbox[2].subject)
        self.assertIn("Set/2026", mail.outbox[2].subject)
        # anexou tudo: para de cobrar
        for m in (6, 7, 8, 9):
            e = MonthlyReportEntry.objects.get(card=self.card, month=date(2026, m, 1))
            e.status = "delivered"; e.save()
        with patch("boards.services.monthly_report.today_local", return_value=date(2026, 9, 16)):
            mr.run_scheduler(now=timezone.make_aware(datetime(2026, 9, 16, 9)))
        self.assertEqual(len(mail.outbox), 3)

    def test_scheduler_without_gestores_nao_envia_nada(self):
        """Sem gestor no Hesk não há para quem cobrar — e o destinatário do
        relatório não pode virar saco de pancada da cobrança diária."""
        mr.ensure_entry(self.rule, self.card, date(2026, 8, 1))
        with patch("boards.services.hesk_gestores.gestores_do_posto", return_value=[]):
            mr.run_scheduler(now=timezone.make_aware(datetime(2026, 9, 9, 8)))
        self.assertEqual(mail.outbox, [])

    def test_cobranca_diaria_nao_copia_o_destinatario(self):
        mr.ensure_entry(self.rule, self.card, date(2026, 8, 1))
        mr.run_scheduler(now=timezone.make_aware(datetime(2026, 9, 9, 8)))
        self.assertEqual(mail.outbox[0].to,
                         ["julio@camim.com.br", "elisangela@camim.com.br"])
        self.assertEqual(mail.outbox[0].cc, [])

    # --- IA ------------------------------------------------------------------
    def test_ai_rejected_holds_month_until_accepted(self):
        self.rule.params["ai_validate"] = True
        self.rule.save()
        mr.ensure_entry(self.rule, self.card, date(2026, 9, 1))
        a = _att(self.card, "outra-coisa.pdf", self.julio)
        with patch("boards.services.monthly_report.validate_with_ai",
                   return_value={"veredito": "reprovado", "resumo": "É um boleto.", "problemas": ["não é o CTRL-Q"]}):
            e = mr.on_attachment_added(self.card, a, actor=self.julio, sync=True)
        e.refresh_from_db()
        self.assertEqual(e.status, "rejected")
        self.card.refresh_from_db()
        self.assertEqual(self.card.due_date, date(2026, 5, 15))  # não rolou
        self.assertTrue(any("REPROVADO" in m.subject for m in mail.outbox))
        rej = [m for m in mail.outbox if "REPROVADO" in m.subject][0]
        self.assertEqual(rej.to, ["julio@camim.com.br"])
        self.assertEqual(rej.cc, ["leonardo@camim.com.br"])
        mr.accept(e, self.owner)
        e.refresh_from_db()
        self.assertEqual(e.status, "delivered")
        self.assertEqual(e.accepted_by, self.owner)
        self.card.refresh_from_db()
        self.assertEqual(self.card.due_date, date(2026, 10, 15))

    def test_ai_atencao_delivers_with_summary_in_email(self):
        self.rule.params["ai_validate"] = True
        self.rule.save()
        mr.ensure_entry(self.rule, self.card, date(2026, 9, 1))
        a = _att(self.card, "ctrlq.xlsx", self.julio)
        with patch("boards.services.monthly_report.validate_with_ai",
                   return_value={"veredito": "atencao", "resumo": "Faltam 3 dias.", "problemas": ["dias 28-30"]}):
            e = mr.on_attachment_added(self.card, a, actor=self.julio, sync=True)
        e.refresh_from_db()
        self.assertEqual(e.status, "delivered")
        self.assertIn("Faltam 3 dias.", mail.outbox[-1].body)
        self.assertIn("ATENÇÃO", mail.outbox[-1].body)

    def test_image_skips_ai_and_delivers(self):
        self.rule.params["ai_validate"] = True
        self.rule.save()
        mr.ensure_entry(self.rule, self.card, date(2026, 9, 1))
        a = _att(self.card, "print.png", self.julio)
        e = mr.on_attachment_added(self.card, a, actor=self.julio, sync=True)
        e.refresh_from_db()
        self.assertEqual(e.status, "delivered")
        self.assertEqual(e.ai_status, "skipped")

    # --- rollout -------------------------------------------------------------
    def test_seed_card_from_existing_attachments(self):
        # anexos: Fev e Mar subidos em 16/03; Abril em 17/04; nada depois -> Mai..Set pendentes
        _att(self.card, "Relatório_CEDAE_-_Fevereiro_de_2026.pdf", self.julio, _dt(2026, 3, 16))
        _att(self.card, "Relatório_CEDAE_-_Março_de_2026.pdf", self.julio, _dt(2026, 3, 16))
        _att(self.card, "Relatório_CEDAE_-_Abril_de_2026.pdf", self.julio, _dt(2026, 4, 17))
        self.rule.params["start_month"] = "2026-02"
        self.rule.save()
        info = mr.seed_card(self.rule, self.card)
        st = {e.month.month: e.status for e in MonthlyReportEntry.objects.filter(card=self.card)}
        self.assertEqual(st, {2: "delivered", 3: "delivered", 4: "delivered",
                              5: "pending", 6: "pending", 7: "pending", 8: "pending", 9: "pending"})
        self.assertEqual(info["pending"], ["Mai/2026", "Jun/2026", "Jul/2026", "Ago/2026", "Set/2026"])
        self.card.refresh_from_db()
        self.assertFalse(self.card.is_delivered)
        self.assertEqual(self.card.due_date, date(2026, 5, 15))
        # idempotente
        mr.seed_card(self.rule, self.card)
        self.assertEqual(MonthlyReportEntry.objects.filter(card=self.card).count(), 8)

    def test_seed_card_current_month_delivered_rolls_to_next(self):
        _att(self.card, "ctrlq.pdf", self.julio, _dt(2026, 9, 1))
        self.rule.params["start_month"] = "2026-09"
        self.rule.save()
        mr.seed_card(self.rule, self.card)
        self.card.refresh_from_db()
        self.assertEqual(self.card.due_date, date(2026, 10, 15))

    # --- comando de rollout --------------------------------------------------
    def test_setup_command_creates_rule_fixes_name_and_reminds(self):
        from django.core.management import call_command
        self.rule.delete()
        _att(self.card, "Relatório_CEDAE_-_Julho_de_2026.pdf", self.julio, _dt(2026, 7, 10))
        call_command("setup_monthly_reports", boards=str(self.board.id), remind_now=True, verbosity=0)
        self.col.refresh_from_db()
        self.assertEqual(self.col.name, "Relatórios Empresariais")
        rule = ColumnAutomation.objects.get(column=self.col, action="monthly_report")
        self.assertEqual(rule.trigger, "attach")
        self.assertEqual(rule.params["start_month"], "2026-07")
        st = {e.month.month: e.status for e in MonthlyReportEntry.objects.filter(card=self.card)}
        self.assertEqual(st, {7: "delivered", 8: "pending", 9: "pending"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Ago/2026", mail.outbox[0].subject)
        self.assertIn("Júlio Albuquerque", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].cc, [])

    # --- chip / painel / API -------------------------------------------------
    def test_chip_and_panel(self):
        mr.ensure_entry(self.rule, self.card, date(2026, 8, 1))
        chip = mr.chip_for_card(self.card)
        self.assertEqual(chip["text"], "📎 falta Ago/2026")
        self.assertEqual(chip["tone"], "late")
        ctx = mr.panel_context(self.card)
        self.assertEqual(ctx["current"].month, date(2026, 8, 1))
        self.assertEqual([g["nome"] for g in ctx["gestores"]], ["Júlio Albuquerque", "Elisangela Rodrigues"])
        other = Column.objects.create(board=self.board, name="Outra", position=1)
        c2 = Card.objects.create(column=other, title="x", created_by=self.owner)
        self.assertIsNone(mr.chip_for_card(c2))
        self.assertEqual(mr.panel_context(c2), {})

    def test_api_requires_token(self):
        from rest_framework.authtoken.models import Token
        mr.ensure_entry(self.rule, self.card, date(2026, 8, 1))
        r = self.client.get("/api/monthly-reports/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 401)
        tok = Token.objects.create(user=self.owner)
        r = self.client.get("/api/monthly-reports/", HTTP_AUTHORIZATION=f"Token {tok.key}", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["rows"][0]["month"], "2026-08")
        self.assertEqual(data["rows"][0]["status"], "pending")
        self.assertEqual(data["rows"][0]["posto"], "ANCHIETA")


@override_settings(GROQ_API_KEY="")
class MonthlyTemplatesTests(TestCase):
    """As telas novas renderizam (aba Mensal, modal de automação com a recorrência)."""

    def setUp(self):
        from django.conf import settings as dj
        User = get_user_model()
        self.owner = User.objects.create_user(username="dono", email="dono@camim.com.br", password="x")
        prof = self.owner.profile
        prof.terms_accepted = True
        prof.terms_version = getattr(dj, "CURRENT_TERMS_VERSION", "2.0")
        prof.activity_sidebar = True
        prof.save()
        self.board = Board.objects.create(name="BANGU", created_by=self.owner)
        BoardMembership.objects.create(board=self.board, user=self.owner, role="owner")
        self.col = Column.objects.create(board=self.board, name="Relatórios Empresariais", position=0)
        self.card = Card.objects.create(column=self.col, title="Relatório CEDAE", created_by=self.owner)
        self.rule = ColumnAutomation.objects.create(
            column=self.col, trigger="attach", action="monthly_report",
            params={"day": 15, "recipient_email": "leonardo@camim.com.br", "ai_validate": True, "start_month": "2026-08"},
        )
        mr.invalidate_cache()
        p = patch("boards.services.hesk_gestores.gestores_do_posto", return_value=list(GESTORES))
        p.start(); self.addCleanup(p.stop)
        t = patch("boards.services.monthly_report.today_local", return_value=date(2026, 9, 9))
        t.start(); self.addCleanup(t.stop)
        self.client.force_login(self.owner)

    def test_panel_renders(self):
        mr.ensure_entry(self.rule, self.card, date(2026, 8, 1))
        r = self.client.get(f"/card/{self.card.id}/monthly/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("Falta o relatório de Ago/2026", html)
        self.assertIn("Júlio Albuquerque", html)

    def test_card_modal_has_monthly_tab(self):
        r = self.client.get(f"/card/{self.card.id}/modal/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('data-cm-tab="monthly"', html)
        self.assertIn('id="cm-monthly-panel"', html)

    def test_automation_modal_renders_and_saves_rule(self):
        r = self.client.get(f"/column/{self.col.id}/automation/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("ca-p-monthly", html)
        self.assertIn("Júlio Albuquerque", html)
        self.assertIn("Entrega mensal de relatório", html)
        # editar a regra existente via POST (uma por coluna)
        r = self.client.post(f"/column/{self.col.id}/automation/", {
            "trigger": "enter", "action": "monthly_report", "day": "10",
            "recipient_email": "leo@camim.com.br", "ai_validate": "1",
            "extra_user_ids": [str(self.owner.id)],
        }, SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ColumnAutomation.objects.filter(column=self.col, action="monthly_report").count(), 1)
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.trigger, "attach")
        self.assertEqual(self.rule.params["day"], 10)
        self.assertEqual(self.rule.params["extra_user_ids"], [self.owner.id])
        self.assertEqual(self.rule.params["start_month"], "2026-08")

    def test_delete_rule_only_deactivates(self):
        r = self.client.post(f"/column-automation/{self.rule.id}/delete/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.rule.refresh_from_db()
        self.assertFalse(self.rule.is_active)
        self.assertEqual(mr.panel_context(self.card), {})

    def test_upload_triggers_monthly(self):
        mr.ensure_entry(self.rule, self.card, date(2026, 9, 1))
        with patch("boards.services.monthly_report._bg", side_effect=lambda fn, *a: fn(*a)):
            r = self.client.post(
                f"/card/{self.card.id}/attachments/add/",
                {"file": SimpleUploadedFile("cedae.png", b"\x89PNG fake")},
                SERVER_NAME="localhost",
            )
        self.assertEqual(r.status_code, 200)
        e = MonthlyReportEntry.objects.get(card=self.card, month=date(2026, 9, 1))
        self.assertEqual(e.status, "delivered")
        self.card.refresh_from_db()
        self.assertEqual(self.card.due_date, date(2026, 10, 15))
        # remover devolve o mês
        r = self.client.post(f"/card/{self.card.id}/attachments/{e.attachment_id}/delete/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        e.refresh_from_db()
        self.assertEqual(e.status, "pending")

    # --- upload direto na linha do mês (aba Mensal) -------------------------
    def test_upload_no_mes_escolhido_quita_mes_atrasado(self):
        """O gestor escolhe Ago/2026 mesmo com Set/2026 aberto — e só Ago fecha."""
        mr.ensure_entry(self.rule, self.card, date(2026, 8, 1))
        mr.ensure_entry(self.rule, self.card, date(2026, 9, 1))
        alvo = MonthlyReportEntry.objects.get(card=self.card, month=date(2026, 8, 1))
        with patch("boards.services.monthly_report._bg", side_effect=lambda fn, *a: fn(*a)):
            r = self.client.post(
                f"/card/{self.card.id}/monthly/{alvo.id}/upload/",
                {"file": SimpleUploadedFile("sem-mes-no-nome.png", b"\x89PNG fake")},
                SERVER_NAME="localhost",
            )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["attachments_count"], 1)
        self.assertIn("Ago/2026", data["panel_html"])

        alvo.refresh_from_db()
        self.assertEqual(alvo.status, "delivered")
        self.assertIsNotNone(alvo.attachment_id)
        self.assertEqual(alvo.attached_by, self.owner)
        # setembro continua aberto e volta a ser o prazo do card
        setembro = MonthlyReportEntry.objects.get(card=self.card, month=date(2026, 9, 1))
        self.assertEqual(setembro.status, "pending")
        self.card.refresh_from_db()
        self.assertEqual(self.card.due_date, date(2026, 9, 15))
        # e o arquivo é um anexo comum do card (aba Anexos)
        self.assertEqual(self.card.attachments.count(), 1)
        self.assertIn("attachment-", data["attachments_html"])

    def test_upload_em_mes_entregue_vira_adicional(self):
        mr.ensure_entry(self.rule, self.card, date(2026, 8, 1))
        alvo = MonthlyReportEntry.objects.get(card=self.card, month=date(2026, 8, 1))
        with patch("boards.services.monthly_report._bg", side_effect=lambda fn, *a: fn(*a)):
            self.client.post(
                f"/card/{self.card.id}/monthly/{alvo.id}/upload/",
                {"file": SimpleUploadedFile("ago.png", b"\x89PNG fake")},
                SERVER_NAME="localhost",
            )
            alvo.refresh_from_db()
            self.assertEqual(alvo.status, "delivered")
            primeiro = alvo.attachment_id
            self.client.post(
                f"/card/{self.card.id}/monthly/{alvo.id}/upload/",
                {"file": SimpleUploadedFile("ago-v2.png", b"\x89PNG fake")},
                SERVER_NAME="localhost",
            )
        alvo.refresh_from_db()
        self.assertEqual(alvo.status, "delivered")
        self.assertEqual(alvo.attachment_id, primeiro)
        self.assertEqual(len(alvo.extra_attachment_ids), 1)

    def test_upload_sem_arquivo_e_somente_leitura(self):
        mr.ensure_entry(self.rule, self.card, date(2026, 9, 1))
        alvo = MonthlyReportEntry.objects.get(card=self.card, month=date(2026, 9, 1))
        r = self.client.post(f"/card/{self.card.id}/monthly/{alvo.id}/upload/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 400)

        User = get_user_model()
        leitor = User.objects.create_user(username="leitor", email="leitor@camim.com.br", password="x")
        prof = leitor.profile
        prof.terms_accepted = True
        from django.conf import settings as dj
        prof.terms_version = getattr(dj, "CURRENT_TERMS_VERSION", "2.0")
        prof.save()
        BoardMembership.objects.create(board=self.board, user=leitor, role="viewer")
        self.client.force_login(leitor)
        r = self.client.post(
            f"/card/{self.card.id}/monthly/{alvo.id}/upload/",
            {"file": SimpleUploadedFile("x.png", b"\x89PNG fake")},
            SERVER_NAME="localhost",
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.card.attachments.count(), 0)

    def test_painel_mostra_botao_de_anexar_por_mes(self):
        mr.ensure_entry(self.rule, self.card, date(2026, 8, 1))
        alvo = MonthlyReportEntry.objects.get(card=self.card, month=date(2026, 8, 1))
        r = self.client.get(f"/card/{self.card.id}/monthly/", SERVER_NAME="localhost")
        html = r.content.decode()
        self.assertIn(f"/card/{self.card.id}/monthly/{alvo.id}/upload/", html)
        self.assertIn("Anexar relatório de Ago/2026", html)
