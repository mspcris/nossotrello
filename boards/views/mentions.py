import re
import unicodedata

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.contrib.auth import get_user_model

from boards.models import BoardMembership

MAX_RESULTS = 20
_WORD_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _fold(text: str) -> str:
    """Minúsculas e sem acento: "José" e "JOSE" viram "jose"."""
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _rank(q: str, handle: str, name: str):
    """Posição do usuário na lista para o termo `q` (menor = mais em cima);
    None = não combina. Começo do @ > começo de um nome > meio do @ > meio do nome."""
    if not q:
        return 0
    if handle.startswith(q):
        return 0
    if any(word.startswith(q) for word in _WORD_SPLIT_RE.split(name)):
        return 1
    if q in handle:
        return 2
    if q in name:
        return 3
    return None


@login_required
def board_mentions(request, board_id: int):
    """Sugestões do "@" no card: membros do quadro, buscados pelo nome ou pelo @.

    Quem marca nem sempre sabe o @ da pessoa (ele pode ter mudado), então o
    termo vale também para o nome de exibição e o nome do cadastro. Sem termo
    (só o "@") devolve os membros do quadro. O que entra no texto continua
    sendo o @ (`value`)."""
    q = _fold((request.GET.get("q") or "").lstrip("@"))

    member_user_ids = BoardMembership.objects.filter(
        board_id=board_id
    ).values_list("user_id", flat=True)

    User = get_user_model()

    # Quadro tem poucos membros: filtra em Python para ignorar acento em
    # qualquer banco (icontains do Postgres não ignora).
    users = (
        User.objects
        .filter(id__in=member_user_ids, is_active=True)
        .exclude(profile__handle="")
        .select_related("profile")
    )

    ranked = []
    for u in users:
        p = getattr(u, "profile", None)
        handle = (getattr(p, "handle", "") or "").strip()
        if not handle:
            continue
        display_name = (getattr(p, "display_name", "") or "").strip()
        name = _fold(f"{display_name} {u.first_name} {u.last_name}")
        rank = _rank(q, handle.lower(), name)
        if rank is None:
            continue
        ranked.append((rank, handle.lower(), u, p, handle, display_name))

    ranked.sort(key=lambda item: item[:2])

    results = []
    for _rank_, _key, u, p, handle, display_name in ranked[:MAX_RESULTS]:
        results.append({
            "id": u.id,
            "value": handle,
            "handle": handle,
            "display_name": display_name,
            "avatar_url": (getattr(p, "avatar_url", "") if p else ""),
        })

    return JsonResponse(results, safe=False)
