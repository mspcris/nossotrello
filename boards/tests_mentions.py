"""Menção (@) no card: a lista aparece ao digitar "@" e a busca vale pelo nome
e pelo @ — quem só sabe o nome da pessoa tem que achá-la."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Board, BoardMembership


def _user(username, handle, display_name, first="", last=""):
    u = get_user_model().objects.create_user(
        username=username, email=f"{username}@camim.com.br", password="x",
        first_name=first, last_name=last,
    )
    p = u.profile
    p.terms_accepted = True
    p.terms_version = "2.0"
    p.handle = handle
    p.display_name = display_name
    p.save(update_fields=["terms_accepted", "terms_version", "handle", "display_name"])
    return u


class BoardMentionsSearchTests(TestCase):
    def setUp(self):
        self.eu = _user("cristiano", "crisss", "Cristiano")
        self.isabelle = _user("isabelle.felix", "felix", "Isabelle Felix",
                              first="Isabelle", last="da Silva Felix")
        self.jose = _user("jose.souza", "zeca", "José Souza")
        self.isaias = _user("isaias", "isaias", "Marcos Lima")
        self.fora = _user("isabela.fora", "belinha", "Isabela de Fora")
        self.board = Board.all_objects.create(name="Quadro", created_by=self.eu)
        for u in (self.eu, self.isabelle, self.jose, self.isaias):
            BoardMembership.objects.create(board=self.board, user=u)
        self.client.force_login(self.eu)
        self.url = reverse("boards:board_mentions", args=[self.board.id])

    def _handles(self, q):
        r = self.client.get(self.url, {"q": q})
        self.assertEqual(r.status_code, 200)
        return [item["handle"] for item in r.json()]

    def test_acha_pelo_nome_quando_o_arroba_e_outro(self):
        self.assertIn("felix", self._handles("isab"))

    def test_continua_achando_pelo_arroba(self):
        self.assertEqual(self._handles("fel"), ["felix"])

    def test_acha_pelo_sobrenome_do_cadastro(self):
        self.assertEqual(self._handles("silva"), ["felix"])

    def test_ignora_acento_e_maiuscula(self):
        self.assertEqual(self._handles("JOSE"), ["zeca"])
        self.assertEqual(self._handles("josé"), ["zeca"])

    def test_so_arroba_lista_os_membros_do_quadro(self):
        self.assertEqual(self._handles(""), ["crisss", "felix", "isaias", "zeca"])

    def test_quem_nao_e_do_quadro_nao_aparece(self):
        self.assertNotIn("belinha", self._handles("isab"))

    def test_comeco_do_arroba_ou_do_nome_vem_antes_de_meio_de_palavra(self):
        # "isa": @isaias e Isabelle (começo) antes de quem só tem "isa" no meio
        meio = _user("luisa", "lu", "Luisa Prado")
        BoardMembership.objects.create(board=self.board, user=meio)
        self.assertEqual(self._handles("isa"), ["isaias", "felix", "lu"])

    def test_item_traz_arroba_e_nome_para_a_lista(self):
        r = self.client.get(self.url, {"q": "isab"})
        item = r.json()[0]
        self.assertEqual(item["value"], "felix")
        self.assertEqual(item["display_name"], "Isabelle Felix")
        self.assertEqual(item["id"], self.isabelle.id)
