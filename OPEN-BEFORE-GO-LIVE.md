# OPEN BEFORE GO-LIVE

**Read this before the app goes onto their server.** Nothing here is a bug. Every line is either a
decision nobody has made yet, content only they can supply, or a seam left deliberately empty — and
each one is cheap now and expensive once real work is running through the system.

Saahil's instruction, 14 Aug 2026: *"mark the open points to remind me before deployment."*

Ordered by what it costs to leave undone.

---

## 1. Decisions that are harder to change afterwards

- [x] ~~**Document numbering — slice 9.**~~ **CLOSED 16 Aug — the customer has agreed to keep
      `PO-000123`.** Saahil talked them out of the change rather than it being dropped for time. The
      richer `PO-BHUD-2627-0007` format — type, project reference, fiscal year, per-project sequence
      restarting 1 April — is not being built.
      ⚠ **This was the most urgent item on this page, and it is closed by agreement, not by code.**
      A number printed on a real order can never be reissued, so if they ever reopen it the cost is
      the same as it always was — and it rises the moment real documents exist. Anyone reconsidering
      this should know they are reversing a decision the customer made, not filling a gap we left.

- [x] ~~**The BOQ reserve matches an activity by NAME, not by ID.**~~ **CLOSED 16 Aug — the customer
      has agreed not to rename construction activities.** Saahil secured that agreement rather than
      us accepting the risk.
      **Belt and braces, and both are real:** the agreement is the belt, and `Activity.clean()` is
      the braces — it **refuses** a rename outright once any estimate line carries that name, so the
      silent-zero scenario cannot happen even if somebody forgets the agreement. It lives in the
      model rather than a view, so every route obeys it, and `masters/test_rename_guard.py` keeps it
      that way. See `ANCHOR: ACTIVITY-RENAME-BLOCKED`.
      Unbuilt, and now genuinely optional: linking the reserve by ID instead of by text.
      The named alternative for master data stays: **deactivate and add a new one, never rename.**

- [ ] **The notification channel.** WhatsApp Business API (no Meta approval yet), email (SMTP they
      already have), or in-app only. **Three features are waiting on this one answer:** the
      "you have been assigned work" message, the daily digest, and compliance expiry reminders at 60
      and 30 days. The seam is marked and empty in `tasks/views.py`; picking a channel is a day's
      work, changing it later is not.

      **16 Aug — still open, leaning one way.** Saahil: *"will get back to you, we may leave it on
      them and guide them to add the WhatsApp API connector themselves."* ⚠ If that is the answer,
      the deliverable changes shape: it is no longer a channel decision but **written instructions
      plus a seam they can fill without us**, and the Meta approval becomes their task and their
      timeline. Worth deciding before the handover document is written, not after.

- [x] ~~**A house default for payment terms.**~~ **DECIDED 14 Aug: 30 days** when a vendor's terms
      cannot be read. 173 of 174 vendors have nothing in that field, so the alternative aged almost
      nothing. The assumption is flagged on every row and counted in every bucket — `DEFAULT_CREDIT_DAYS`
      in `analytics/money.py`, one line to change or to move onto CompanyProfile.

- [x] ~~**`required_by` is set on 0 of 7 documents.**~~ **CLOSED 16 Aug — the customer has agreed not
      to make it mandatory.** The field stays optional and nobody will be asked to fill it.
      ⚠ **They have accepted a consequence, so make sure they know which one:** vendor delivery
      lateness compares `Receipt.received_on` against `required_by`, so with the field empty **the
      vendor scorecard has no input at all** — not inaccurate, absent. And it cannot be built
      retrospectively either, because the data was never captured. If they ask in six months which
      vendors deliver late, the honest answer is that the question can only be answered from the day
      they start filling the field in.

- [ ] **⚠ THE MASTER-DATA ROUND TRIP IS BROKEN ON A FRESH DATABASE.** The Materials sheet stores a
      group as a *code*, and nothing seeds material groups or vendor groups — only activities (18)
      and units (28) arrive with `migrate`. So a file exported from the screen and imported into an
      empty database is rejected **row by row**: *"Group 'HDW' is not a material group."* All 705.
      The `import_masters` **command** works, because `MATERIAL_MASTER.xlsx` carries its own Groups
      sheet; the **screen export does not include one**. **This bites on their server on day one.**
      Fix: put a Groups sheet in the exported workbook and let the importer create from it, or refuse
      once with a clear list instead of 705 identical errors.

      **16 Aug — Saahil is testing this himself:** *"have to test, will do."* ⚠ The test only means
      anything on a **genuinely empty** database — on his own laptop the groups are already there,
      so the round trip succeeds and proves nothing. Export from the screen, then import into a
      fresh database with only `migrate` run.

- [x] ~~**Session length is 12 hours.**~~ **CONFIRMED 16 Aug.** Long enough for a full site day,
      short enough that a shared laptop does not stay signed in overnight.

## 2. Content only they can supply

- [ ] **Their own GSTIN and registered address.** Its first two digits decide CGST + SGST against
      IGST on **every document**. Until it is filled in, every vendor is treated as local.
- [ ] **Vendor GSTINs.** Approval hard-blocks without one, except vendors explicitly marked
      unregistered.
- [ ] **The standard terms that print on every order.** The clauses in the system today were drafted
      by Claude and are commercial boilerplate — not an Elegance Skyz document. Their contracts
      person should read them once.
- [ ] **Their CA's confirmation** of three things on the money ladder: the post-tax deduction, the
      TDS treatment, and the terms. Legal and tax are the CA's call, never ours.
- [ ] **Estimation rates**, a rate for `Common`, the RMC and steel materials, the labour and service
      materials, and the 16 rows in `IMPORT_TO_FIX.xlsx`.
- [ ] **The compliance checklist, confirmed by whoever does their liaison work.** Rajachitthi,
      plinth checking, BU permission, RERA Forms 1/2/3 and the rest are a first draft and are
      labelled as such on screen. **Getting one wrong there is a compliance risk, not a bug.**

## 3. Questions left open on purpose, with a reversible answer in place today

Each of these works right now. Each was decided the way that is easy to widen and hard to undo.

- [ ] **Does a site engineer see everybody's delay log?** Today: managers only. Their own late rows
      are on their own screen, so nobody is kept from their own record. Widening it is one line.
- [ ] **Does a manager verify Done?** Today: no — *"the engineer's tick is final"*. A manager can
      reopen a mistaken tick, and that is visible.
- [ ] **"Scope or design changed"** was added as a seventh delay reason when rescheduling was built.
      It is not one of the six agreed with the customer. Keep it or drop the line.
- [ ] **Can a site engineer edit a draft purchase order?** The agreed table has one row for "view ·
      edit draft · PDF" ticked for Site; it was split so they can read every value and not edit
      somebody's draft. Flagged in `accounts/perms.py` for confirmation.
- [ ] **Compliance:** does the `REPEAT` kind survive, and are downloads logged?
- [ ] **Compliance thresholds: 60 days for Expiring, 92 for a quarterly filing going stale.**
      The only two numbers in the module that were chosen rather than derived. 60 should be however
      long an AMC renewal actually takes to come back — if a fire NOC takes three months it should be
      90. `EXPIRING_WITHIN_DAYS` and `REPEAT_AFTER_DAYS` in `compliance/status.py`.
- [x] ~~**Does an uploaded document need a second person to accept it?**~~ **DECIDED: no.** On a team
      this size a review step gets skipped, and a good certificate sitting at "waiting review" makes
      a compliant project look non-compliant. Who uploaded and when is already recorded.
- [x] ~~**Can a checklist item belong to one project?**~~ **DECIDED: yes** —
      `ComplianceItem.project`, for a condition attached to one plot. Marked on screen so it is not
      mistaken for part of the standard list.

## 4. Things deliberately not built, so nobody goes looking for them

- **The daily digest.** A digest is a notification; see the channel decision above. As a screen it
  would only be My work again.
- **Task templates per activity** — worth doing once they have used the board for a fortnight and
  know which packages actually repeat.
- **Comments on tasks.**
- ~~**Vendor rates** — agreed, not built.~~ **⚠ THIS ENTRY WAS STALE AND IS NOW WRONG.** Vendor
  rates ARE built: captured on approval as `taxable ÷ quantity`, one row per vendor and material,
  replaced each time. `effective_vendor_rate` reads them — typed rate, then the captured rate,
  then the planning rate. See `ANCHOR: VENDOR-RATE-CAPTURE`.
- **`MaterialActivity` and `VendorCategory`** are dead models still in the schema. Drop them.
- **Django Admin** — removed entirely, not merely restricted. `/admin/` is a 404 and a test keeps
  it that way. See `ANCHOR: NO-DJANGO-ADMIN`.

## 5. The server itself

- [ ] **What OS is the in-house server, and is it a hypervisor?** Still unanswered by their IT lead.
      **If Windows, gunicorn does not run there and WeasyPrint needs GTK3** — this changes the
      deployment plan, not a setting.
- [ ] `DEBUG=False`, a fresh `SECRET_KEY`, `ALLOWED_HOSTS`, HTTPS, and CSRF trusted origins.
- [ ] **pango and cairo installed, or purchase orders cannot print at all.**
- [ ] ~~`collectstatic` and WhiteNoise~~ — **no longer needed.** It was only ever for Django
      Admin's own CSS, and Admin is gone. This application ships not one static file; all CSS is
      inline.
- [ ] A systemd service, so it comes back up after a reboot without somebody remembering.
- [ ] **PostgreSQL rehearsed on a laptop FIRST**, then `dumpdata` / `loaddata`, then **count the rows
      on both sides**. Never rehearse a migration for the first time on the machine that matters.
- [ ] **Backups: `pg_dump` AND the media folder.** Compliance documents are the only thing in this
      system that does not live in the database, and a database-only backup would silently miss every
      signed municipal approval. **A backup on the same machine is not a backup.**
- [ ] **Reaching it from site**: Cloudflare Tunnel, VPN or port-forwarding — tunnel recommended.
- [ ] SSH keys only, root login disabled, **at least two key holders**. `.env` and the database
      password go in their password manager, not in a chat message.
- [ ] The repository stays **Private**.

## 6. On the day

### ⚠⚠ G1 — SEED THE MASTERS WITH `import_masters`, AND NEVER WITH THE SCREEN'S EXPORT

**This is the one that stops day one dead, and it is procedural — there is no code fix.**

```
python manage.py import_masters      ← THE ONLY WAY to seed a fresh database
```
using **`MATERIAL_MASTER.xlsx`** and **`VENDOR_MASTER.xlsx`**, which carry their own **Groups**
sheet.

**⚠ DO NOT download from the Materials or Vendors screen and upload it into the new database.**
`masters/sheets.py` matches a group only against `MaterialGroup` rows **already present in the
target database**, and no migration seeds them. The workbook's `Reference` sheet exists for
Excel's dropdowns and is never read back on import.

**So the round trip that works perfectly on Saahil's laptop rejects all 705 rows, one at a time,
against an empty Postgres.** Confirmed by reading both import paths, not guessed.

**After seeding, count the rows on both sides** — 705 materials, 174 vendors, 18 construction
activities, 28 units — before anybody signs in.

### ⚠ Dummy GSTINs must not travel

If `seed_dummy_gstins` has been run anywhere, **every number it wrote contains `ZZDMY` and is
fake.** It refuses to run when `DEBUG` is False, and it never touches `VENDOR_MASTER.xlsx`, so
production should never see one. Check anyway:

```
python manage.py check_integrity     ← read-only, safe any time
```

### ✅ The first Admin now creates itself — you no longer have to know a trick

**This used to stop day one dead and it was not written down anywhere.**
`createsuperuser` makes a Django `User` but **no `UserProfile`**, and every screen reads
`UserProfile.role`. With no Django Admin to repair it from, the first sign-in on a brand-new
database landed on an almost empty launchpad where every tile answered "your role does not
have that authorization" — and the Users screen refused to let you set your own role, with
the advice *"Ask another Admin"* when there was no other Admin. **It looked exactly like the
application was broken.** Hit for real during the PostgreSQL rehearsal on 16 Aug.

**Fixed — `ANCHOR: BOOTSTRAP-ADMIN`.** If the system has **no active Admin at all**, a
superuser signing in is made one, told so on screen, and it is written into the account
history. Nothing to run and nothing to remember.

**⚠ The condition is "this system has no Admin", NOT "this user is a superuser".** The door
shuts the moment one Admin exists, so a superuser created later gets a role from an Admin
like anybody else. Being able to open a shell still does not mean being able to approve a
purchase order.

- [ ] Create the real user accounts with real roles, each forced to change password at first sign-in.
      **Delete nothing and nobody afterwards** — deactivate.
- [ ] **Saahil has still never run an Excel upload himself.** One file rewrites 705 rates. Do it once
      on a copy before anybody does it on the live system.
- [ ] Run `python manage.py check_integrity` against the real data — it is read-only and safe any
      time, and it checks the things the test suite cannot: that *their* data is sane.
