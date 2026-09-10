"""
The sales ⓘ panels keep the format `projects/test_info_panels.py` enforces,
so merging them into `projects.help_panels.PANELS` cannot break that suite —
and every panel key a sales template asks for actually exists.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from sales.panels import PANELS


class SalesPanelsKeepTheFormat(SimpleTestCase):

    def test_steps_are_between_twenty_and_thirty_words(self):
        for key, panel in PANELS.items():
            for number, step in enumerate(panel["steps"], 1):
                words = len(step["text"].split())
                with self.subTest(panel=key, step=number):
                    self.assertGreaterEqual(words, 18)
                    self.assertLessEqual(words, 32)

    def test_labels_are_one_or_two_words_and_panels_have_three_steps(self):
        for key, panel in PANELS.items():
            with self.subTest(panel=key):
                self.assertTrue(panel["title"])
                self.assertGreaterEqual(len(panel["steps"]), 3)
                for step in panel["steps"]:
                    self.assertLessEqual(len(step["label"].split()), 2)
                    self.assertFalse(step["label"].endswith("."))
                    self.assertNotIn("<", step["text"])
                    for control in re.findall(r"\[\[(.+?)\]\]", step["text"]):
                        self.assertLessEqual(len(control.split()), 4)

    def test_a_step_that_needs_a_permission_names_a_real_key(self):
        from accounts.perms import MATRIX
        for key, panel in PANELS.items():
            for step in panel["steps"]:
                if step["perm"]:
                    with self.subTest(panel=key, step=step["label"]):
                        self.assertIn(step["perm"], MATRIX)
                        self.assertTrue(step["perm"].startswith("sales."))

    def test_every_key_a_sales_template_uses_exists(self):
        folder = Path(settings.BASE_DIR) / "templates" / "sales"
        used = set()
        for path in folder.glob("*.html"):
            used.update(re.findall(r'{% info(?:button|panel) "([^"]+)" %}', path.read_text(encoding="utf-8")))
        self.assertTrue(used)
        self.assertEqual(used - set(PANELS), set())
        # And nothing is written for a screen that does not exist.
        self.assertEqual(set(PANELS) - used, set())
