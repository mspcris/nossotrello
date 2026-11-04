"""Ações rápidas por coluna (PT2-T4U-ALPP): configurar no menu da coluna e
mover o card pelo botão na face do quadro, sem abri-lo."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Board, Card, Column


def _user(username, email):
    u = get_user_model().objects.create_user(username=username, email=email, password="x")
    p = u.profile
    p.terms_accepted = True
    p.terms_version = "2.0"
    p.save(update_fields=["terms_accepted", "terms_version"])
    return u


class QuickActionsTests(TestCase):
    def setUp(self):
        self.user = _user("dona", "dona@camim.com.br")
        self.board = Board.all_objects.create(name="Quadro", created_by=self.user)
        self.col = Column.objects.create(board=self.board, name="Sprint", position=1)
        self.done = Column.objects.create(board=self.board, name="DONE", position=2)
        self.card = Card.all_objects.create(title="Card A", column=self.col,
                                            created_by=self.user, position=0)
        self.client.force_login(self.user)
        self.url = reverse("boards:column_quick_actions_config", args=[self.col.id])

    def test_configura_adiciona_e_remove(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Ações rápidas — Sprint", r.content.decode())
        r = self.client.post(self.url, {"acao": "add", "to": self.done.id, "label": "Testado ✅"})
        self.assertIn("Ação adicionada", r.content.decode())
        self.col.refresh_from_db()
        self.assertEqual(self.col.quick_actions, [{"to": self.done.id, "label": "Testado ✅"}])
        # repetida: não duplica
        self.client.post(self.url, {"acao": "add", "to": self.done.id})
        self.col.refresh_from_db()
        self.assertEqual(len(self.col.quick_actions), 1)
        # a própria coluna não é destino
        self.client.post(self.url, {"acao": "add", "to": self.col.id})
        self.col.refresh_from_db()
        self.assertEqual(len(self.col.quick_actions), 1)
        # remove
        self.client.post(self.url, {"acao": "remove", "to": self.done.id})
        self.col.refresh_from_db()
        self.assertEqual(self.col.quick_actions, [])

    def test_sem_label_usa_nome_da_coluna(self):
        self.client.post(self.url, {"acao": "add", "to": self.done.id})
        self.col.refresh_from_db()
        self.assertEqual(self.col.quick_actions[0]["label"], "DONE")

    def test_botao_aparece_no_card_e_some_se_destino_apagado(self):
        self.col.quick_actions = [{"to": self.done.id, "label": "Pronto"}]
        self.col.save(update_fields=["quick_actions"])
        html = self.client.get(reverse("boards:board_detail", args=[self.board.id])).content.decode()
        self.assertIn("card-qa-btn", html)
        self.assertIn(f'data-qa-to="{self.done.id}"', html)
        self.assertIn("⚡ Pronto", html)
        # carregamento preguiçoso da coluna também traz o botão
        more = self.client.get(reverse("boards:column_cards_more", args=[self.col.id]) + "?offset=0").content.decode()
        self.assertIn("card-qa-btn", more)
        # destino apagado: o botão some sozinho
        self.done.is_deleted = True
        self.done.save(update_fields=["is_deleted"])
        self.assertEqual(self.col.quick_actions_vivas, [])
        html = self.client.get(reverse("boards:board_detail", args=[self.board.id])).content.decode()
        self.assertNotIn("card-qa-btn", html)

    def test_quem_nao_edita_o_quadro_nao_configura(self):
        outro = _user("outro", "outro@camim.com.br")
        self.client.force_login(outro)
        r = self.client.post(self.url, {"acao": "add", "to": self.done.id})
        self.assertEqual(r.status_code, 403)
        self.col.refresh_from_db()
        self.assertEqual(self.col.quick_actions, [])
