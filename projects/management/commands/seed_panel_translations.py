"""
Load the Gujarati first draft into the translation overlay.

>>> ANCHOR: INFO-PANELS <<<
⚠⚠ A DRAFT TO BE CORRECTED, NOT AN ANSWER. Saahil's decision — "editing will be
   easier than typing the whole thing." The rows this writes are Claude's
   Gujarati; their own people correct them on the Screen instructions tab, and
   the screen says plainly which rows nobody has checked yet.

⚠⚠ IT NEVER OVERWRITES A ROW A PERSON WROTE. `updated_by` is the whole test: a
   row this command writes has none, and a row saved from the screen always has
   one. So a second run cannot undo somebody's afternoon of corrections, which
   is the only way this command could do real damage.

⚠ `--remove` IS THE SAME RULE READ BACKWARDS. It deletes a row only where the
  Gujarati is still exactly what was seeded and nobody has touched it. Anything
  corrected is kept and counted, and the command says how many it left behind.
  `seed_showcase --remove` deletes exactly its own rows; so does this.

⚠ A LABEL THAT NO LONGER EXISTS IS REPORTED, NOT WRITTEN. The draft is keyed by
  panel key and step label. Rename a step in `help_panels.py` and its draft
  stops matching — which must be loud, because a translation seeded against
  nothing would sit in the table describing an instruction nobody can read.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from masters.models import PanelTranslation
from projects.help_panels import PANELS
from projects.panel_gujarati import DRAFTS


class Command(BaseCommand):
    help = "Seed the Gujarati first draft of the ⓘ panels, for their people to correct."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Say what would change and write nothing.")
        parser.add_argument("--remove", action="store_true",
                            help="Delete the seeded drafts that nobody has corrected.")
        parser.add_argument("--panel", default="",
                            help="One panel key only, for checking a single screen.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        only = opts["panel"]
        self.loud = opts.get("verbosity", 1) >= 1

        drafts = {k: v for k, v in DRAFTS.items() if not only or k == only}
        if only and not drafts:
            self.stderr.write(self.style.ERROR(
                f"No draft for panel '{only}'. Known: {', '.join(sorted(DRAFTS))}"))
            return

        # ⚠ VALIDATE THE WHOLE DRAFT BEFORE WRITING ANY OF IT. A typo in a panel
        #   key is a mistake in this file, not a reason to half-seed the table.
        unknown = []
        for key, steps in drafts.items():
            panel = PANELS.get(key)
            if not panel:
                unknown.append(f"panel '{key}' does not exist")
                continue
            labels = {s["label"] for s in panel["steps"]}
            for label in steps:
                if label not in labels:
                    unknown.append(f"{key} · step '{label}' does not exist")
        if unknown:
            for line in unknown:
                self.stderr.write(self.style.ERROR(f"  ✗ {line}"))
            self.stderr.write(self.style.ERROR(
                f"{len(unknown)} draft entr{'y' if len(unknown) == 1 else 'ies'} match no step. "
                "Nothing was written."))
            return

        if opts["remove"]:
            self._remove(drafts, dry)
            return

        written = updated = unchanged = kept = 0
        with transaction.atomic():
            for key, steps in sorted(drafts.items()):
                english = {s["label"]: s["text"] for s in PANELS[key]["steps"]}
                for label, gujarati in steps.items():
                    gujarati = " ".join(gujarati.split())
                    row = PanelTranslation.objects.filter(
                        panel_key=key, step_label=label).first()

                    # ⚠⚠ SOMEBODY'S OWN WORDS ARE NEVER REPLACED.
                    if row and row.updated_by_id is not None:
                        kept += 1
                        continue
                    if row and row.gujarati == gujarati and row.source_english == english[label]:
                        unchanged += 1
                        continue
                    if not dry:
                        PanelTranslation.objects.update_or_create(
                            panel_key=key, step_label=label,
                            defaults={"gujarati": gujarati,
                                      "source_english": english[label],
                                      "updated_by": None})
                    if row:
                        updated += 1
                    else:
                        written += 1
            if dry:
                transaction.set_rollback(True)

        if not self.loud:
            return
        verb = "would be" if dry else ""
        self.stdout.write(self.style.SUCCESS(
            f"{written} draft{'' if written == 1 else 's'} {verb} written, "
            f"{updated} refreshed, {unchanged} already current."))
        if kept:
            self.stdout.write(
                f"  {kept} row{'' if kept == 1 else 's'} left alone — somebody has "
                f"corrected {'it' if kept == 1 else 'them'} already.")
        total = sum(len(s) for s in drafts.values())
        panels_done = len(drafts)
        self.stdout.write(
            f"  {total} steps across {panels_done} screen{'' if panels_done == 1 else 's'} "
            f"in this batch. These are a FIRST DRAFT and must be checked on the "
            f"Screen instructions tab before anybody relies on them.")

    def _remove(self, drafts, dry):
        """Delete only what is still untouched."""
        gone = kept = 0
        for key, steps in sorted(drafts.items()):
            for label, gujarati in steps.items():
                gujarati = " ".join(gujarati.split())
                row = PanelTranslation.objects.filter(
                    panel_key=key, step_label=label).first()
                if not row:
                    continue
                if row.updated_by_id is not None or row.gujarati != gujarati:
                    kept += 1
                    continue
                if not dry:
                    row.delete()
                gone += 1
        if not self.loud:
            return
        verb = "would be" if dry else ""
        self.stdout.write(self.style.SUCCESS(
            f"{gone} untouched draft{'' if gone == 1 else 's'} {verb} removed."))
        if kept:
            self.stdout.write(
                f"  {kept} row{'' if kept == 1 else 's'} kept — corrected since seeding, "
                "so not this command's to delete.")
