"""Ações rápidas por coluna (PT2-T4U-ALPP): configurar no menu da coluna; o
"Mover rápido" do card (menu ⋮) passa a mostrar as ações configuradas."""
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

    def test_mover_rapido_mostra_as_acoes_configuradas(self):
        url = reverse("boards:card_move_suggestions", args=[self.card.id])
        # Sem configuração: sugestões por frequência (vazias aqui) + atalho Gerenciar.
        d = self.client.get(url).json()
        self.assertFalse(d["configured"])
        self.assertEqual(d["manage_url"], self.url)
        # Configurada: o Mover rápido mostra a ação, com o texto escolhido.
        self.col.quick_actions = [{"to": self.done.id, "label": "Pronto"}]
        self.col.save(update_fields=["quick_actions"])
        d = self.client.get(url).json()
        self.assertTrue(d["configured"])
        self.assertEqual([(x["to_column_id"], x["to_column_name"]) for x in d["suggestions"]],
                         [(self.done.id, "Pronto")])
        # Destino apagado: some sozinho e volta ao modo frequência.
        self.done.is_deleted = True
        self.done.save(update_fields=["is_deleted"])
        self.assertEqual(self.col.quick_actions_vivas, [])
        self.assertFalse(self.client.get(url).json()["configured"])

    def test_face_do_card_nao_ganha_botao_extra(self):
        self.col.quick_actions = [{"to": self.done.id, "label": "Pronto"}]
        self.col.save(update_fields=["quick_actions"])
        html = self.client.get(reverse("boards:board_detail", args=[self.board.id])).content.decode()
        self.assertNotIn("card-qa-btn", html)

    def test_quem_nao_edita_o_quadro_nao_configura(self):
        outro = _user("outro", "outro@camim.com.br")
        self.client.force_login(outro)
        r = self.client.post(self.url, {"acao": "add", "to": self.done.id})
        self.assertEqual(r.status_code, 403)
        self.col.refresh_from_db()
        self.assertEqual(self.col.quick_actions, [])
