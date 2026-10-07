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


def can_waive_monthly(user) -> bool:
    """Quem pode LIBERAR (dispensar) um mês do relatório mensal.

    Regra de negócio (Cristiano, 06/10/2026): uma DUPLA FIXA de administradores
    da rede, definida em settings.RELATORIO_MENSAL_LIBERADORES (por e-mail) —
    NÃO o dono de cada quadro, senão o gestor do próprio posto se auto-perdoaria.
    Independe do papel (owner/editor/viewer) e de ser superusuário.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    from django.conf import settings
    email = (getattr(user, "email", "") or "").strip().lower()
    if not email:
        return False
    allowed = {e.strip().lower() for e in getattr(settings, "RELATORIO_MENSAL_LIBERADORES", [])}
    return email in allowed
