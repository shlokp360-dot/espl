"""
The estimate as a PDF.

>>> ANCHOR: BOQ-PDF <<<
Saahil's requirement, in his words: "once they quote it, they download it, and
then they upload it onto a portal."

⚠⚠ WEASYPRINT IS NOT INSTALLED IN CI — only Django, python-dotenv and openpyxl
   are. So these tests exercise everything up to and including the template
   render and the Draft refusal, and skip only the byte-generation itself. That
   is the same reason po_pdf imports WeasyPrint inside the function, and the
   same line the purchase-order tests draw.
"""
import sys
import types
from contextlib import contextmanager
from decimal import Decimal as D
from unittest.mock import MagicMock

from django.template.loader import render_to_string
from django.urls import reverse

from accounts.models import Role
from accounts.testing import AuthedTestCase
from masters.models import Activity, CompanyProfile
from projects import bom_calc
from projects.models import Estimate, EstimateLine, Project


@contextmanager
def stubbed_weasyprint():
    """
    ⚠⚠ WEASYPRINT IS NOT INSTALLED IN CI, so it cannot even be imported to be
       patched — `patch("weasyprint.HTML")` fails at the import, not at the
       assertion. A whole fake module goes into `sys.modules` instead, which is
       also what makes this test meaningful: it proves the view reaches the PDF
       step and builds the response around it, without needing native libraries
       that take minutes to build and that CI deliberately does not have.
    """
    fake = types.ModuleType("weasyprint")
    fake.HTML = MagicMock()
    fake.HTML.return_value.write_pdf.return_value = b"%PDF-1.7 fake"
    had = sys.modules.get("weasyprint")
    sys.modules["weasyprint"] = fake
    try:
        yield fake
    finally:
        if had is None:
            sys.modules.pop("weasyprint", None)
        else:
            sys.modules["weasyprint"] = had


class Fixture(AuthedTestCase):

    def setUp(self):
        super().setUp()
        self.rcc = Activity.objects.get(abbreviation="RCC")
        self.project = Project.objects.create(
            code="PRJ-ZQP", name="ZQ PDF Site", bua_sqft=D("10000"),
            status=Project.Status.DRAFT)
        self.estimate = Estimate.objects.create(
            project=self.project, contingency_percent=D("7.35"),
            design_fee_percent=D("4.65"), gst_percent=D("18"))
        EstimateLine.objects.create(estimate=self.estimate, name=self.rcc.name,
                                    rate=D("600"), gst_percent=D("18"))

    def url(self):
        return reverse("boq_pdf", args=[self.project.id])

    def quote_it(self):
        self.project.status = Project.Status.QUOTED
        self.project.save(update_fields=["status"])


class ADraftIsRefused(Fixture):
    """
    ⚠⚠ THE RULE, AND IT IS THE SAME ONE AS THE PURCHASE ORDER'S. A draft
       estimate is a number still being argued about. On paper, in somebody
       else's inbox, it is indistinguishable from an offer — and nothing in the
       document itself would tell them otherwise.
    """

    def test_a_draft_project_cannot_be_downloaded(self):
        response = self.client.get(self.url(), follow=True)
        self.assertContains(response, "still a Draft")

    def test_a_draft_is_redirected_rather_than_500(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("boq", response["Location"])

    def test_the_button_is_not_offered_on_a_draft(self):
        page = self.client.get(reverse("boq_screen", args=[self.project.id]))
        self.assertNotContains(page, reverse("boq_pdf", args=[self.project.id]))

    def test_the_button_appears_once_quoted(self):
        self.quote_it()
        page = self.client.get(reverse("boq_screen", args=[self.project.id]))
        self.assertContains(page, reverse("boq_pdf", args=[self.project.id]))


class TheDocumentSaysWhatTheScreenSays(Fixture):
    """
    ⚠⚠ THE POINT OF THE WHOLE FEATURE: the paper and the screen read the same
       figures, because both ask `Estimate` for them and neither works anything
       out on its own. If this ever fails, somebody has added a second
       implementation of the arithmetic.
    """

    def setUp(self):
        super().setUp()
        self.quote_it()

    def render(self):
        lines = bom_calc.boq_rows(self.estimate)
        return render_to_string("projects/boq_pdf.html", {
            "project": self.project,
            "estimate": self.estimate,
            "lines": lines,
            "company": CompanyProfile.get_solo(),
            "bill_to": self.project.billing_address,
        })

    def test_every_rung_of_the_ladder_is_on_the_page(self):
        html = self.render()
        # 600 x 10,000 = 60,00,000 base; 7.35% and 4.65% on top; 18% on the lot.
        self.assertIn("60,00,000", html)          # base cost
        self.assertIn("4,41,000", html)           # contingency @ 7.35%
        self.assertIn("2,79,000", html)           # design fee @ 4.65%
        self.assertIn("67,20,000", html)          # cost before GST
        self.assertIn("12,09,600", html)          # GST @ 18%
        self.assertIn("79,29,600", html)          # grand total

    def test_the_figures_match_the_model_exactly(self):
        """Belt and braces — the numbers above, asserted against the source."""
        self.assertEqual(self.estimate.base_cost, D("6000000"))
        self.assertEqual(self.estimate.contingency_amount, D("441000.00"))
        self.assertEqual(self.estimate.design_fee_amount, D("279000.00"))
        self.assertEqual(self.estimate.grand_total, D("7929600.0000"))

    def test_it_carries_the_project_and_the_area(self):
        html = self.render()
        self.assertIn("PRJ-ZQP", html)
        self.assertIn("ZQ PDF Site", html)
        self.assertIn("10,000", html)

    def test_no_rupee_glyph_reaches_the_pdf(self):
        """
        ⚠ THE GLYPH IS MISSING FROM MANY SERVER FONTS and prints as a hollow box
          on a document sent to a client. Same rule as the purchase order.
        """
        self.assertNotIn("₹", self.render())

    def test_the_activity_and_its_rate_are_listed(self):
        html = self.render()
        self.assertIn(self.rcc.name, html)
        self.assertIn("600.00", html)


class OnlyTheRolesThatSeeTheEstimate(Fixture):
    """
    ⚠ IT READS THE ESTIMATE, so it reads like `boq.view` — Admin and Project
      manager. Added to `test_matrix` in the same commit, because that table is
      hand-written and a new key is not caught automatically.
    """

    def test_a_site_engineer_is_refused(self):
        self.quote_it()
        self.client.force_login(self.make_user("zqsitepdf", role=Role.SITE))
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_a_project_manager_may_download(self):
        self.quote_it()
        self.client.force_login(self.make_user("zqpmpdf", role=Role.PROJECT_MANAGER))
        with stubbed_weasyprint():
            response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)


class TheDownloadItself(Fixture):
    """The response, with WeasyPrint stubbed out — CI has no native libraries."""

    def test_it_comes_back_as_a_pdf_named_after_the_project(self):
        self.quote_it()
        with stubbed_weasyprint():
            response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("PRJ-ZQP", response["Content-Disposition"])
        self.assertIn("estimate.pdf", response["Content-Disposition"])
