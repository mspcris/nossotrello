# boards/urls.py
"""
URLs do app boards — versão "limpa" (imports explícitos por módulo).

Objetivo:
- Remover dependência de reexport via boards/views/__init__.py (import *)
- Evitar colisão de nomes e AttributeError em runtime
- Manter os mesmos names (compatibilidade com templates/front)

Ponto de atenção:
- Este app expõe rotas de AUTH com namespace "boards".
"""

from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views  # mantém apenas o que realmente está em boards/views/__init__.py (ex: first_login)

from .views import cards as cards_views
from .views import checklists as checklist_views
from .views import calendar as calendar_views
from .views.mentions import board_mentions
from .views.polling import board_poll

from boards.views.modal_card_term import set_card_term_due, set_board_term_colors


from .views.activity import (
    activity_panel,
    add_activity,
    cards_unread_activity,
    quill_upload,
)

from boards.views.account import (
public_profile,
)

# Módulo "boards" (boards/views/boards.py)
from boards.views.boards import (
    # core
    index,
    board_detail,
    add_board,
    rename_board,
    delete_board,
    board_leave,
    board_share,
    board_share_remove,
    toggle_aggregator_column,
    # access request
    request_board_access,
    approve_board_access,
    deny_board_access,
    # transfer ownership
    transfer_owner_start,
    transfer_owner_confirm,
    # wallpaper / image
    update_board_wallpaper,
    remove_board_wallpaper,
    board_wallpaper_css,
    update_board_image,
    remove_board_image,
    # home wallpaper
    update_home_wallpaper,
    remove_home_wallpaper,
    home_wallpaper_css,
    # home groups / favorites
    home_group_create,
    home_group_rename,
    home_group_delete,
    home_group_item_add,
    home_group_item_remove,
    home_favorite_toggle,
)

from boards.views.boards_state import (
    boards_trash,
    boards_archived,
    archive_board,
    unarchive_board,
    trash_board,
    restore_board,
)


# Outros módulos (pelo seu urls atual)

from .views.search import board_search, home_search

# Colunas (assumindo boards/views/columns.py)
from .views import columns as columns_views

# Attachments / Quill (assumindo boards/views/attachments.py e boards/views/activity.py ou afins)
from .views import attachments as attachments_views

from .views import cards_state as cards_state_views

from boards.views.column_follow import toggle_column_follow


app_name = "boards"

urlpatterns = [
    # ============================================================
    # HOME (lista de quadros)
    # ============================================================
    path("", index, name="boards_index"),

    # ============================================================
    # PERFIL PÚBLICO (rota curta por handle)
    # ============================================================
    path("u/<str:handle>/", public_profile, name="public_profile"),

    # ============================================================
    # AUTH / CONTAS (login/logout/primeiro login/recuperação senha)
    # ============================================================
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/first-login/", views.first_login, name="first_login"),
    path(
        "accounts/password_reset/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.txt",
            html_email_template_name="registration/password_reset_email.html",
            subject_template_name="registration/password_reset_subject.txt",
            success_url=reverse_lazy("boards:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "accounts/password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url=reverse_lazy("boards:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),

    # ============================================================
    # ADMIN / USUÁRIOS (opcional)
    # ============================================================
    path("users/create/", views.create_user, name="create_user"),

    # ============================================================
    # BOARDS — CRUD / VISUALIZAÇÃO / AÇÕES DE QUADRO
    # ============================================================
    path("board/add/", add_board, name="add_board"),
    path("board/<int:board_id>/", board_detail, name="board_detail"),
    path("board/<int:board_id>/search/", board_search, name="board_search"),
    path("board/<int:board_id>/rename/", rename_board, name="rename_board"),
    path("board/<int:board_id>/delete/", delete_board, name="delete_board"),
    path("board/<int:board_id>/leave/", board_leave, name="board_leave"),



    path("board/<int:board_id>/archive/", archive_board, name="archive_board"),
    path("board/<int:board_id>/unarchive/", unarchive_board, name="unarchive_board"),

    path("board/<int:board_id>/trash-board/", trash_board, name="trash_board"),
    path("board/<int:board_id>/restore/", restore_board, name="restore_board"),
    path("boards/trash/", boards_trash, name="boards_trash"),
    path("boards/archived/", boards_archived, name="boards_archived"),


    # ============================================================
    # CARDS — Arquivo / Lixeira (Cards)
    # ============================================================
    
    path("card/<int:card_id>/archive/", cards_state_views.archive_card, name="archive_card"),
    path("card/<int:card_id>/unarchive/", cards_state_views.unarchive_card, name="unarchive_card"),
    path("card/<int:card_id>/trash/", cards_state_views.trash_card, name="trash_card"),
    path("card/<int:card_id>/restore/", cards_state_views.restore_card, name="restore_card"),
    # CARDS — Arquivo / Lixeira (PÁGINAS)
    path("board/<int:board_id>/trash/", cards_state_views.trash, name="trash"),
    path("board/<int:board_id>/archived/", cards_state_views.archived, name="archived"),



    # ============================================================
    # BOARDS — COMPARTILHAMENTO (modal + remove membro)
    # ============================================================
    path("board/<int:board_id>/share/", board_share, name="board_share"),
    path("board/<int:board_id>/share/submit/", board_share, name="board_share_submit"),
    path(
        "board/<int:board_id>/share/remove/<int:user_id>/",
        board_share_remove,
        name="board_share_remove",
    ),

    # ============================================================
    # BOARDS — ACESSO SEM CONVITE (solicitar / aprovar / negar)
    # ============================================================
    path(
        "boards/<int:board_id>/request-access/",
        request_board_access,
        name="board_request_access",
    ),
    path(
        "boards/<int:board_id>/approve-access/<int:user_id>/",
        approve_board_access,
        name="board_approve_access",
    ),
    path(
        "boards/<int:board_id>/deny-access/<int:user_id>/",
        deny_board_access,
        name="board_deny_access",
    ),
    path("board/<int:board_id>/access-requests/poll/", views.board_access_requests_poll, name="board_access_requests_poll"),


    # ============================================================
    # BOARDS — COLUNAS (criar / reordenar / seguir)
    # ============================================================
    path("board/<int:board_id>/add_column/", columns_views.add_column, name="add_column"),
    path("board/<int:board_id>/columns/reorder/", columns_views.reorder_columns, name="reorder_columns"),
    path("column/<int:column_id>/follow/", toggle_column_follow, name="toggle_column_follow"),

    # ============================================================
    # BOARDS — WALLPAPER / CSS
    # ============================================================
    path("board/<int:board_id>/wallpaper/", update_board_wallpaper, name="update_board_wallpaper"),
    path("board/<int:board_id>/wallpaper/remove/", remove_board_wallpaper, name="remove_board_wallpaper"),
    path("board/<int:board_id>/wallpaper.css", board_wallpaper_css, name="board_wallpaper_css"),

    # ============================================================
    # BOARDS — IMAGEM (capa do quadro)
    # ============================================================
    path("board/<int:board_id>/image/", update_board_image, name="update_board_image"),
    path("board/<int:board_id>/image/remove/", remove_board_image, name="remove_board_image"),

    # ============================================================
    # BOARDS — POLLING (sincronização leve)
    # ============================================================
    path("board/<int:board_id>/poll/", board_poll, name="board_poll"),

    # ============================================================
    # BOARDS — PRAZOS (term due + cores do board)
    # ============================================================
    path("card/<int:card_id>/term-due/", set_card_term_due, name="set_card_term_due"),
    path("board/<int:board_id>/term-colors/", set_board_term_colors, name="set_board_term_colors"),

    # ============================================================
    # BOARDS — AGREGADOR DE COLUNAS
    # ============================================================
    path(
        "board/<int:board_id>/toggle-aggregator/",
        toggle_aggregator_column,
        name="toggle_aggregator_column",
    ),

    # ============================================================
    # BOARDS — TRANSFERÊNCIA DE TITULARIDADE (OWNER -> OWNER)
    # ============================================================
    path(
        "board/<int:board_id>/transfer_owner/start/",
        transfer_owner_start,
        name="transfer_owner_start",
    ),
    path(
        "board/<int:board_id>/transfer_owner/confirm/",
        transfer_owner_confirm,
        name="transfer_owner_confirm",
    ),

    # ============================================================
    # BOARDS — CALENDÁRIO
    # ============================================================
    path("calendar/cards/", calendar_views.calendar_cards, name="calendar_cards"),
    path(
        "card/<int:card_id>/calendar-date/",
        calendar_views.card_calendar_date_update,
        name="card_calendar_date_update",
    ),

    # ============================================================
    # HOME GROUPS / FAVORITOS (agrupamentos pessoais)
    # ============================================================
    path("home/groups/create/", home_group_create, name="home_group_create"),
    path("home/groups/<int:group_id>/rename/", home_group_rename, name="home_group_rename"),
    path("home/groups/<int:group_id>/delete/", home_group_delete, name="home_group_delete"),
    path("home/groups/<int:group_id>/items/add/", home_group_item_add, name="home_group_item_add"),
    path(
        "home/groups/<int:group_id>/items/<int:board_id>/remove/",
        home_group_item_remove,
        name="home_group_item_remove",
    ),
    path("home/favorites/toggle/<int:board_id>/", home_favorite_toggle, name="home_favorite_toggle"),
    path("home/search/", home_search, name="home_search"),

    # ============================================================
    # HOME WALLPAPER (papel de parede da home)
    # ============================================================
    path("home/wallpaper/", update_home_wallpaper, name="update_home_wallpaper"),
    path("home/wallpaper/remove/", remove_home_wallpaper, name="remove_home_wallpaper"),
    path("home/wallpaper.css", home_wallpaper_css, name="home_wallpaper_css"),

    # ============================================================
    # COLUMNS (ações por coluna)
    # ============================================================
    path("column/<int:column_id>/add_card/", cards_views.add_card, name="add_card"),
    path("column/<int:column_id>/delete/", columns_views.delete_column, name="delete_column"),
    path("column/<int:column_id>/rename/", columns_views.rename_column, name="rename_column"),
    path("column/<int:column_id>/theme/", columns_views.set_column_theme, name="set_column_theme"),
    path("column/<int:column_id>/reorder_cards/", cards_views.reorder_cards_in_column, name="reorder_cards_in_column"),

    # ============================================================
    # CARDS (modal / CRUD / mover / anexos / atividade)
    # ============================================================
    path("card/<int:card_id>/modal/", cards_views.card_modal, name="card_modal"),
    path("card/<int:card_id>/snippet/", cards_views.card_snippet, name="card_snippet"),
    path("card/<int:card_id>/edit/", cards_views.edit_card, name="edit_card"),
    path("card/<int:card_id>/update/", cards_views.update_card, name="update_card"),
    path("card/<int:card_id>/delete/", cards_views.delete_card, name="delete_card"),

    # Tags
    path("cards/<int:card_id>/tag-color/", cards_views.set_tag_color, name="set_tag_color"),
    path("card/<int:card_id>/remove_tag/", cards_views.remove_tag, name="remove_tag"),

    # Capa do card
    path("card/<int:card_id>/cover/set/", cards_views.set_card_cover, name="set_card_cover"),
    path("card/<int:card_id>/cover/remove/", cards_views.remove_card_cover, name="remove_card_cover"),

    # Duplicar card
    path("card/<int:card_id>/duplicate/", cards_views.duplicate_card, name="duplicate_card"),

    # Mover card
    path("move-card/", cards_views.move_card, name="move_card"),
    path("card/<int:card_id>/move/options/", cards_views.card_move_options, name="card_move_options"),

    # Atividade (painel / add / quill upload) — ajuste conforme seu projeto real
    path("card/<int:card_id>/activity/panel/", activity_panel, name="activity_panel"),
    path("card/<int:card_id>/activity/add/", add_activity, name="add_activity"),
    path("quill/upload/", quill_upload, name="quill_upload"),


    path(
        "board/<int:board_id>/cards/unread-activity/",
        cards_unread_activity,
        name="cards_unread_activity",
    ),

    # Menções (board)
    path("board/<int:board_id>/mentions/", board_mentions, name="board_mentions"),

    # Anexos
    path("card/<int:card_id>/attachments/add/", attachments_views.add_attachment, name="add_attachment"),
    path(
        "card/<int:card_id>/attachments/<int:attachment_id>/delete/",
        attachments_views.delete_attachment,
        name="delete_attachment",
    ),

    path("card/<int:card_id>/follow/", cards_state_views.toggle_card_follow, name="toggle_card_follow"),


    # ============================================================
    # CHECKLISTS (modal do card)
    # ============================================================
    path("card/<int:card_id>/checklist/add/", checklist_views.checklist_add, name="checklist_add"),
    path("checklist/<int:checklist_id>/rename/", checklist_views.checklist_rename, name="checklist_rename"),
    path("checklist/<int:checklist_id>/delete/", checklist_views.checklist_delete, name="checklist_delete"),

    path("checklist/<int:checklist_id>/item/add/", checklist_views.checklist_add_item, name="checklist_add_item"),
    path("checklist/item/<int:item_id>/toggle/", checklist_views.checklist_toggle_item, name="checklist_toggle_item"),
    path("checklist/item/<int:item_id>/delete/", checklist_views.checklist_delete_item, name="checklist_delete_item"),
    path("checklist/item/<int:item_id>/update/", checklist_views.checklist_update_item, name="checklist_update_item"),

    path("card/<int:card_id>/checklists/reorder/", checklist_views.checklists_reorder, name="checklists_reorder"),
    path("card/<int:card_id>/checklist-items/reorder/", checklist_views.checklist_items_reorder, name="checklist_items_reorder"),

    # Legado (se ainda existir)
    path("checklist/<int:checklist_id>/move/", checklist_views.checklist_move, name="checklist_move"),
    path("checklist/item/<int:item_id>/move-up/", checklist_views.checklist_move_up, name="checklist_move_up"),
    path("checklist/item/<int:item_id>/move-down/", checklist_views.checklist_move_down, name="checklist_move_down"),

    # ============================================================
    # CONTA / PERFIL (modal do usuário)
    # (mantendo via views/__init__.py porque você reexporta account/profiles)
    # ============================================================
    path("account/modal/", views.account_modal, name="account_modal"),
    path("account/profile/update/", views.account_profile_update, name="account_profile_update"),
    path("account/password/change/", views.account_password_change, name="account_password_change"),
    path("account/avatar/update/", views.account_avatar_update, name="account_avatar_update"),
    path("account/avatar/choose/", views.account_avatar_choice_update, name="account_avatar_choice_update"),
    path("account/identity-label/update/", views.account_identity_label_update, name="account_identity_label_update"),

    # ============================================================
    # PERFIL READ-ONLY (modal ao clicar em avatar de outra pessoa)
    # ============================================================
    path(
        "users/<int:user_id>/profile/readonly/",
        views.user_profile_readonly_modal,
        name="user_profile_readonly_modal",
    ),

    # ============================================================
    # HISTÓRICO / NÃO LIDOS
    # ============================================================
    path("board/<int:board_id>/history/", views.board_history_modal, name="board_history_modal"),
    path("board/<int:board_id>/history/unread-count/", views.board_history_unread_count, name="board_history_unread_count"),
]
# END file boards/urls.py
