# nossotrello/db_routers.py
"""Router do alias `hesk`: o Tarefas só LÊ o cadastro de gestores do Hesk.

Nenhum model é migrado nem escrito lá — quem manda no schema é o projeto Hesk.
Todos os models do Tarefas continuam no `default`.
"""


class ReadOnlyHeskRouter:
    def db_for_read(self, model, **hints):
        return None  # default

    def db_for_write(self, model, **hints):
        return None  # default — nunca "hesk"

    def allow_relation(self, obj1, obj2, **hints):
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == "hesk":
            return False
        return None
