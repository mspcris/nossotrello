"""Telefone do cadastro -> número da Evolution (boards/services/notifications.py)."""
from django.test import SimpleTestCase

from boards.services.notifications import _safe_digits_phone


class SafeDigitsPhoneTests(SimpleTestCase):
    def test_zero_de_tronco_do_cadastro_do_idcamim(self):
        # "(021) 9…" é o formato que vem do IDCamim/ERP. Antes saía "0219…" ou
        # "55021…" e a Evolution respondia exists:false.
        self.assertEqual(_safe_digits_phone("(021) 96625-7803"), "5521966257803")
        self.assertEqual(_safe_digits_phone("(021) 2455-9602"), "552124559602")
        self.assertEqual(_safe_digits_phone("(048) 99912-3480"), "5548999123480")
        self.assertEqual(_safe_digits_phone("021966257803"), "5521966257803")

    def test_discagem_internacional_com_zeros(self):
        self.assertEqual(_safe_digits_phone("0055 21 96625-7803"), "5521966257803")

    def test_formatos_que_ja_funcionavam_continuam_iguais(self):
        self.assertEqual(_safe_digits_phone("21 96625-7803"), "5521966257803")
        self.assertEqual(_safe_digits_phone("2124559602"), "552124559602")
        self.assertEqual(_safe_digits_phone("+55 (21) 96625-7803"), "5521966257803")
        self.assertEqual(_safe_digits_phone("5521966257803"), "5521966257803")
        self.assertEqual(_safe_digits_phone("552124559602"), "552124559602")

    def test_so_o_numero_assume_rio(self):
        self.assertEqual(_safe_digits_phone("96625-7803"), "5521966257803")
        self.assertEqual(_safe_digits_phone("2455-9602"), "552124559602")

    def test_numero_de_fora_do_brasil_nao_e_mexido(self):
        self.assertEqual(_safe_digits_phone("+351 912 345 678"), "351912345678")

    def test_lixo_vira_vazio(self):
        for raw in ("", None, "abc", "0", "00", "1234", "12", "(021)", "0000000000000"):
            self.assertEqual(_safe_digits_phone(raw), "", raw)
