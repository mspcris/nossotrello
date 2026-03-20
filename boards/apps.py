from django.apps import AppConfig


class BoardsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'boards'

    def ready(self):
        from . import signals  # noqa

        # ── SQLite WAL mode ──────────────────────────────────────────────
        # Habilita WAL journal para leituras simultâneas enquanto grava,
        # reduz lock contention dramaticamente.
        # synchronous=NORMAL: seguro e muito mais rápido que FULL.
        # cache_size=-32000: 32 MB de cache em memória por conexão.
        # mmap_size: I/O mapeado em memória para reads sequenciais.
        # busy_timeout: espera até 5s antes de retornar SQLITE_BUSY.
        from django.db.backends.signals import connection_created

        def _activate_sqlite_wal(sender, connection, **kwargs):
            if connection.vendor != 'sqlite':
                return
            with connection.cursor() as cur:
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.execute("PRAGMA cache_size=-32000")
                cur.execute("PRAGMA temp_store=MEMORY")
                cur.execute("PRAGMA mmap_size=268435456")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.execute("PRAGMA wal_autocheckpoint=1000")

        connection_created.connect(_activate_sqlite_wal)
