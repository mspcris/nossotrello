"""Link de anexo do HESK dentro do card → anexo equivalente que já vive aqui.

O HESK copia os anexos do chamado para dentro do card e grava a descrição com
/media/serve/<uuid>/. Mas quem estava com o card ABERTO no navegador ainda tinha
o HTML antigo (https://hesk.camim.com.br/anexo/<token>/<nome>) no editor, e o
autosave gravou por cima — sem log no feed, porque o texto puro é igual. Foi
assim que o card 21423 voltou a mandar o Janderson para o login do HESK em
31/08/2026, meia hora depois de corrigido.

Este módulo é a trava do lado de cá: em todo salvamento de descrição, cada URL
/anexo/ do HESK cujo nome bate com UM anexo vivo do card é trocada pelo
/media/serve/ desse anexo. Sem correspondência única (dois "image.png"), a URL
fica como está — o cron do HESK saneia em até 5 min.
"""
import re
from urllib.parse import unquote

HESK_ANEXO_RE = re.compile(
    r"https?://[^\s\"'<>]*?/anexo/([0-9a-f]{32})/?([^\s\"'<>]*)", re.I)


def _nome_seguro(nome: str) -> str:
    """Mesma regra do HESK (_anexo_pub_url): só [A-Za-z0-9._-], 80 chars."""
    return (re.sub(r"[^A-Za-z0-9._-]", "_", nome or "")[:80] or "arquivo").lower()


def reapontar_anexos_hesk(card, html: str) -> str:
    if not html or "/anexo/" not in html:
        return html
    try:
        anexos = list(card.attachments.select_related().all())
    except Exception:
        return html
    if not anexos:
        return html
    por_nome = {}
    for a in anexos:
        nomes = {(a.description or "").strip(), }
        try:
            from boards.models import StoredFile
            sf = StoredFile.objects.filter(id=a.file.name).only("original_name").first()
            if sf and sf.original_name:
                nomes.add(sf.original_name.strip())
        except Exception:
            pass
        for n in nomes:
            if n:
                por_nome.setdefault(_nome_seguro(n), set()).add(a.file.name)

    def _sub(m):
        nome = unquote(m.group(2) or "").split("?")[0].split("#")[0].strip()
        alvo = por_nome.get(_nome_seguro(nome)) if nome else None
        if alvo and len(alvo) == 1:
            return f"/media/serve/{next(iter(alvo))}/"
        return m.group(0)

    return HESK_ANEXO_RE.sub(_sub, html)
