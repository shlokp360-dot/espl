"""
The addresses that let somebody in, and the screen that decides who they are.

⚠ THE LOGIN PAGE IS THE ONE ADDRESS THAT MUST NOT REQUIRE A LOGIN.
    `LoginRequiredMiddleware` protects everything by default — that is the point
    of it — so the login view is marked with `login_not_required`. Without that
    the middleware redirects the login page to the login page, forever.
"""
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from accounts import views
from accounts.forms import UsernameLoginForm

urlpatterns = [
    path("login/", login_not_required(LoginView.as_view(
        template_name="accounts/login.html",
        authentication_form=UsernameLoginForm,
        redirect_authenticated_user=True,
    )), name="login"),

    # ⚠ POST only, and that is Django's doing rather than ours: a GET that logs
    #   you out can be fired by any image tag on any page.
    path("logout/", LogoutView.as_view(), name="logout"),

    path("password/", views.ChangeOwnPassword.as_view(), name="password_change"),

    # Under /masters/ because that is where the screen lives on the Master data
    # page, beside Materials and Vendors.
    path("masters/users/", views.user_list, name="user_list"),
    path("masters/users/new/", views.user_form, name="user_new"),
    path("masters/users/<int:user_id>/", views.user_form, name="user_edit"),
    path("masters/users/<int:user_id>/toggle/", views.user_toggle_active, name="user_toggle_active"),
    path("masters/users/<int:user_id>/reset/", views.user_reset_password, name="user_reset_password"),
]
