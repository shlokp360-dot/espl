# Wiring the drawings module into the shared files

Nothing below has been applied — these are the rows to add to files the brief
says not to edit. `python manage.py test drawings` is green without them (78
tests); the matrix rows and the panel merge make the shared suites see it.

## `accounts/test_matrix.py` — SCREENS

`True` means "reverse with project id 1". Screens taking a second id are not
expressible in the table as it stands; their permission refusals are proved in
`drawings/tests.py` (`WhoMayDoWhat`, `Architects`) instead. `drawings_download`
takes a revision id — with `1` an allowed role gets 404 and a refused one 403,
which is exactly what the screen test asserts.

```python
    # ---- drawings — the register, the files, and who was sent what ----------
    # ⚠ Accountant and Compliance are NOT on the read row: accounts/perms.py
    #   gives drawings.view to A, PM, PUR, SITE. Purchase reads the register
    #   because a work order goes out with the drawings it is priced from.
    ("drawings_home",              False, {A, PM, PUR, SITE}),
    ("drawings_register_default",  False, {A, PM, PUR, SITE}),
    ("drawings_register",          True,  {A, PM, PUR, SITE}),
    ("drawings_transmittals",      True,  {A, PM, PUR, SITE}),
    ("drawings_architects",        False, {A, PM, PUR, SITE}),
    ("drawings_groups",            False, {A, PM, PUR, SITE}),
    # revision id, not project id — see the note above.
    ("drawings_download",          True,  {A, PM, PUR, SITE}),
    # Registering and issuing are A and PM only.
    ("drawings_new",               True,  {A, PM}),
    ("drawings_bulk",              True,  {A, PM}),
    ("drawings_architect_new",     False, {A, PM}),
    ("drawings_transmittal_new",   True,  {A, PM}),
```

Not in the table (two ids): `drawings_detail`, `drawings_edit`,
`drawings_transmittal`, `drawings_transmittal_pdf`, `drawings_architect_edit`.

## `accounts/test_matrix.py` — ACTIONS

```python
    ("drawings_groups_save",       False, {A, PM}),
    ("drawings_architect_new",     False, {A, PM}),        # GET+POST on one view
    ("drawings_new",               True,  {A, PM}),
    ("drawings_bulk",              True,  {A, PM}),
    ("drawings_transmittal_new",   True,  {A, PM}),
```

Not in the table (two ids): `drawings_upload`, `drawings_approve`,
`drawings_edit` — refusals proved in `drawings/tests.py`.

## `projects/help_panels.py` — the ⓘ panels

At the bottom of `PANELS`, or after the dict:

```python
from drawings.panels import PANELS as DRAWINGS_PANELS
PANELS.update(DRAWINGS_PANELS)
```

Keys: `drawings_home`, `drawings_register`, `drawings_form`, `drawings_bulk`,
`drawings_detail`, `drawings_transmittals`, `drawings_transmittal_new`,
`drawings_transmittal`, `drawings_architects`, `drawings_groups`. Every
template already calls `{% infobutton %}`/`{% infopanel %}` with these keys;
until merged they render nothing (an unknown key is silent by design).
`drawings/tests.py::ThePanelsKeepTheFormat` applies the same rules as
`projects/test_info_panels.py` so the merge cannot fail the shared suite.

## `projects/hub.py`

The tile already exists (`key: "drawings"`, `url_name: "drawings_home"`,
`perm: "drawings.view"`). Nothing to add.

## `templates/drawings/_nav.html` — the tab list

| Tab           | url name                                   | shown when            |
|---------------|--------------------------------------------|-----------------------|
| Overview      | `drawings_home`                            | always                |
| Register      | `drawings_register` / `_register_default`  | always                |
| Transmittals  | `drawings_transmittals`                    | a project is in context |
| Architects    | `drawings_architects`                      | always                |
| Groups        | `drawings_groups`                          | always                |

## `NumberSeries`

Key `transmittal`, formatted `TR-000001`. Created on first use by
`take_next`; nothing to seed.

## `ANCHORS.md`

Append the rows in `drawings/ANCHORS-drawings.md`. The drift check gains 7
anchors (`DRAWINGS-*`); the `MASTER-TABS` and `INFO-PANELS` references in this
app point at existing rows.
