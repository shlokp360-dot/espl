"""
The ⓘ panels, and the three rules they have to keep.

>>> ANCHOR: INFO-PANELS <<<
Points 4, 5 and 6. The panels became DATA rather than markup in twenty
templates, and the argument for that was partly this file: a format held in one
place can be checked, and a format copied into twenty templates cannot.

⚠⚠ THESE ARE THE RULES FROM THE SAMPLE SAAHIL APPROVED, written down so they
   cannot erode one panel at a time:

     1. The index is SHORT LABELS, not sentences.
     2. 20–30 words a step.
     3. Bold is ONLY EVER a button or a field name — never emphasis.

⚠ THE THIRD IS ENFORCED BY THE SYNTAX, not by discipline. `[[Order Qty]]` is the
  only thing that becomes bold, and the brackets are named for what they are
  allowed to contain. A test still checks, because a syntax nobody verifies is a
  convention.
"""
import re

from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from accounts.testing import AuthedTestCase
from projects.help_panels import PANELS
from projects.templatetags.help import render_text


class EveryPanelKeepsTheFormat(TestCase):

    def test_a_step_is_between_twenty_and_thirty_words(self):
        """
        Long enough to be an instruction, short enough that somebody standing at
        a desk reads it. A little slack either side; a paragraph is not a step.
        """
        for key, panel in PANELS.items():
            for number, step in enumerate(panel["steps"], 1):
                words = len(step["text"].split())
                with self.subTest(panel=key, step=number):
                    self.assertGreaterEqual(words, 18)
                    self.assertLessEqual(words, 32)

    def test_an_index_label_is_one_or_two_words(self):
        """The index is a line of labels to jump by, not a summary to read."""
        for key, panel in PANELS.items():
            for step in panel["steps"]:
                with self.subTest(panel=key, label=step["label"]):
                    self.assertLessEqual(len(step["label"].split()), 2)
                    self.assertFalse(step["label"].endswith("."))

    def test_every_panel_has_a_title_and_at_least_three_steps(self):
        for key, panel in PANELS.items():
            with self.subTest(panel=key):
                self.assertTrue(panel["title"])
                self.assertGreaterEqual(len(panel["steps"]), 3)

    def test_no_step_uses_html_directly(self):
        """
        ⚠ THE POINT OF THE `[[…]]` SYNTAX. A stray <b> in the data would be
          escaped and printed literally — which is safe, and would look broken.
          Better to say so here.
        """
        for key, panel in PANELS.items():
            for step in panel["steps"]:
                with self.subTest(panel=key, step=step["label"]):
                    self.assertNotIn("<", step["text"])

    def test_a_control_name_is_short_enough_to_be_a_control(self):
        """
        Bold marks something you can point at on the screen. Eight words inside
        the brackets is a sentence somebody wanted emphasised.
        """
        for key, panel in PANELS.items():
            for step in panel["steps"]:
                for control in re.findall(r"\[\[(.+?)\]\]", step["text"]):
                    with self.subTest(panel=key, control=control):
                        self.assertLessEqual(len(control.split()), 4)


class TheMarkupIsSafe(TestCase):

    def test_a_control_becomes_bold(self):
        self.assertEqual(render_text("Type into [[Order Qty]]."),
                         "Type into <b>Order Qty</b>.")

    def test_everything_else_is_escaped(self):
        """One vendor called "Shah & Co" is enough to break an unescaped panel."""
        self.assertEqual(render_text("Shah & Co <script>"),
                         "Shah &amp; Co &lt;script&gt;")

    def test_a_control_cannot_carry_markup_in_with_it(self):
        """
        ⚠ ESCAPE FIRST, THEN BOLD. The other order would let `[[<script>]]`
          through as real markup, because the brackets survive escaping.
        """
        self.assertNotIn("<script>", render_text("[[<script>]]"))

    def test_nothing_else_is_bolded(self):
        self.assertNotIn("<b>", render_text("This is important and urgent."))


class ThePanelReachesTheScreen(AuthedTestCase):

    def render(self, key):
        return Template(
            '{% load help %}{% infobutton "' + key + '" %}{% infopanel "' + key + '" %}'
        ).render(Context({}))

    def test_the_button_opens_the_panel_of_the_same_key(self):
        html = self.render("bom")

        self.assertIn("info-bom", html)
        self.assertIn("showModal", html)

    def test_the_index_is_generated_from_the_steps(self):
        """
        ⚠ WRITTEN BY HAND IT WOULD BE WRONG the first time somebody inserted a
          step in the middle. Every label must appear in the index.
        """
        html = self.render("bom")

        for step in PANELS["bom"]["steps"]:
            self.assertIn(step["label"], html)

    def test_an_unknown_key_renders_nothing_rather_than_raising(self):
        """A typo must not take a working screen down. The next test catches it."""
        self.assertEqual(self.render("no-such-panel").strip(), "")

    def test_the_language_toggle_is_absent_until_the_gujarati_exists(self):
        """
        ⚠ THE GUJARATI IS CHECKED BY THEIR OWN PEOPLE BEFORE IT SHIPS — the same
          rule as the compliance checklist. A toggle that reveals blank steps is
          worse than no toggle.
        """
        self.assertNotIn("ગુજરાતી", self.render("bom"))


class TheGujaratiIsWrittenByThem(AuthedTestCase):
    """
    >>> ANCHOR: INFO-PANELS <<<
    Saahil's idea, and better than the plan it replaced: "what if we allow the
    admin to add gujarati info on their own, so they can edit your text wherever
    necessary?" Their own people correct the translation on screen rather than
    checking a document somebody then has to paste back.

    ⚠⚠ AN OVERLAY, NOT A COPY. The English lives in code and ships with the app;
       a row exists only where somebody has written a translation. An untouched
       install behaves exactly as it did before the table existed.
    """

    def setUp(self):
        super().setUp()
        self.key = "bom"
        self.first = PANELS[self.key]["steps"][0]

    def save(self, **boxes):
        return self.client.post(reverse("panel_text_save", args=[self.key]), boxes, follow=True)

    def render_panel(self):
        return Template('{% load help %}{% infopanel "' + self.key + '" %}').render(
            Context({"user": self.user}))

    def test_nothing_is_stored_until_somebody_writes_something(self):
        from masters.models import PanelTranslation

        self.client.get(reverse("panel_text"))

        self.assertEqual(PanelTranslation.objects.count(), 0)

    def test_a_translation_reaches_the_panel(self):
        self.save(**{f"gu-{self.first['label']}": "ગુજરાતી લખાણ"})

        self.assertIn("ગુજરાતી લખાણ", self.render_panel())

    def test_it_records_the_english_it_was_written_from(self):
        """
        ⚠⚠ THE WHOLE STALENESS MECHANISM. Without this, an English instruction
           that changes later leaves the Gujarati describing something that no
           longer exists, and nobody reading only Gujarati could ever find out.
        """
        from masters.models import PanelTranslation

        self.save(**{f"gu-{self.first['label']}": "લખાણ"})

        row = PanelTranslation.objects.get(step_label=self.first["label"])
        self.assertEqual(row.source_english, self.first["text"])
        self.assertEqual(row.updated_by, self.user)

    def test_the_screen_flags_a_row_whose_english_has_moved_on(self):
        from masters.models import PanelTranslation

        PanelTranslation.objects.create(
            panel_key=self.key, step_label=self.first["label"], gujarati="લખાણ",
            source_english="something the panel used to say")

        page = self.client.get(reverse("panel_text") + f"?panel={self.key}").content.decode()

        self.assertIn("changed in English after being translated", page)

    def test_an_up_to_date_row_is_not_flagged(self):
        self.save(**{f"gu-{self.first['label']}": "લખાણ"})

        page = self.client.get(reverse("panel_text") + f"?panel={self.key}").content.decode()

        self.assertNotIn("changed in English after being translated", page)

    def test_clearing_the_box_removes_the_translation(self):
        from masters.models import PanelTranslation

        self.save(**{f"gu-{self.first['label']}": "લખાણ"})
        self.save(**{f"gu-{self.first['label']}": ""})

        self.assertFalse(PanelTranslation.objects.exists())

    def test_the_toggle_needs_every_visible_step_translated(self):
        """Partly done stays English — a toggle revealing blank steps is worse."""
        self.save(**{f"gu-{self.first['label']}": "લખાણ"})

        self.assertNotIn("ગુજરાતી</button>", self.render_panel())

    def test_and_appears_once_they_all_are(self):
        boxes = {f"gu-{s['label']}": "લખાણ" for s in PANELS[self.key]["steps"]}
        self.save(**boxes)

        self.assertIn("ગુજરાતી", self.render_panel())

    def test_the_structure_cannot_be_edited(self):
        """
        ⚠ HIS RULE, AND HE WAS RIGHT: "Structure should never be editable in
          reality, especially by a user." No field on the form can add, remove or
          reorder a step, and the English is printed rather than typed into.
        """
        page = self.client.get(reverse("panel_text") + f"?panel={self.key}").content.decode()

        self.assertNotIn('name="head-', page)
        self.assertNotIn('name="text-', page)
        self.assertNotIn('name="label-', page)

    def test_only_an_admin_may_write_one(self):
        """Narrower than masters.edit, which PM, Purchase and Accountant hold."""
        self.client.force_login(self.make_user("pm.gu", role=Role.PROJECT_MANAGER))

        self.assertEqual(self.client.get(reverse("panel_text")).status_code, 403)

    def test_the_lookup_is_one_query(self):
        """
        ⚠ MEASURED BEFORE IT WAS BUILT: the BOM already runs 30 queries and 1.2
          seconds, the launchpad 2 and 10ms. One indexed lookup of six rows is
          inside the noise — but it must stay ONE, on every screen in the app.
        """
        self.save(**{f"gu-{self.first['label']}": "લખાણ"})

        with self.assertNumQueries(1):
            self.render_panel()


class TheScreensThatHaveOneUseIt(AuthedTestCase):
    """
    ⚠ POINT 5 — the ⓘ was on 17 of 48 screens and Saahil was clicking in the half
      that had none. These are the ones converted so far; the list grows as the
      remaining screens are done, and a screen that loses its panel fails here.
    """

    def test_the_bom_offers_its_panel(self):
        """
        ⚠ THE PROJECT NEEDS A REAL BOM. Written first with a bare project, which
          redirects to the "no bill of materials yet" screen — a different
          template, correctly carrying no panel. The test was wrong, not the app.
        """
        from decimal import Decimal as D
        from masters.models import Activity, Material, MaterialGroup
        from projects.bom_models import Bom, BomLine
        from projects.models import Project

        activity = Activity.objects.create(abbreviation="ZQP", name="Panel test activity",
                                           rate=D("100"), sort_order=920)
        group = MaterialGroup.objects.create(code="ZQP", name="Panel test group")
        material = Material.objects.create(
            code="ZQP-ZQP-001", name="TEST MATERIAL", group=group, home_activity=activity,
            uom="Bag", estimation_rate=D("400"), gst_percent=D("18"))
        project = Project.objects.create(name="Panel site", bua_sqft=D("1000"),
                                         status=Project.Status.WON)
        bom = Bom.objects.create(project=project, generated_by=self.user)
        BomLine.objects.create(bom=bom, activity=activity, material=material,
                               planned_qty=D("10"), sort_order=1)

        page = self.client.get(reverse("bom_screen", args=[project.pk]),
                               follow=True).content.decode()

        self.assertIn("info-bom", page)

    def test_master_data_offers_its_panel(self):
        page = self.client.get(reverse("master_data")).content.decode()

        self.assertIn("info-master_data", page)
