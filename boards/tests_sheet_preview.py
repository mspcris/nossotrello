"""Visualizador de planilha (boards/services/sheet_preview.py + rota da prévia)."""
import io
from datetime import date, datetime

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from boards.models import Board, BoardMembership, Card, CardAttachment, Column
from boards.services import sheet_preview
from boards.services.file_meta import file_meta


def _xlsx_bytes():
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Agenda"
    ws.append(["Data", "Posto", "Atendimentos", "Ticket"])
    ws.append([datetime(2026, 5, 4), "NOVA IGUAÇU", 128, 42.5])
    ws.append([date(2026, 5, 5), "NOVA IGUAÇU", 96, 40.0])
    wb.create_sheet("Resumo").append(["Total", 224])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class SheetPreviewServiceTests(TestCase):
    def test_le_xlsx_com_datas_e_decimais_em_pt_br(self):
        att = _fake_file(_xlsx_bytes(), "RELATORIO.xlsx")
        out = sheet_preview.read(att, "xlsx")
        self.assertNotIn("error", out)
        self.assertEqual(len(out["sheets"]), 2)
        agenda = out["sheets"][0]
        self.assertEqual(agenda["title"], "Agenda")
        self.assertEqual(agenda["rows"][0], ["Data", "Posto", "Atendimentos", "Ticket"])
        self.assertEqual(agenda["rows"][1][0], "04/05/2026")
        self.assertEqual(agenda["rows"][1][2], "128")       # int não vira "128.0"
        self.assertEqual(agenda["rows"][1][3], "42,5")      # decimal com vírgula
        self.assertEqual(agenda["rows"][2][3], "40")        # 40.0 -> "40"

    def test_csv_com_ponto_e_virgula(self):
        att = _fake_file("Mes;Valor\r\nMai;1200\r\n".encode("utf-8"), "dados.csv")
        out = sheet_preview.read(att, "csv", title="dados.csv")
        self.assertEqual(out["sheets"][0]["rows"], [["Mes", "Valor"], ["Mai", "1200"]])

    def test_csv_latin1_nao_quebra(self):
        att = _fake_file("Mês,Situação\r\nMaio,Pendência\r\n".encode("latin-1"), "d.csv")
        out = sheet_preview.read(att, "csv")
        self.assertEqual(out["sheets"][0]["rows"][1], ["Maio", "Pendência"])

    def test_formato_nao_suportado_e_arquivo_corrompido(self):
        att = _fake_file(b"nada", "foto.png")
        self.assertIn("error", sheet_preview.read(att, "png"))
        att = _fake_file(b"isso nao e um xlsx", "quebrado.xlsx")
        self.assertIn("error", sheet_preview.read(att, "xlsx"))

    def test_file_meta_classifica_planilha(self):
        self.assertEqual(file_meta(_fake_file(b"", "x.xlsx")).get("kind"), "sheet")
        self.assertEqual(file_meta(_fake_file(b"", "x.csv")).get("kind"), "sheet")


class _Fake:
    """Mínimo que `sheet_preview.read` usa de um FieldFile."""

    def __init__(self, data, name):
        self.name = name
        self._buf = io.BytesIO(data)

    def open(self, mode="rb"):
        self._buf.seek(0)
        return self

    def read(self):
        return self._buf.getvalue()

    def close(self):
        pass


def _fake_file(data, name):
    return _Fake(data, name)


class SheetPreviewViewTests(TestCase):
    def setUp(self):
        from django.conf import settings as dj

        User = get_user_model()
        self.owner = User.objects.create_user(username="dono", email="dono@camim.com.br", password="x")
        prof = self.owner.profile
        prof.terms_accepted = True
        prof.terms_version = getattr(dj, "CURRENT_TERMS_VERSION", "2.0")
        prof.save()
        self.board = Board.objects.create(name="NOVA IGUAÇU", created_by=self.owner)
        BoardMembership.objects.create(board=self.board, user=self.owner, role="owner")
        self.col = Column.objects.create(board=self.board, name="Relatórios", position=0)
        self.card = Card.objects.create(column=self.col, title="Agenda médica", created_by=self.owner)
        self.att = CardAttachment.objects.create(
            card=self.card,
            file=SimpleUploadedFile("RELATORIO_AGENDA_MEDICA.xlsx", _xlsx_bytes()),
            created_by=self.owner,
        )
        self.client.force_login(self.owner)

    def test_previa_devolve_linhas(self):
        r = self.client.get(
            f"/card/{self.card.id}/attachments/{self.att.id}/sheet/", SERVER_NAME="localhost"
        )
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["sheets"][0]["rows"][0][0], "Data")
        self.assertTrue(d["download_url"])

    def test_sem_acesso_ao_board(self):
        from django.conf import settings as dj

        User = get_user_model()
        outro = User.objects.create_user(username="zé", email="ze@camim.com.br", password="x")
        prof = outro.profile
        prof.terms_accepted = True
        prof.terms_version = getattr(dj, "CURRENT_TERMS_VERSION", "2.0")
        prof.save()
        self.client.force_login(outro)
        r = self.client.get(
            f"/card/{self.card.id}/attachments/{self.att.id}/sheet/", SERVER_NAME="localhost"
        )
        self.assertEqual(r.status_code, 403)

    def test_link_da_aba_anexos_abre_o_visualizador(self):
        r = self.client.get(f"/card/{self.card.id}/modal/", SERVER_NAME="localhost")
        html = r.content.decode()
        self.assertIn(f"/card/{self.card.id}/attachments/{self.att.id}/sheet/", html)
        self.assertIn("data-sheet-src", html)
