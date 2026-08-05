import tempfile
import hashlib
import shutil
import subprocess
import unicodedata
import unittest
from unittest.mock import patch
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings

from boards.models import Board, Card, CardAttachment, CardLog, Column, StoredFile


class MediaServeCompatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="cristiano",
            email="Cristiano@camim.com.br",
            password="secret123",
        )
        profile = cls.user.profile
        profile.terms_accepted = True
        profile.terms_version = "2.0"
        profile.save(update_fields=["terms_accepted", "terms_version"])

    def setUp(self):
        self.client.force_login(self.user)

    def test_serves_stored_file_by_uuid(self):
        stored = StoredFile.objects.create(
            original_name="report.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            data=b"sheet-data",
            size=10,
            checksum="a" * 64,
        )

        response = self.client.get(f"/media/serve/{stored.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"sheet-data")
        self.assertEqual(response["ETag"], '"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"')

    def test_serves_legacy_reference_from_storedfile_by_unique_original_name(self):
        StoredFile.objects.create(
            original_name="legacy-report.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            data=b"legacy-data",
            size=11,
            checksum="b" * 64,
        )

        response = self.client.get("/media/serve/attachments/legacy-report.xlsx/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"legacy-data")

    def test_returns_404_for_ambiguous_legacy_original_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            StoredFile.objects.create(
                original_name="image.png",
                content_type="image/png",
                data=b"first",
                size=5,
                checksum="c" * 64,
            )
            StoredFile.objects.create(
                original_name="image.png",
                content_type="image/png",
                data=b"second",
                size=6,
                checksum="d" * 64,
            )

            with override_settings(MEDIA_ROOT=tmpdir):
                response = self.client.get("/media/serve/attachments/image.png/")

            self.assertEqual(response.status_code, 404)

    def test_serves_legacy_reference_with_unicode_normalization_mismatch(self):
        nfc_name = unicodedata.normalize("NFC", "MODELO_ÁGUA_1_6zkxGYF.xlsx")
        nfd_name = unicodedata.normalize("NFD", "MODELO_ÁGUA_1_6zkxGYF.xlsx")
        self.assertNotEqual(nfc_name, nfd_name)

        StoredFile.objects.create(
            original_name=nfd_name,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            data=b"agua-data",
            size=9,
            checksum="9" * 64,
        )

        response = self.client.get(f"/media/serve/attachments/{nfc_name}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"agua-data")

    def test_falls_back_to_filesystem_for_legacy_reference(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "attachments" / "legacy.txt"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"legacy-fs")

            with override_settings(MEDIA_ROOT=tmpdir):
                response = self.client.get("/media/serve/attachments/legacy.txt/")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), b"legacy-fs")


class RepairLegacyFileRefsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tester",
            email="tester@example.com",
            password="secret123",
        )
        self.board = Board.all_objects.create(name="Board teste", created_by=self.user)
        self.column = Column.objects.create(board=self.board, name="Coluna", position=1)
        self.card = Card.all_objects.create(
            title="Card teste",
            column=self.column,
            created_by=self.user,
            position=1,
        )

    def test_repairs_unique_name_match(self):
        stored = StoredFile.objects.create(
            original_name="legacy-report.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            data=b"legacy-data",
            size=11,
            checksum="e" * 64,
        )
        attachment = CardAttachment.objects.create(
            card=self.card,
            file="attachments/legacy-report.xlsx",
            description="arquivo antigo",
            created_by=self.user,
        )

        call_command("repair_legacy_file_refs", "--apply")

        attachment.refresh_from_db()
        self.board.refresh_from_db()
        self.assertEqual(attachment.file.name, str(stored.id))
        self.assertEqual(self.board.version, 1)

    def test_repairs_ambiguous_name_from_filesystem_checksum(self):
        StoredFile.objects.create(
            original_name="image.png",
            content_type="image/png",
            data=b"first",
            size=5,
            checksum="f" * 64,
        )
        expected = StoredFile.objects.create(
            original_name="image.png",
            content_type="image/png",
            data=b"second",
            size=6,
            checksum=hashlib.sha256(b"second").hexdigest(),
        )
        attachment = CardAttachment.objects.create(
            card=self.card,
            file="attachments/image.png",
            description="ambiguous",
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "attachments" / "image.png"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"second")

            with override_settings(MEDIA_ROOT=tmpdir):
                call_command("repair_legacy_file_refs", "--apply")

        attachment.refresh_from_db()
        self.assertEqual(attachment.file.name, str(expected.id))

    def test_imports_missing_stored_file_from_filesystem(self):
        attachment = CardAttachment.objects.create(
            card=self.card,
            file="attachments/new-file.txt",
            description="importar",
            created_by=self.user,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "attachments" / "new-file.txt"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"new-file-data")

            with override_settings(MEDIA_ROOT=tmpdir):
                call_command("repair_legacy_file_refs", "--apply")

        attachment.refresh_from_db()
        stored = StoredFile.objects.get(id=attachment.file.name)
        self.assertEqual(stored.original_name, "new-file.txt")
        self.assertEqual(bytes(stored.data), b"new-file-data")



from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from boards.models import (
    Board, BoardMembership, Card, CardImpediment, Column, Organization, SocialGroup,
    SocialGroupJoinRequest, SocialGroupMembership, SocialPost, UserProfile,
)

User = get_user_model()


def _mk(username, email):
    from boards.views.legal import CURRENT_TERMS_VERSION
    u = User.objects.create_user(username=username, email=email, password="x")
    p, _ = UserProfile.objects.get_or_create(user=u)
    p.terms_accepted = True
    p.terms_version = CURRENT_TERMS_VERSION
    p.notify_email = True
    p.save()
    return u


class ImpedimentTests(TestCase):
    def setUp(self):
        self.dono = _mk("dono", "dono@camim.com.br")
        self.ricardo = _mk("ricardo", "ricardo@camim.com.br")
        self.editor = _mk("editor", "editor@camim.com.br")
        self.estranho = _mk("estranho", "estranho@x.com")
        self.org = Organization.objects.create(name="C", owner=self.dono)
        self.board = Board.objects.create(name="B", organization=self.org)
        for u, role in [
            (self.dono, BoardMembership.Role.OWNER),
            (self.ricardo, BoardMembership.Role.VIEWER),
            (self.editor, BoardMembership.Role.EDITOR),
        ]:
            BoardMembership.objects.create(board=self.board, user=u, role=role)
        self.col = Column.objects.create(board=self.board, name="Tarefas", position=0)
        self.card = Card.objects.create(column=self.col, title="T", position=0)
        self.set_url = reverse("boards:set_card_impediment", kwargs={"card_id": self.card.id})
        self.clear_url = reverse("boards:clear_card_impediment", kwargs={"card_id": self.card.id})

    def _active(self):
        return list(
            CardImpediment.objects.filter(card=self.card, is_active=True)
            .values_list("user_id", flat=True)
        )

    # -------- set --------

    def test_marca_impedimento_com_responsavel(self):
        self.client.force_login(self.dono)
        r = self.client.post(self.set_url, {"responsibles": [self.ricardo.id]})
        self.assertEqual(r.status_code, 200)
        self.card.refresh_from_db()
        self.assertTrue(self.card.is_impeded)
        self.assertEqual(self._active(), [self.ricardo.id])

    def test_sem_responsavel_recusa(self):
        self.client.force_login(self.dono)
        r = self.client.post(self.set_url, {})
        self.assertEqual(r.status_code, 400)
        self.card.refresh_from_db()
        self.assertFalse(self.card.is_impeded)

    def test_responsavel_precisa_ser_membro(self):
        self.client.force_login(self.dono)
        r = self.client.post(self.set_url, {"responsibles": [self.estranho.id]})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(CardImpediment.objects.exists())

    def test_viewer_nao_marca(self):
        self.client.force_login(self.ricardo)  # viewer
        r = self.client.post(self.set_url, {"responsibles": [self.ricardo.id]})
        self.assertEqual(r.status_code, 403)

    def test_marcar_de_novo_nao_duplica(self):
        self.client.force_login(self.dono)
        self.client.post(self.set_url, {"responsibles": [self.ricardo.id]})
        self.client.post(self.set_url, {"responsibles": [self.ricardo.id]})
        self.assertEqual(
            CardImpediment.objects.filter(card=self.card, user=self.ricardo, is_active=True).count(), 1
        )

    def test_bump_de_versao(self):
        self.board.refresh_from_db(); v0 = self.board.version
        self.client.force_login(self.dono)
        self.client.post(self.set_url, {"responsibles": [self.ricardo.id]})
        self.board.refresh_from_db()
        self.assertGreater(self.board.version, v0)

    # -------- clear --------

    def test_responsavel_limpa_a_propria(self):
        self.client.force_login(self.dono)
        self.client.post(self.set_url, {"responsibles": [self.ricardo.id, self.editor.id]})
        self.client.force_login(self.ricardo)
        r = self.client.post(self.clear_url, {})  # default: a propria
        self.assertEqual(r.status_code, 200)
        self.card.refresh_from_db()
        self.assertTrue(self.card.is_impeded)  # editor ainda trava
        self.assertEqual(self._active(), [self.editor.id])

    def test_card_sai_quando_ultimo_resolve(self):
        self.client.force_login(self.dono)
        self.client.post(self.set_url, {"responsibles": [self.ricardo.id]})
        self.client.force_login(self.ricardo)
        self.client.post(self.clear_url, {})
        self.card.refresh_from_db()
        self.assertFalse(self.card.is_impeded)

    def test_terceiro_nao_limpa_de_outro(self):
        self.client.force_login(self.dono)
        self.client.post(self.set_url, {"responsibles": [self.ricardo.id]})
        # editor NÃO é dono; tentar limpar a pendência do ricardo
        self.client.force_login(self.editor)
        r = self.client.post(self.clear_url, {"user_id": self.ricardo.id})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._active(), [self.ricardo.id])

    def test_dono_limpa_de_qualquer_um(self):
        self.client.force_login(self.dono)
        self.client.post(self.set_url, {"responsibles": [self.ricardo.id]})
        r = self.client.post(self.clear_url, {"user_id": self.ricardo.id})
        self.assertEqual(r.status_code, 200)
        self.card.refresh_from_db()
        self.assertFalse(self.card.is_impeded)

    def test_reativar_apos_resolver(self):
        self.client.force_login(self.dono)
        self.client.post(self.set_url, {"responsibles": [self.ricardo.id]})
        self.client.post(self.clear_url, {"user_id": self.ricardo.id})
        # marca de novo o mesmo: deve reativar, não estourar unique
        r = self.client.post(self.set_url, {"responsibles": [self.ricardo.id]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._active(), [self.ricardo.id])
        # histórico preservado: 1 resolvido + 1 ativo
        self.assertEqual(CardImpediment.objects.filter(card=self.card, user=self.ricardo).count(), 2)


@override_settings(STORAGES={
    "default": {"BACKEND": "boards.storage.DatabaseStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AttachmentSoftDeleteTests(TestCase):
    """Remover anexo NUNCA pode apagar linha nem bytes (regra do projeto).

    Ponto crítico: `django_cleanup` está no INSTALLED_APPS e apaga o arquivo do
    storage no post_delete de qualquer FileField. Como o DatabaseStorage
    deduplica por checksum, um delete físico levava junto o blob compartilhado
    com OUTROS cards. Daí o soft-delete ser obrigatório aqui.
    """

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="anexos", email="anexos@example.com", password="secret123",
        )
        self.board = Board.all_objects.create(name="Board anexos", created_by=self.user)
        self.column = Column.objects.create(board=self.board, name="Coluna", position=1)
        self.card = Card.all_objects.create(
            title="Card anexos", column=self.column, created_by=self.user, position=1,
        )
        # TermsMiddleware barra quem não aceitou os termos
        from boards.views.legal import CURRENT_TERMS_VERSION
        profile = self.user.profile
        profile.terms_accepted = True
        profile.terms_version = CURRENT_TERMS_VERSION
        profile.save(update_fields=["terms_accepted", "terms_version"])

        self.client.force_login(self.user)

    def _upload(self, name=b"conteudo", filename="Relatorio Assinado.PDF"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post(
            f"/card/{self.card.id}/attachments/add/",
            {"file": SimpleUploadedFile(filename, name, content_type="application/pdf")},
        )

    def test_storage_nao_apaga_bytes_ainda_referenciados(self):
        """O mesmo arquivo em dois cards é UMA linha de StoredFile (dedupe).

        Antes do soft-delete, apagar o anexo de um card fazia o django_cleanup
        chamar storage.delete() e levar os bytes do OUTRO card junto — 18
        anexos morreram assim até 07/2026. O storage agora recusa.
        """
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.files.storage import default_storage

        outro_card = Card.all_objects.create(
            title="Outro", column=self.column, created_by=self.user, position=9,
        )
        self._upload()
        self.client.post(
            f"/card/{outro_card.id}/attachments/add/",
            {"file": SimpleUploadedFile(
                "Relatorio Assinado.PDF", b"conteudo", content_type="application/pdf"
            )},
        )

        a1 = CardAttachment.objects.get(card=self.card)
        a2 = CardAttachment.objects.get(card=outro_card)
        self.assertEqual(a1.file.name, a2.file.name, "dedupe por checksum deveria unir os dois")

        key = a1.file.name
        default_storage.delete(key)
        self.assertTrue(
            StoredFile.objects.filter(id=key).exists(),
            "storage apagou bytes que ainda tinham dono",
        )

        # sem nenhum dono, aí sim pode sair
        CardAttachment.all_objects.filter(file=key).delete()
        CardLog.objects.filter(attachment=key).delete()
        default_storage.delete(key)
        self.assertFalse(StoredFile.objects.filter(id=key).exists())

    def test_anexo_com_bytes_sumidos_e_marcado_como_indisponivel(self):
        """Chave órfã não pode virar link que devolve 404."""
        from boards.services.file_meta import file_meta

        self._upload()
        attachment = CardAttachment.objects.get(card=self.card)
        key = attachment.file.name

        self.assertFalse(file_meta(attachment.file)["missing"])

        # simula o estrago antigo: bytes fora, linha do anexo de pé
        StoredFile.objects.filter(id=key).delete()
        cache.delete(f"sfmeta:{key}")

        self.assertTrue(file_meta(attachment.file)["missing"])

    def test_video_sem_extensao_no_nome_ainda_e_tratado_como_video(self):
        """Gravador de tela salva "video-2026-08-01_12.03.56" — sem extensão.

        O navegador manda application/octet-stream, e o ".56" do horário era
        lido como extensão: o anexo virava arquivo comum e perdia miniatura,
        player e conversão. Quem decide agora são os bytes.
        """
        from django.core.files.uploadedfile import SimpleUploadedFile
        from boards.services.file_meta import file_meta

        # cabeçalho EBML/WebM real
        webm = bytes.fromhex(
            "1a45dfa39f4286810142f7810142f2810442f381084282847765626d42878102"
        ) + b"\x00" * 128

        self.client.post(
            f"/card/{self.card.id}/attachments/add/",
            {
                "file": SimpleUploadedFile(
                    "video-2026-08-01_12.03.56",
                    webm,
                    content_type="application/octet-stream",
                )
            },
        )

        attachment = CardAttachment.objects.get(card=self.card)
        stored = StoredFile.objects.get(id=attachment.file.name)
        self.assertEqual(stored.content_type, "video/webm")

        meta = file_meta(attachment.file)
        self.assertEqual(meta["kind"], "video")
        self.assertEqual(meta["ext"], "WEBM")
        self.assertEqual(meta["name"], "video-2026-08-01_12.03.56")

        # e o feed registra como vídeo, não como "um arquivo"
        log = self.card.logs.filter(attachment__gt="").first()
        self.assertIn("anexou um vídeo", log.content)

    def test_content_type_declarado_vence_o_palpite_dos_bytes(self):
        """Só chuta quando o navegador não soube dizer — nunca por cima dele."""
        from boards.services.file_sniff import resolve_content_type

        webm = bytes.fromhex("1a45dfa39f428681") + b"webm" + b"\x00" * 64
        self.assertEqual(resolve_content_type("video/mp4", webm), "video/mp4")
        self.assertEqual(resolve_content_type("application/octet-stream", webm), "video/webm")
        # sem assinatura conhecida, mantém o que veio
        self.assertEqual(
            resolve_content_type("application/octet-stream", b"nada disso" * 8),
            "application/octet-stream",
        )

    def test_upload_guarda_nome_original_e_loga_o_tipo(self):
        self._upload()

        attachment = CardAttachment.objects.get(card=self.card)
        stored = StoredFile.objects.get(id=attachment.file.name)
        # o Django sanitiza o nome no upload; é esse que o download devolve
        self.assertEqual(stored.original_name, "Relatorio_Assinado.PDF")

        # A linha do feed diz só QUE anexou e de que tipo: o nome do arquivo
        # aparece no cartão do anexo logo abaixo, renderizado de log.attachment.
        log = self.card.logs.filter(attachment__gt="").first()
        self.assertIn("anexou um PDF", log.content)
        self.assertNotIn(str(stored.id), log.content)

        from boards.services.file_meta import file_meta
        self.assertEqual(
            file_meta(attachment.file),
            {"name": "Relatorio_Assinado.PDF", "ext": "PDF", "kind": "pdf", "missing": False},
        )
        # é daqui que o template tira o nome mostrado no feed
        self.assertEqual(file_meta(log.attachment)["name"], "Relatorio_Assinado.PDF")

    def test_delete_e_soft_e_preserva_bytes(self):
        self._upload()
        attachment = CardAttachment.objects.get(card=self.card)
        stored_id = attachment.file.name

        response = self.client.post(
            f"/card/{self.card.id}/attachments/{attachment.id}/delete/"
        )
        self.assertEqual(response.status_code, 200)

        # linha continua existindo, só saiu de circulação
        self.assertFalse(CardAttachment.objects.filter(id=attachment.id).exists())
        self.assertTrue(CardAttachment.all_objects.filter(id=attachment.id).exists())
        dead = CardAttachment.all_objects.get(id=attachment.id)
        self.assertFalse(dead.is_active)
        self.assertIsNotNone(dead.deleted_at)

        # bytes intactos (django_cleanup não pode ter sido acionado)
        self.assertTrue(StoredFile.objects.filter(id=stored_id).exists())

        # sumiu da lista do card e o feed marca como removido
        self.assertEqual(list(self.card.attachments.all()), [])
        self.assertTrue(
            self.card.logs.filter(attachment=stored_id, attachment_deleted=True).exists()
        )

    def test_blob_compartilhado_sobrevive_a_remocao_em_outro_card(self):
        self._upload()
        other_card = Card.all_objects.create(
            title="Outro card", column=self.column, created_by=self.user, position=2,
        )
        first = CardAttachment.objects.get(card=self.card)
        shared = CardAttachment.objects.create(card=other_card, file=first.file.name)

        self.client.post(f"/card/{self.card.id}/attachments/{first.id}/delete/")

        shared.refresh_from_db()
        self.assertTrue(StoredFile.objects.filter(id=shared.file.name).exists())
        self.assertEqual([a.id for a in other_card.attachments.all()], [shared.id])


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg ausente")
class VideoThumbTests(TestCase):
    """Vídeo anexado ganha miniatura do 1º frame (ffmpeg)."""

    def _make_video(self, duration="3", size="640x360"):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "v.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi",
                 "-i", f"testsrc=size={size}:rate=15:duration={duration}",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                capture_output=True, timeout=60,
            )
            return path.read_bytes()

    def _store(self, data, name="reuniao.mp4", content_type="video/mp4"):
        return StoredFile.objects.create(
            original_name=name, content_type=content_type,
            data=data, size=len(data), checksum=hashlib.sha256(data).hexdigest(),
        )

    def test_extrai_frame_e_memoiza(self):
        from boards.services.attach_thumbs import thumb_url_for_fieldfile

        stored = self._store(self._make_video())

        class FieldFile:
            name = str(stored.id)

        url = thumb_url_for_fieldfile(FieldFile())
        thumb = StoredFile.objects.get(original_name=f"vidthumb::{stored.id}.jpg")
        self.assertEqual(url, f"/media/serve/{thumb.id}/")
        self.assertEqual(thumb.content_type, "image/jpeg")
        self.assertGreater(thumb.size, 0)

        # 2ª chamada não pode regerar
        total = StoredFile.objects.count()
        thumb_url_for_fieldfile(FieldFile())
        self.assertEqual(StoredFile.objects.count(), total)

    def test_video_mais_curto_que_o_seek_ainda_gera(self):
        from boards.services.video_thumbs import _extract_frame_jpeg
        # 0.2s: o seek de 0.5s passa do fim, tem que cair no frame 0
        self.assertTrue(_extract_frame_jpeg(self._make_video(duration="0.2")))

    def test_arquivo_invalido_nao_gera_miniatura(self):
        from boards.services.attach_thumbs import thumb_url_for_fieldfile

        stored = self._store(b"isso nao e um video", name="quebrado.mp4")

        class FieldFile:
            name = str(stored.id)

        self.assertEqual(thumb_url_for_fieldfile(FieldFile()), "")

    def test_kind_video_reconhecido_por_extensao_e_content_type(self):
        from boards.services.file_meta import file_meta

        stored = self._store(b"x", name="sem-content-type.mov", content_type="")

        class FieldFile:
            name = str(stored.id)

        meta = file_meta(FieldFile())
        self.assertEqual(meta["kind"], "video")
        self.assertEqual(meta["ext"], "MOV")


class SocialGroupAccessTests(TestCase):
    def setUp(self):
        self.owner = _mk("groupowner", "groupowner@example.com")
        self.manager = _mk("groupmanager", "groupmanager@example.com")
        self.requester = _mk("grouprequester", "grouprequester@example.com")
        self.member = _mk("groupmember", "groupmember@example.com")
        self.group = SocialGroup.objects.create(
            name="Comunidade Fechada",
            created_by=self.owner,
        )
        SocialGroupMembership.objects.create(
            group=self.group,
            user=self.owner,
            invited_by=self.owner,
            role=SocialGroupMembership.ROLE_OWNER,
        )
        SocialGroupMembership.objects.create(
            group=self.group,
            user=self.manager,
            invited_by=self.owner,
            role=SocialGroupMembership.ROLE_MANAGER,
        )
        SocialGroupMembership.objects.create(
            group=self.group,
            user=self.member,
            invited_by=self.owner,
            role=SocialGroupMembership.ROLE_MEMBER,
        )
        for user, handle, name in [
            (self.owner, "ownergroup", "Dono Grupo"),
            (self.manager, "lucas", "Lucas Paes"),
            (self.member, "maria", "Maria Silva"),
            (self.requester, "fora", "Pessoa de Fora"),
        ]:
            user.last_login = timezone.now()
            user.save(update_fields=["last_login"])
            profile = user.profile
            profile.handle = handle
            profile.display_name = name
            profile.save(update_fields=["handle", "display_name"])

    def test_join_creates_request_instead_of_membership(self):
        self.client.force_login(self.requester)

        response = self.client.post(reverse("boards:group_join", args=[self.group.slug]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            SocialGroupMembership.objects.filter(group=self.group, user=self.requester).exists()
        )
        self.assertTrue(
            SocialGroupJoinRequest.objects.filter(group=self.group, user=self.requester).exists()
        )

    def test_manager_can_approve_request(self):
        SocialGroupJoinRequest.objects.create(group=self.group, user=self.requester)
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("boards:group_request_approve", args=[self.group.slug, self.requester.id])
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            SocialGroupMembership.objects.filter(group=self.group, user=self.requester).exists()
        )
        self.assertFalse(
            SocialGroupJoinRequest.objects.filter(group=self.group, user=self.requester).exists()
        )

    def test_manager_can_remove_member(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("boards:group_member_remove", args=[self.group.slug, self.member.id])
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            SocialGroupMembership.objects.filter(group=self.group, user=self.member).exists()
        )

    def test_member_can_search_mentions_only_within_group(self):
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("boards:group_mention_search", args=[self.group.slug]),
            {"q": "lu"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["handle"], "lucas")

    def test_non_member_does_not_receive_group_mentions_search_results(self):
        self.client.force_login(self.requester)

        response = self.client.get(
            reverse("boards:group_mention_search", args=[self.group.slug]),
            {"q": "ma"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_manager_sees_remove_action_on_group_detail(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("boards:group_detail", args=[self.group.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Você pode retirar membros daqui.")
        self.assertContains(response, "Retirar")
        self.assertContains(response, "Cutucar")

    def test_member_does_not_see_remove_action_on_group_detail(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse("boards:group_detail", args=[self.group.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Você pode retirar membros daqui.")
        self.assertNotContains(response, "Retirar</button>", html=False)
        self.assertNotContains(response, "Cutucar</button>", html=False)

    def test_manager_does_not_see_nudge_action_for_member_with_group_post(self):
        SocialPost.objects.create(
            user=self.member,
            group=self.group,
            text="Já publiquei aqui",
            show_on_profile=False,
        )
        self.client.force_login(self.manager)

        response = self.client.get(reverse("boards:group_detail", args=[self.group.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Cutucar</button>", html=False)

    @patch("boards.services.notifications.notify_group_nudge")
    def test_manager_can_nudge_member_without_group_posts(self, notify_group_nudge):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("boards:group_member_nudge", args=[self.group.slug, self.member.id])
        )

        self.assertEqual(response.status_code, 302)
        notify_group_nudge.assert_called_once_with(
            recipient=self.member,
            actor=self.manager,
            group=self.group,
        )

    @patch("boards.services.notifications.notify_group_nudge")
    def test_member_cannot_nudge_another_member(self, notify_group_nudge):
        other_member = _mk("groupfriend", "groupfriend@example.com")
        other_member.profile.handle = "ana"
        other_member.profile.display_name = "Ana"
        other_member.profile.save(update_fields=["handle", "display_name"])
        SocialGroupMembership.objects.create(
            group=self.group,
            user=other_member,
            invited_by=self.owner,
            role=SocialGroupMembership.ROLE_MEMBER,
        )
        self.client.force_login(self.member)

        response = self.client.post(
            reverse("boards:group_member_nudge", args=[self.group.slug, other_member.id])
        )

        self.assertEqual(response.status_code, 403)
        notify_group_nudge.assert_not_called()

    @patch("boards.services.notifications.notify_group_nudge")
    def test_manager_cannot_nudge_member_who_already_posted(self, notify_group_nudge):
        SocialPost.objects.create(
            user=self.member,
            group=self.group,
            text="Já participei",
            show_on_profile=False,
        )
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("boards:group_member_nudge", args=[self.group.slug, self.member.id])
        )

        self.assertEqual(response.status_code, 403)
        notify_group_nudge.assert_not_called()

    def test_manager_can_delete_group_post(self):
        post = SocialPost.objects.create(
            user=self.member,
            group=self.group,
            text="post para moderar",
            show_on_profile=False,
        )
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("boards:group_post_delete", args=[self.group.slug, post.id])
        )

        self.assertEqual(response.status_code, 302)
        post.refresh_from_db()
        self.assertFalse(post.is_active)
        self.assertEqual(post.moderation_status, SocialPost.MOD_REMOVED)
