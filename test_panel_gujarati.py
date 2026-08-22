"""
The Gujarati first draft, and the rules that keep it honest.

>>> ANCHOR: INFO-PANELS <<<
Saahil's call: Claude writes a first draft and their own people correct it on
screen, because editing is easier than typing. That decision creates three ways
to be wrong, and each of them is a test here.

  1. A DRAFT KEYED TO A STEP THAT NO LONGER EXISTS. Rename a step in
     `help_panels.py` and its Gujarati describes nothing. Caught at test time,
     not only when somebody runs the command.
  2. A CONTROL NAME TRANSLATED. `[[Order Qty]]` is a button on an English
     screen. Translating what is inside the brackets puts two vocabularies in
     one room the first time somebody reads a screen over a shoulder.
  3. SOMEBODY'S CORRECTION OVERWRITTEN by a second run of the seeder. That is
     the only way this command destroys work, so it is the test that matters
     most.
"""
import re

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.testing import AuthedTestCase
from masters.models import PanelTranslation
from projects.help_panels import PANELS
from projects.panel_gujarati import DRAFTS

CONTROL = re.compile(r"\[\[(.+?)\]\]")


class TheDraftMatchesThePanels(TestCase):

    def test_every_draft_names_a_panel_that_exists(self):
        for key in DRAFTS:
            with self.subTest(panel=key):
                self.assertIn(key, PANELS)

    def test_every_draft_names_a_step_that_exists(self):
        """
        ⚠ KEYED BY LABEL, NOT POSITION — so a renamed label must be loud. A
          translation seeded against nothing sits in the table for ever,
          describing an instruction nobody can reach.
        """
        for key, steps in DRAFTS.items():
            labels = {s["label"] for s in PANELS[key]["steps"]}
            for label in steps:
                with self.subTest(panel=key, label=label):
                    self.assertIn(label, labels)

    def test_a_panel_is_drafted_whole_or_not_at_all(self):
        """
        The toggle appears only when every step a reader can see is translated,
        so half a panel is work that shows the reader nothing.
        """
        for key, steps in DRAFTS.items():
            labels = {s["label"] for s in PANELS[key]["steps"]}
            with self.subTest(panel=key):
                self.assertEqual(set(steps), labels)

    def test_every_panel_is_drafted(self):
        """
        ⚠⚠ THE SET IS COMPLETE, AND A NEW PANEL MUST SAY SO. All 162 steps are
           drafted. Add a screen next year and this fails — which is the point:
           one English panel among thirty-eight bilingual ones is the kind of
           gap nobody notices from the inside, and everybody notices at a site
           office. Drafting it is a line of work; discovering it is not.
        """
        self.assertEqual(set(DRAFTS), set(PANELS))
        self.assertEqual(sum(len(s) for s in DRAFTS.values()),
                         sum(len(p["steps"]) for p in PANELS.values()))

    def test_no_draft_is_empty(self):
        for key, steps in DRAFTS.items():
            for label, gujarati in steps.items():
                with self.subTest(panel=key, label=label):
                    self.assertTrue(gujarati.strip())


class TheControlNamesSurviveTranslation(TestCase):
    """
    ⚠⚠ SCREEN LABELS STAY ENGLISH. The panel is bilingual; the screen is not.
    """

    def test_the_same_controls_are_named_in_both_languages(self):
        for key, steps in DRAFTS.items():
            english = {s["label"]: s["text"] for s in PANELS[key]["steps"]}
            for label, gujarati in steps.items():
                with self.subTest(panel=key, label=label):
                    self.assertEqual(sorted(CONTROL.findall(english[label])),
                                     sorted(CONTROL.findall(gujarati)))

    def test_gujarati_is_actually_gujarati(self):
        """
        A draft left in English would seed silently and read as finished work.
        Outside the brackets there must be Gujarati script.
        """
        for key, steps in DRAFTS.items():
            for label, gujarati in steps.items():
                outside = CONTROL.sub("", gujarati)
                with self.subTest(panel=key, label=label):
                    self.assertTrue(any("઀" <= ch <= "૿" for ch in outside))


class SeedingTheDraft(AuthedTestCase):

    def setUp(self):
        super().setUp()
        self.key = next(iter(DRAFTS))
        self.label = next(iter(DRAFTS[self.key]))

    def test_it_writes_the_english_it_was_written_from(self):
        """`source_english` is the whole of the staleness guard."""
        call_command("seed_panel_translations", panel=self.key, verbosity=0)
        row = PanelTranslation.objects.get(panel_key=self.key, step_label=self.label)
        english = {s["label"]: s["text"] for s in PANELS[self.key]["steps"]}
        self.assertEqual(row.source_english, english[self.label])

    def test_a_seeded_row_has_no_author(self):
        """Which is what lets the screen say nobody has checked it."""
        call_command("seed_panel_translations", panel=self.key, verbosity=0)
        row = PanelTranslation.objects.get(panel_key=self.key, step_label=self.label)
        self.assertIsNone(row.updated_by_id)

    def test_running_it_twice_changes_nothing(self):
        call_command("seed_panel_translations", panel=self.key, verbosity=0)
        before = PanelTranslation.objects.get(panel_key=self.key, step_label=self.label)
        stamp = before.updated_at
        call_command("seed_panel_translations", panel=self.key, verbosity=0)
        after = PanelTranslation.objects.get(panel_key=self.key, step_label=self.label)
        self.assertEqual(after.updated_at, stamp)

    def test_a_dry_run_writes_nothing(self):
        call_command("seed_panel_translations", panel=self.key, dry_run=True, verbosity=0)
        self.assertFalse(PanelTranslation.objects.exists())

    def test_it_never_overwrites_what_a_person_wrote(self):
        """
        ⚠⚠ THE ONE THAT MATTERS. Their people spend an afternoon correcting the
           draft; somebody runs the seeder again next month. Nothing they typed
           may be lost.
        """
        person = self.make_user("zqhelp1")
        PanelTranslation.objects.create(
            panel_key=self.key, step_label=self.label,
            gujarati="તેમના પોતાના શબ્દો", source_english="whatever it said",
            updated_by=person)

        call_command("seed_panel_translations", panel=self.key, verbosity=0)

        row = PanelTranslation.objects.get(panel_key=self.key, step_label=self.label)
        self.assertEqual(row.gujarati, "તેમના પોતાના શબ્દો")
        self.assertEqual(row.updated_by_id, person.id)

    def test_remove_takes_back_only_what_nobody_touched(self):
        call_command("seed_panel_translations", panel=self.key, verbosity=0)
        person = self.make_user("zqhelp2")
        corrected = PanelTranslation.objects.filter(panel_key=self.key).exclude(
            step_label=self.label).first()
        corrected.gujarati = "સુધારેલું"
        corrected.updated_by = person
        corrected.save()

        call_command("seed_panel_translations", panel=self.key, remove=True, verbosity=0)

        self.assertFalse(PanelTranslation.objects.filter(
            panel_key=self.key, step_label=self.label).exists())
        self.assertTrue(PanelTranslation.objects.filter(pk=corrected.pk).exists())


class TheScreenSaysWhatIsUnchecked(AuthedTestCase):
    """
    ⚠ THE COMPLIANCE PRECEDENT. Content that is a first draft says so where it
      is worked on — beside the box, not in a banner a full page swallows.
    """

    def test_a_seeded_row_is_marked_as_a_draft(self):
        key = next(iter(DRAFTS))
        call_command("seed_panel_translations", panel=key, verbosity=0)

        page = self.client.get(f"{reverse('panel_text')}?panel={key}")
        self.assertContains(page, "not checked yet")

    def test_a_row_somebody_saved_is_not_marked_as_a_draft(self):
        """The marker must mean "nobody has checked it", not "it is Gujarati"."""
        key = next(iter(DRAFTS))
        call_command("seed_panel_translations", panel=key, verbosity=0)
        PanelTranslation.objects.filter(panel_key=key).update(updated_by=self.user)

        page = self.client.get(f"{reverse('panel_text')}?panel={key}")
        self.assertNotContains(page, "not checked yet")


class TheScreenExplainsTheMarkers(AuthedTestCase):
    """
    C3 — the `[[...]]` markers show raw, and until now nothing said why.

    ⚠⚠ THE MARKERS MUST SURVIVE TRANSLATION or a button's name stops matching
       the button. A liaison person meeting `[[Order Qty]]` cold may translate
       it, drop the brackets, or decide the screen is broken — and the first two
       fail silently, because a panel with a translated marker still renders.

    ⚠ THE GUIDANCE IS IN THE COLUMN HEADING, so it is present at the moment of
      typing rather than in a banner above a long table.
    """

    def test_the_guidance_is_on_the_screen(self):
        key = next(iter(DRAFTS))
        page = self.client.get(f"{reverse('panel_text')}?panel={key}")
        self.assertContains(page, "keep")
        self.assertContains(page, "[[...]]")

    def test_it_is_there_even_when_a_row_has_gone_stale(self):
        """
        ⚠ THE STALE WARNING REPLACES THE OTHER NOTE, and a translator fixing a
          drifted row needs the marker rule exactly as much as a new one does.
          Putting it in the heading is what makes this true in both branches.
        """
        key = next(iter(DRAFTS))
        call_command("seed_panel_translations", panel=key, verbosity=0)
        PanelTranslation.objects.filter(panel_key=key).update(
            updated_by=self.user, source_english="something it no longer says")

        page = self.client.get(f"{reverse('panel_text')}?panel={key}")
        self.assertContains(page, "changed in English after being translated")
        self.assertContains(page, "[[...]]")
