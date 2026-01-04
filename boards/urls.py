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
from boards.views.modal_card_term import set_card_term_due, set_board_term_colors
from boards.views.boards import toggle_aggregator_column




app_name = "boards"

# ============================================================
# URLS DO APP BOARDS — ORGANIZADAS E COMENTADAS
# ============================================================
urlpatterns = [
    # ============================================================
    # HOME
    # ============================================================
    path("", views.index, name="boards_index"),

    # ============================================================
    # AUTH / CONTAS (LOGIN / PRIMEIRO LOGIN / RECUPERAÇÃO SENHA)
    # ============================================================
    # perfil clicável
    path("u/<str:handle>/", views.public_profile, name="public_profile"),

    # Login / Logout (usa templates em templates/registration/)
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

    # Primeiro login (view custom)
    path("accounts/first-login/", views.first_login, name="first_login"),

    # Recuperação de senha
    # - email_template_name: texto puro (evita aparecer <p> no Gmail)
    # - html_email_template_name: HTML (para clientes que renderizam)
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

    # (Opcional) criação de usuário
    path("users/create/", views.create_user, name="create_user"),

    # ============================================================
    # BOARDS
    # ============================================================
    path("board/add/", views.add_board, name="add_board"),
    path("board/<int:board_id>/", views.board_detail, name="board_detail"),
    path("board/<int:board_id>/search/", views.board_search, name="board_search"),
    path("board/<int:board_id>/rename/", views.rename_board, name="rename_board"),
    path("board/<int:board_id>/delete/", views.delete_board, name="delete_board"),

    # Compartilhamento
    path("board/<int:board_id>/share/", views.board_share, name="board_share"),
    path(
        "board/<int:board_id>/share/remove/<int:user_id>/",
        views.board_share_remove,
        name="board_share_remove",
    ),
    path("board/<int:board_id>/leave/", views.board_leave, name="board_leave"),

    # Colunas do board
    path("board/<int:board_id>/add_column/", views.add_column, name="add_column"),
    path("board/<int:board_id>/columns/reorder/", views.reorder_columns, name="reorder_columns"),

    # Wallpaper do board
    path("board/<int:board_id>/wallpaper/", views.update_board_wallpaper, name="update_board_wallpaper"),
    path("board/<int:board_id>/wallpaper/remove/", views.remove_board_wallpaper, name="remove_board_wallpaper"),
    path("board/<int:board_id>/wallpaper.css", views.board_wallpaper_css, name="board_wallpaper_css"),

    # Imagem do board
    path("board/<int:board_id>/image/", views.update_board_image, name="update_board_image"),
    path("board/<int:board_id>/image/remove/", views.remove_board_image, name="remove_board_image"),

    # Search do board (se existir no seu views/__init__.py)

    # board polling
    path("board/<int:board_id>/poll/", board_poll, name="board_poll"),

    # board prazos
    path("card/<int:card_id>/term-due/", set_card_term_due, name="set_card_term_due"),
    path("board/<int:board_id>/term-colors/", set_board_term_colors, name="set_board_term_colors"),

    # board agregador de colunas
    path(
    "board/<int:board_id>/toggle-aggregator/",
    toggle_aggregator_column,
    name="toggle_aggregator_column",
),

    

    # ============================================================
    # HOME GROUPS / FAVORITOS
    # ============================================================
    path("home/groups/create/", views.home_group_create, name="home_group_create"),
    path("home/groups/<int:group_id>/rename/", views.home_group_rename, name="home_group_rename"),
    path("home/groups/<int:group_id>/delete/", views.home_group_delete, name="home_group_delete"),
    path("home/groups/<int:group_id>/items/add/", views.home_group_item_add, name="home_group_item_add"),
    path("home/groups/<int:group_id>/items/<int:board_id>/remove/", views.home_group_item_remove, name="home_group_item_remove"),
    path("home/favorites/toggle/", views.home_favorite_toggle, name="home_favorite_toggle"),


    # ============================================================
    # HOME WALLPAPER
    # ============================================================
    path("home/wallpaper/", views.update_home_wallpaper, name="update_home_wallpaper"),
    path("home/wallpaper/remove/", views.remove_home_wallpaper, name="remove_home_wallpaper"),
    path("home/wallpaper.css", views.home_wallpaper_css, name="home_wallpaper_css"),

    # ============================================================
    # COLUMNS
    # ============================================================
    path("column/<int:column_id>/add_card/", views.add_card, name="add_card"),
    path("column/<int:column_id>/delete/", views.delete_column, name="delete_column"),
    path("column/<int:column_id>/rename/", views.rename_column, name="rename_column"),
    path("column/<int:column_id>/theme/", views.set_column_theme, name="set_column_theme"),

    # ============================================================
    # CARDS
    # ============================================================
    path("card/<int:card_id>/modal/", views.card_modal, name="card_modal"),
    path("card/<int:card_id>/snippet/", views.card_snippet, name="card_snippet"),
    path("card/<int:card_id>/edit/", views.edit_card, name="edit_card"),
    path("card/<int:card_id>/update/", views.update_card, name="update_card"),
    path("card/<int:card_id>/delete/", views.delete_card, name="delete_card"),

    # Etiquetas
    path("cards/<int:card_id>/tag-color/", views.set_tag_color, name="set_tag_color"),
    path("card/<int:card_id>/remove_tag/", views.remove_tag, name="remove_tag"),
    
    # Vencimento do card
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

    # Menções do board
    path("board/<int:board_id>/mentions/", board_mentions, name="board_mentions"),

    # Anexos (múltiplos)
    path("card/<int:card_id>/attachments/add/", views.add_attachment, name="add_attachment"),
    path(
        "card/<int:card_id>/attachments/<int:attachment_id>/delete/",
        views.delete_attachment,
        name="delete_attachment",
    ),
    



    # ============================================================
    # CONTA / PERFIL (MODAL)
    # ============================================================
    path("account/modal/", views.account_modal, name="account_modal"),
    path("account/profile/update/", views.account_profile_update, name="account_profile_update"),
    path("account/password/change/", views.account_password_change, name="account_password_change"),
    path("account/avatar/update/", views.account_avatar_update, name="account_avatar_update"),
    path("account/avatar/choose/", views.account_avatar_choice_update, name="account_avatar_choice_update"),


    # ============================================================
    # PERFIL (READ-ONLY NO MODAL)
    # ============================================================
    path(
    "users/<int:user_id>/profile/readonly/",
    views.user_profile_readonly_modal,
    name="user_profile_readonly_modal",
    ),
    

    # ============================================================
    # CONTA / PERFIL (SOCIAL)
    # ============================================================
    path("u/<str:handle>/", views.public_profile, name="public_profile"),


    # ============================================================
    # CHECKLISTS (múltiplos por card)
    # ============================================================
    path("card/<int:card_id>/checklist/add/", views.checklist_add, name="checklist_add"),
    path("checklist/<int:checklist_id>/rename/", views.checklist_rename, name="checklist_rename"),
    path("checklist/<int:checklist_id>/delete/", views.checklist_delete, name="checklist_delete"),

    # Reordenação
    path("card/<int:card_id>/checklists/reorder/", views.checklists_reorder, name="checklists_reorder"),
    path("card/<int:card_id>/checklist/items/reorder/", views.checklist_items_reorder, name="checklist_items_reorder"),

    # Compat/legado
    path("checklist/<int:checklist_id>/move/", views.checklist_move, name="checklist_move"),
    path("checklist/item/<int:item_id>/move-up/", views.checklist_move_up, name="checklist_move_up"),
    path("checklist/item/<int:item_id>/move-down/", views.checklist_move_down, name="checklist_move_down"),

    # Itens do checklist
    path("checklist/<int:checklist_id>/item/add/", views.checklist_add_item, name="checklist_add_item"),
    path("checklist/item/<int:item_id>/toggle/", views.checklist_toggle_item, name="checklist_toggle_item"),
    path("checklist/item/<int:item_id>/delete/", views.checklist_delete_item, name="checklist_delete_item"),
    path("checklist/item/<int:item_id>/update/", views.checklist_update_item, name="checklist_update_item"),
]
#END file boards/urls.py