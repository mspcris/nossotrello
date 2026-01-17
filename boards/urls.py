"""
boards/urls.py

URLs do app boards — organizadas e comentadas.

Ponto de atenção:
- Este app expõe as rotas de AUTH (login/logout/reset/first-login) com namespace "boards".
- Portanto, nos templates use:
  - {% url 'boards:login' %}
  - {% url 'boards:logout' %}
  - {% url 'boards:password_reset' %}
  - {% url 'boards:password_reset_done' %}
  - {% url 'boards:password_reset_confirm' uidb64=uid token=token %}
  - {% url 'boards:password_reset_complete' %}
  - {% url 'boards:first_login' %}
"""

from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .views import cards
from .views.mentions import board_mentions
from .views.polling import board_poll
from .views import calendar as calendar_views
from boards.views.modal_card_term import set_card_term_due, set_board_term_colors
from boards.views import checklists as checklist_views

# Views “de negócio” (boards/views/boards.py)
from boards.views.boards import (
    toggle_aggregator_column,
    transfer_owner_start,
    transfer_owner_confirm,
    request_board_access,
    approve_board_access,
    deny_board_access,
)

app_name = "boards"

# ============================================================
# URLS DO APP BOARDS — ORGANIZADAS E COMENTADAS
# ============================================================
urlpatterns = [
    # ============================================================
    # HOME (lista de quadros)
    # ============================================================
    path("", views.index, name="boards_index"),

    # ============================================================
    # PERFIL PÚBLICO (rota curta por handle)
    # ============================================================
    path("u/<str:handle>/", views.public_profile, name="public_profile"),

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
    path(
        "accounts/logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
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
    path("board/add/", views.add_board, name="add_board"),
    path("board/<int:board_id>/", views.board_detail, name="board_detail"),
    path("board/<int:board_id>/search/", views.board_search, name="board_search"),
    path("board/<int:board_id>/rename/", views.rename_board, name="rename_board"),
    path("board/<int:board_id>/delete/", views.delete_board, name="delete_board"),
    path("board/<int:board_id>/leave/", views.board_leave, name="board_leave"),

    # ============================================================
    # BOARDS — COMPARTILHAMENTO (modal + remove membro)
    # ============================================================
    path("board/<int:board_id>/share/", views.board_share, name="board_share"),
    # (mantido se o front usa submit em rota separada; se não usa, pode remover)
    path("board/<int:board_id>/share/submit/", views.board_share, name="board_share_submit"),
    path(
        "board/<int:board_id>/share/remove/<int:user_id>/",
        views.board_share_remove,
        name="board_share_remove",
    ),

    # ============================================================
    # BOARDS — ACESSO SEM CONVITE (solicitar / aprovar / negar)
    #
    # PADRÃO ÚNICO (sem duplicidade):
    # - request-access
    # - approve-access
    # - deny-access
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

    # ============================================================
    # BOARDS — COLUNAS (criar / reordenar)
    # ============================================================
    path("board/<int:board_id>/add_column/", views.add_column, name="add_column"),
    path("board/<int:board_id>/columns/reorder/", views.reorder_columns, name="reorder_columns"),

    # ============================================================
    # BOARDS — WALLPAPER / CSS
    # ============================================================
    path("board/<int:board_id>/wallpaper/", views.update_board_wallpaper, name="update_board_wallpaper"),
    path("board/<int:board_id>/wallpaper/remove/", views.remove_board_wallpaper, name="remove_board_wallpaper"),
    path("board/<int:board_id>/wallpaper.css", views.board_wallpaper_css, name="board_wallpaper_css"),

    # ============================================================
    # BOARDS — IMAGEM (capa do quadro)
    # ============================================================
    path("board/<int:board_id>/image/", views.update_board_image, name="update_board_image"),
    path("board/<int:board_id>/image/remove/", views.remove_board_image, name="remove_board_image"),

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

    # ============================================================
    # HOME GROUPS / FAVORITOS (agrupamentos pessoais)
    # ============================================================
    path("home/groups/create/", views.home_group_create, name="home_group_create"),
    path("home/groups/<int:group_id>/rename/", views.home_group_rename, name="home_group_rename"),
    path("home/groups/<int:group_id>/delete/", views.home_group_delete, name="home_group_delete"),
    path("home/groups/<int:group_id>/items/add/", views.home_group_item_add, name="home_group_item_add"),
    path(
        "home/groups/<int:group_id>/items/<int:board_id>/remove/",
        views.home_group_item_remove,
        name="home_group_item_remove",
    ),
    path("home/favorites/toggle/<int:board_id>/", views.home_favorite_toggle, name="home_favorite_toggle"),
    path("home/search/", views.home_search, name="home_search"),

    # ============================================================
    # HOME WALLPAPER (papel de parede da home)
    # ============================================================
    path("home/wallpaper/", views.update_home_wallpaper, name="update_home_wallpaper"),
    path("home/wallpaper/remove/", views.remove_home_wallpaper, name="remove_home_wallpaper"),
    path("home/wallpaper.css", views.home_wallpaper_css, name="home_wallpaper_css"),

    # ============================================================
    # COLUMNS (ações por coluna)
    # ============================================================
    path("column/<int:column_id>/add_card/", views.add_card, name="add_card"),
    path("column/<int:column_id>/delete/", views.delete_column, name="delete_column"),
    path("column/<int:column_id>/rename/", views.rename_column, name="rename_column"),
    path("column/<int:column_id>/theme/", views.set_column_theme, name="set_column_theme"),
    path("column/<int:column_id>/reorder_cards/", views.reorder_cards_in_column, name="reorder_cards_in_column"),

    # ============================================================
    # CARDS (modal / CRUD / mover / anexos / atividade)
    # ============================================================
    path("card/<int:card_id>/modal/", views.card_modal, name="card_modal"),
    path("card/<int:card_id>/snippet/", views.card_snippet, name="card_snippet"),
    path("card/<int:card_id>/edit/", views.edit_card, name="edit_card"),
    path("card/<int:card_id>/update/", views.update_card, name="update_card"),
    path("card/<int:card_id>/delete/", views.delete_card, name="delete_card"),

    # Tags
    path("cards/<int:card_id>/tag-color/", views.set_tag_color, name="set_tag_color"),
    path("card/<int:card_id>/remove_tag/", views.remove_tag, name="remove_tag"),

    # Term (vencimento)
    path("cards/<int:card_id>/term-color/", views.set_term_color, name="set_term_color"),
    path("card/<int:card_id>/remove_term/", views.remove_term, name="remove_term"),

    # Capa do card
    path("card/<int:card_id>/cover/set/", cards.set_card_cover, name="set_card_cover"),
    path("card/<int:card_id>/cover/remove/", cards.remove_card_cover, name="remove_card_cover"),

    # Duplicar card
    path("card/<int:card_id>/duplicate/", cards.duplicate_card, name="duplicate_card"),

    # Mover card
    path("move-card/", views.move_card, name="move_card"),
    path("card/<int:card_id>/move/options/", views.card_move_options, name="card_move_options"),

    # Atividade (Quill)
    path("card/<int:card_id>/activity/panel/", views.activity_panel, name="activity_panel"),
    path("card/<int:card_id>/activity/add/", views.add_activity, name="add_activity"),
    path("quill/upload/", views.quill_upload, name="quill_upload"),

    # Menções (board)
    path("board/<int:board_id>/mentions/", board_mentions, name="board_mentions"),

    # Anexos
    path("card/<int:card_id>/attachments/add/", views.add_attachment, name="add_attachment"),
    path(
        "card/<int:card_id>/attachments/<int:attachment_id>/delete/",
        views.delete_attachment,
        name="delete_attachment",
    ),

    # ============================================================
    # CHECKLISTS (modal do card)
    # ============================================================

    # CRUD
    path("card/<int:card_id>/checklist/add/", checklist_views.checklist_add, name="checklist_add"),
    path("checklist/<int:checklist_id>/rename/", checklist_views.checklist_rename, name="checklist_rename"),
    path("checklist/<int:checklist_id>/delete/", checklist_views.checklist_delete, name="checklist_delete"),

    path("checklist/<int:checklist_id>/item/add/", checklist_views.checklist_add_item, name="checklist_add_item"),
    path("checklist/item/<int:item_id>/toggle/", checklist_views.checklist_toggle_item, name="checklist_toggle_item"),
    path("checklist/item/<int:item_id>/delete/", checklist_views.checklist_delete_item, name="checklist_delete_item"),
    path("checklist/item/<int:item_id>/update/", checklist_views.checklist_update_item, name="checklist_update_item"),

    # Reorder (DnD)
    path("card/<int:card_id>/checklists/reorder/", checklist_views.checklists_reorder, name="checklists_reorder"),
    path("card/<int:card_id>/checklist-items/reorder/", checklist_views.checklist_items_reorder, name="checklist_items_reorder"),

    # Legado (se você ainda usa em algum lugar)
    path("checklist/<int:checklist_id>/move/", checklist_views.checklist_move, name="checklist_move"),
    path("checklist/item/<int:item_id>/move-up/", checklist_views.checklist_move_up, name="checklist_move_up"),
    path("checklist/item/<int:item_id>/move-down/", checklist_views.checklist_move_down, name="checklist_move_down"),


    # ============================================================
    # CONTA / PERFIL (modal do usuário)
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
