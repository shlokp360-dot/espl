"""
The login form, and only the login form.

⚠ WHY THERE IS NO USER FORM HERE
    Every other screen in this project parses `request.POST` in the view and
    renders plain inputs in the template — the material screen, the vendor
    screen, the BOQ, the BOM. The Users screen follows them, so that somebody
    reading two screens side by side sees one pattern rather than two.

    Login is the exception because Django's `AuthenticationForm` carries the
    parts nobody should hand-roll: the inactive-account check, the
    "authenticate() returned nobody" message, and the session-fixation fix that
    comes with `login()`. All this subclass does is relabel the box.

⚠ IT SAYS USERNAME, NOT EMAIL, AND THAT IS SAAHIL'S CALL — "keep login with
    username only". The reason it is the right one: site engineers are the
    people most likely to be signing in from a phone at seven in the morning,
    and they are also the people least likely to have a company email address.
    `ramesh` beats `ramesh.patel@elegancesky.com` at that hour on that keyboard.
"""
from django import forms
from django.contrib.auth.forms import AuthenticationForm


class UsernameLoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Username",
        widget=forms.TextInput(attrs={
            "class": "cell", "autofocus": True, "autocomplete": "username",
            "autocapitalize": "none", "spellcheck": "false",
            "placeholder": "ramesh",
            "style": "background:#fff",
        }),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={
            "class": "cell", "autocomplete": "current-password",
            "style": "background:#fff",
        }),
    )

    error_messages = {
        # ⚠ ONE MESSAGE FOR BOTH FAILURES, ON PURPOSE. "No such user" tells a
        #   stranger which usernames are real.
        "invalid_login": "That username and password do not match an account.",
        "inactive": "That account has been deactivated. Ask the admin to turn it back on.",
    }
