"""The one function every panel file uses. Kept apart from help_panels so the
module panel files can import it without importing the merged table back."""


def step(label, head, text, gu="", perm=None):
    return {"label": label, "head": head, "text": text, "gu": gu, "perm": perm}
