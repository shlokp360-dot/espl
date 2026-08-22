# Setup — step by step

Written for someone who has not run a Django project before.
Everything in `code font` is typed exactly as shown.

---

## 0. Move this folder out of OneDrive first

**Important.** OneDrive and Git both manage hidden files and will corrupt each
other. Symptoms are confusing and hard to recover from.

Move this whole folder to somewhere like `C:\Projects\elegance-skyz`.
Your Excel master files can stay in OneDrive — only the code folder must move.

---

## 1. Install the two things you need

* **Python 3.12** — https://www.python.org/downloads/
  On the first screen, tick **"Add python.exe to PATH"**. Easy to miss, annoying to fix later.
* **GitHub Desktop** — https://desktop.github.com
  Handles Git without the command line.

Check Python worked. Open Command Prompt and type:

    python --version

You should see `Python 3.12.x`.

---

## 2. Set up the project

Open Command Prompt **inside the project folder** (in File Explorer, type `cmd`
in the address bar and press Enter). Then:

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt

The first line creates a private space for this project's libraries so it can
never clash with anything else on the machine. You will see `(.venv)` appear at
the start of the line — that means it is active. Run `.venv\Scripts\activate`
again each time you open a new Command Prompt.

---

## 3. Create your settings file

Copy `.env.example` to `.env`, then open `.env` in Notepad and change
`DJANGO_SECRET_KEY` to any long random string.

`.env` is never uploaded to GitHub. It is where passwords and API keys live.

---

## 4. Create the database and your login

    python manage.py makemigrations
    python manage.py migrate
    python manage.py createsuperuser

The last command asks for a username and password. This is your admin login.

While developing, the database is a single file (`db.sqlite3`) — nothing to
install. PostgreSQL comes later, on the server.

> **Before that server day arrives, read `OPEN-BEFORE-GO-LIVE.md`.**
> It is the list of decisions nobody has made yet, content only Elegance Skyz can
> supply, and seams left deliberately empty. Each one is cheap to close now and
> expensive once real orders are running through the system — the document
> numbering format most of all, because a number printed on a real order can
> never be reissued.

---

## 5. Run it

    python manage.py runserver

Open **http://127.0.0.1:8000** in your browser and log in.

You will see the Materials, Vendors, Vendor rates, Projects, Estimates and
Trade defaults screens — searchable, filterable, editable. Those screens were
not written by hand; Django generated them from the table definitions in
`masters/models.py` and `projects/models.py`.

Press `Ctrl + C` in the Command Prompt to stop it.

---

## 6. Connect to GitHub

In **GitHub Desktop**:

1. `File` → `Add local repository` → choose this folder
2. It will say the folder is not a Git repository → click **"create a repository"**
3. Leave the defaults, click **Create repository**
4. Click **Publish repository** at the top
5. **Tick "Keep this code private"** — this is client work
6. Choose the repo you already created, or let it create one

After that, every change you make shows up in GitHub Desktop. Type a short note
about what you changed, click **Commit**, then **Push origin**. That is the
whole routine.

---

## Before every commit

Look at the list of files GitHub Desktop is about to upload. If you see a
spreadsheet, a `.env`, or anything with vendor phone numbers, stop and tell
whoever set this up. Once something is committed it stays in the history even
after you delete it.

---

## When something breaks

* `'python' is not recognized` → Python was installed without ticking "Add to PATH". Reinstall and tick it.
* `No module named django` → you forgot `.venv\Scripts\activate` in this window.
* `That port is already in use` → the server is already running in another window.


---

## Showing it to somebody — a clone with data in it, in ten minutes

**⚠ A FRESH CLONE HAS AN EMPTY DATABASE.** No projects, no materials, no login.
That is deliberate — the database, the `.env` and the master spreadsheets are
never committed, because they hold real vendor phone numbers, GST numbers and
prices. So a clone on its own shows six empty screens, and anybody judging the
work from that would be judging the wrong thing.

`seed_showcase` fixes that in one command. It **needs nothing imported first**.

### On their laptop

1. **They need access.** The repository is Private — add them in GitHub under
   Settings → Collaborators.
2. **GitHub Desktop** → File → Clone repository → pick it.
3. **Python 3.12** from python.org, ticking *"Add python.exe to PATH"*.
4. A new command prompt, in the folder they cloned into:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_showcase
python manage.py runserver
```

5. `http://127.0.0.1:8000/` and sign in with the superuser they just made.

### What they will see

Three Won sites, five months of purchase orders at every stage, work that is
part done and part late, and a compliance file with documents that are valid,
expiring and expired. **Every screen has something on it** — that is the
acceptance test for the seeder, and there is a test that walks all twenty
screens and asserts each one answers.

### Two things worth knowing

**⚠ `createsuperuser` MAKES AN ACCOUNT WITH NO ROLE**, and the permission matrix
answers "no role" with an almost empty launchpad. `seed_showcase` promotes any
such superuser to Admin and says so in its summary — otherwise the first
impression of the app is that it is broken.

**Everything it creates is marked**: projects are named "Showcase — …",
materials sit in group `SHW`, vendors are `VEN-S01` upwards, demo colleagues have
user IDs ending `.demo` and cannot sign in. To remove it all:

```
python manage.py seed_showcase --remove
```

That deletes exactly those rows and nothing else — there is a test which creates
a real project and a real vendor, runs the seeder, removes it, and asserts both
survive.

### On a Mac — every step that actually caught somebody out

Done live on a MacBook on 14 Aug. All seven of these cost a round trip; none is obvious.

1. **macOS has no `python` command, only `python3`.** `zsh: command not found: python` means you
   typed the wrong one, not that Python is missing.
2. Running `python3` for the first time offers to install Apple's **Command Line Tools** — accept it.
   It then reports **Python 3.9.6**, and **Django 5.2 needs 3.10 or newer**. Install **Python 3.12**
   from python.org; it sits alongside Apple's and breaks nothing.
3. **Close Terminal completely and reopen it** after that install, or it still sees the old version.
   If `python3 --version` is still 3.9, check what actually installed with
   `ls /Library/Frameworks/Python.framework/Versions/` and call it by full path:
   `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m venv .venv`
4. **⚠ Do not clone into Desktop or Documents.** Both are usually synced to iCloud Drive, and iCloud
   corrupts a Git repository the same way OneDrive does. Use `~/Projects`.
5. GitHub Desktop → **Repository → Open in Terminal** (`Cmd` + `` ` ``) starts you in the project
   folder, so there is no `cd` step.
6. Activation is **`source .venv/bin/activate`**, not `.venv\Scripts\activate`. After it, plain
   `python` works — which is why the first line below says `python3` and the rest say `python`.
7. The address is **`http://`**, not `https://`. A local server has no certificate.

**First time, once:**

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_showcase
python manage.py runserver
```

**Every time after that — this is the whole routine:**

```
source .venv/bin/activate
python manage.py runserver
```

Then http://127.0.0.1:8000. `Ctrl` + `C` stops it. Leave Terminal running while you click around;
closing that window kills the app.

`createsuperuser` **shows nothing at all while you type the password** — no dots, no cursor movement.
That is normal. Email can be left blank.

### If the install fails, it will be WeasyPrint

It needs graphics libraries that Windows and macOS do not ship. **WeasyPrint is imported inside the
PDF view, not when the app starts**, so it can be missing entirely — install just these and carry on,
and everything except the three PDF buttons works:

```
pip install Django==5.2.16 python-dotenv==1.0.1 openpyxl==3.1.5
```

**A `.env` file is also not needed for a demonstration** — the secret key falls back to a development
default. It is only required on a real server.

### Making the PDFs actually work

Skip this for a demonstration. Do it before any test that has to include **the printed purchase
order**, the BOQ PDF, or **⤓ PDFs as a zip** — those three are the only things that need it.

Without the libraries you get:

```
OSError: cannot load library 'libgobject-2.0-0': error 0x7e
```

That is not a bug in the application. WeasyPrint does not draw PDFs itself; it calls out to the
GTK3 native libraries (Pango, Cairo, GObject), and those simply are not on the machine.

**On Windows**

1. Install the **GTK3 Runtime for Windows 64-bit** (`gtk3-runtime-…-win64.exe`).
2. Let it **add itself to your PATH**, or add `C:\Program Files\GTK3-Runtime Win64\bin` yourself.
3. ⚠⚠ **THE STEP EVERYBODY MISSES, AND IT IS NOT IN ANY OFFICIAL DOCUMENTATION.** GTK installs the
   file as **`libgobject-2.0-0.dll`** and WeasyPrint looks for **`gobject-2.0-0.dll`**. Open that
   `bin` folder, copy the file, and rename the copy with the `lib` prefix removed.
4. **Restart the machine** — not just the terminal. A PATH change needs it.
5. `runserver` again and open any approved order's **Download PDF**.

**On a Mac**

```
brew install pango libffi
```

Then reopen Terminal. macOS needs no DLL rename; Homebrew puts the libraries where WeasyPrint
looks.

### ⚠⚠ ON WINDOWS, PATH ALONE IS NOT ENOUGH ON PYTHON 3.8 AND LATER

**This cost Saahil a restart on 16 Aug and it will cost you one too.** Python 3.8 changed how
Windows loads native libraries: `ctypes` **no longer searches `PATH`**. So the GTK folder can be
correctly on PATH, the DLL can be sitting right there, and WeasyPrint still reports

```
cannot load library 'libgobject-2.0-0': error 0x7e
```

WeasyPrint reads a dedicated variable instead. Set it **as well as** the PATH entry:

- Variable name: `WEASYPRINT_DLL_DIRECTORIES`
- Variable value: `C:\msys64\ucrt64\bin` (or your GTK `bin` folder)

To try it in one window without touching system settings, before `runserver`:

```
set WEASYPRINT_DLL_DIRECTORIES=C:\msys64\ucrt64\bin
```

**⚠ HONEST STATUS: THIS IS NOT YET CONFIRMED WORKING ON OUR OWN MACHINE.** The libraries install
cleanly and `libgobject-2.0-0.dll` is demonstrably present in `/ucrt64/bin`, but the PDFs had still
not rendered on Saahil's laptop when this was written. If it still fails, the next thing to check
is whether Windows can load the library at all, independently of WeasyPrint:

```
python -c "import os,ctypes; os.add_dll_directory(r'C:\msys64\ucrt64\bin'); ctypes.CDLL('libgobject-2.0-0.dll'); print('LOADED OK')"
```

`error 0x7e` is `ERROR_MOD_NOT_FOUND`, which can also mean the DLL was found but one of **its own**
dependencies was not.

**⚠ NONE OF THIS APPLIES ON LINUX**, where it is one line — `apt install libpango-1.0-0
libpangoft2-1.0-0`. Every bit of this friction exists only because the machine is Windows, which is
also why the in-house server's operating system is the open question that matters most.

⚠ **This is also the deployment question, not just a laptop one.** If the in-house server runs
Windows, the same wall is there — and gunicorn does not run on Windows either. That is a different
deployment plan, not a different setting. See `OPEN-BEFORE-GO-LIVE.md` §5.

### The other two seeders, so nobody picks the wrong one

| Command | What it is for |
|---|---|
| `seed_showcase` | A complete, plausible system. **For a demonstration.** Needs nothing. |
| `seed_demo` | One project built from your **real** 705 materials. Needs the spreadsheets imported first. |
| `seed_stress` | Deliberately awkward data — zero rates, missing vendors, a trade with no budget. **For finding what breaks.** |
| `seed_dummy_gstins` | **Fake GSTINs so purchase orders can be approved.** Only on a test machine — it refuses to run when `DEBUG` is False. |

### ⚠ If nothing can be approved, this is why

A purchase order **cannot be approved without the vendor's GSTIN** — that rule is correct and is
not going anywhere. On a fresh laptop almost no vendor has one, so the whole second half of the
application (approve → deliver → pay → the printed order → vendor rates → spend analytics) is
unreachable.

```
python manage.py seed_dummy_gstins --dry-run
python manage.py seed_dummy_gstins
python manage.py seed_dummy_gstins --remove
```

Every number it writes contains **`ZZDMY`** and is unmistakably fake. It leaves a dozen vendors
deliberately blank, so the vendor master's "without a GSTIN" counter still shows a real gap, and it
never touches a number somebody typed.

### ⚠⚠ SEEDING A REAL DATABASE — the one that would break day one

**Never** seed a fresh database by downloading from the Materials or Vendors screen and uploading
that file into the new one. The screen's importer matches groups only against rows **already in the
target database**, and nothing seeds them — so all 705 rows are rejected, one at a time.

```
python manage.py import_masters
```

using `MATERIAL_MASTER.xlsx` and `VENDOR_MASTER.xlsx`, which carry their own **Groups** sheet.
This is `G1` in `OPEN-BEFORE-GO-LIVE.md` §6.
