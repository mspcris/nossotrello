from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model


class UsernameOrEmailBackend(ModelBackend):
    """
    Permite login com username OU email no campo 'username'.
    Compatível com o LoginView/Form padrão que manda username=<email>.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()

        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)

        if username is None or password is None:
            return None

        # 1) tenta padrão (username)
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is not None:
            return user

        # 2) tenta email
        try:
            user_obj = UserModel._default_manager.get(email__iexact=username)
        except UserModel.DoesNotExist:
            return None

        if user_obj.check_password(password) and self.user_can_authenticate(user_obj):
            return user_obj
        return None
