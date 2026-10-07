# boards/permissions.py

def can_edit_board(user, board) -> bool:
    """
    Política A (recomendada):
    - superuser: True
    - board com memberships: SOMENTE owner/editor edita; viewer NUNCA edita
    - board legado (sem memberships): somente criador edita
    - staff: NÃO bypassa o compartilhamento do board (segue a regra acima)
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    # Superuser pode tudo (admin do sistema)
    if getattr(user, "is_superuser", False):
        return True

    memberships_qs = getattr(board, "memberships", None)
    if memberships_qs is None:
        # Falha fechada se algo estiver inconsistente
        return False

    # Boards com compartilhamento: a permissão vem EXCLUSIVAMENTE do role
    if memberships_qs.exists():
        role = (
            memberships_qs
            .filter(user=user)
            .values_list("role", flat=True)
            .first()
        )
        role = (role or "").strip().lower()

        # viewer nunca edita
        if role == "viewer":
            return False

        return role in {"owner", "editor"}

    # Board legado: sem memberships => somente criador edita
    created_by_id = getattr(board, "created_by_id", None)
    return bool(created_by_id and created_by_id == user.id)


def can_admin_board(user, board) -> bool:
    """Admin do quadro: ações privilegiadas (ex.: liberar/dispensar um mês do
    relatório mensal). Mais restrito que `can_edit_board` — editor NÃO é admin.

    - superuser: True
    - board com memberships: SOMENTE role 'owner'
    - board legado (sem memberships): somente o criador
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    memberships_qs = getattr(board, "memberships", None)
    if memberships_qs is None:
        return False

    if memberships_qs.exists():
        role = (
            memberships_qs
            .filter(user=user)
            .values_list("role", flat=True)
            .first()
        )
        return (role or "").strip().lower() == "owner"

    created_by_id = getattr(board, "created_by_id", None)
    return bool(created_by_id and created_by_id == user.id)
