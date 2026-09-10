"""
What the compliance repository has to keep being true.

⚠ THE TWO THAT MATTER MOST, AND THEY ARE BOTH ABOUT EVIDENCE:
  nothing is ever overwritten, and no document can be reached without the
  permission check. Everything else on these screens is convenience.
"""
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal as D

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from accounts.testing import AuthedTestCase
from compliance import status
from compliance.models import (
    ComplianceDocument, ComplianceItem, ComplianceTitle, ComplianceType, Kind,
    ProjectCompliance, applies_to,
)
from projects.models import Project

MEDIA = tempfile.mkdtemp()


def a_pdf(name="approval.pdf"):
    return SimpleUploadedFile(name, b"%PDF-1.4 not really a pdf", content_type="application/pdf")


class TheStatusIsDerived(TestCase):
    """
    ⚠ NOBODY MAINTAINS A STATUS FIELD, so nothing can quietly disagree with
      reality. Every answer below is worked out from the documents held.
    """

    def setUp(self):
        self.today = date(2026, 8, 14)
        type = ComplianceType.objects.create(code="TST", name="Test regime")
        title = ComplianceTitle.objects.create(type=type, name="Title")
        self.one = ComplianceItem.objects.create(title=title, name="One time", kind=Kind.ONE)
        self.valid = ComplianceItem.objects.create(title=title, name="Has validity",
                                                   kind=Kind.VALID)
        self.repeat = ComplianceItem.objects.create(title=title, name="Quarterly",
                                                    kind=Kind.REPEAT)

    def document(self, expires=None, uploaded=None):
        document = ComplianceDocument(expires_on=expires)
        document.uploaded_at = timezone.make_aware(
            timezone.datetime.combine(uploaded or self.today, timezone.datetime.min.time()))
        return document

    def test_nothing_uploaded_is_missing(self):
        state, latest, _days = status.state_of(self.one, [], self.today)
        self.assertEqual((state, latest), (status.MISSING, None))

    def test_a_one_time_document_is_held_and_never_expires(self):
        """⚠ Giving it an expiry it does not have puts a permanent approval on a
           renewal list forever."""
        state, _latest, days = status.state_of(self.one, [self.document()], self.today)
        self.assertEqual((state, days), (status.HELD, None))

    def test_a_validity_comfortably_away_is_valid(self):
        state, _l, days = status.state_of(
            self.valid, [self.document(expires=date(2027, 8, 14))], self.today)
        self.assertEqual(state, status.VALID)
        self.assertEqual(days, 365)

    def test_inside_sixty_days_it_is_expiring(self):
        state, _l, days = status.state_of(
            self.valid, [self.document(expires=self.today + timedelta(days=30))], self.today)
        self.assertEqual((state, days), (status.EXPIRING, 30))

    def test_past_its_date_it_is_expired_and_the_number_goes_negative(self):
        # ⚠ THE REAL FAILURE IS NOT A MISSING DOCUMENT, IT IS ONE THAT LAPSED.
        state, _l, days = status.state_of(
            self.valid, [self.document(expires=self.today - timedelta(days=3))], self.today)
        self.assertEqual((state, days), (status.EXPIRED, -3))

    def test_a_validity_item_with_no_typed_expiry_is_not_judged(self):
        state, _l, _d = status.state_of(self.valid, [self.document()], self.today)
        self.assertEqual(state, status.HELD)

    def test_a_quarterly_filing_falls_due_again(self):
        fresh = self.document(uploaded=self.today - timedelta(days=40))
        stale = self.document(uploaded=self.today - timedelta(days=120))
        self.assertEqual(status.state_of(self.repeat, [fresh], self.today)[0], status.HELD)
        self.assertEqual(status.state_of(self.repeat, [stale], self.today)[0], status.DUE_AGAIN)

    def test_only_compulsory_items_count_towards_attention(self):
        """An optional document that is missing is not a problem, and counting it
        as one teaches people to ignore the number."""
        optional = ComplianceItem.objects.create(
            title=self.one.title, name="Nice to have", kind=Kind.ONE, is_compulsory=False)
        rows = status.rows_for(None, [self.one, optional], [], self.today)
        self.assertEqual(status.summarise(rows)["attention"], 1)


@override_settings(MEDIA_ROOT=MEDIA)
class ComplianceCase(AuthedTestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.project = Project.objects.create(
            name="Bhudarpura", bua_sqft=D("26545"), status=Project.Status.WON)
        self.amc = ComplianceType.objects.get(code="AMC")
        self.rera = ComplianceType.objects.get(code="RERA")
        self.item = ComplianceItem.objects.filter(title__type=self.amc, kind=Kind.ONE).first()
        self.expiring_item = ComplianceItem.objects.filter(
            title__type=self.amc, kind=Kind.VALID).first()

    def upload(self, item=None, **extra):
        item = item or self.item
        data = {"file": a_pdf()}
        data.update(extra)
        return self.client.post(
            reverse("compliance_upload", args=[self.project.pk, item.pk]), data)


class TheChecklistIsSeededAndFlaggedAsADraft(ComplianceCase):

    def test_both_regimes_arrive_with_content(self):
        self.assertTrue(ComplianceItem.objects.filter(title__type=self.amc).exists())
        self.assertTrue(ComplianceItem.objects.filter(title__type=self.rera).exists())

    def test_amc_applies_to_every_project_and_rera_is_ticked(self):
        # ⚠ A compulsory regime cannot be switched off by forgetting to create a
        #   row — it is answered from the type itself.
        self.assertTrue(applies_to(self.project, self.amc))
        self.assertFalse(applies_to(self.project, self.rera))

        ProjectCompliance.objects.create(project=self.project, type=self.rera, applicable=True)
        self.assertTrue(applies_to(self.project, self.rera))

    def test_the_screen_says_the_checklist_is_a_draft(self):
        body = self.client.get(
            reverse("compliance_project", args=[self.project.pk])).content.decode()
        self.assertIn("first draft", body)

    def test_rera_forms_are_the_repeating_kind(self):
        forms = ComplianceItem.objects.filter(title__type=self.rera, name__startswith="Form")
        self.assertTrue(forms.exists())
        for form in forms:
            self.assertEqual(form.kind, Kind.REPEAT, form.name)


class NothingIsOverwritten(ComplianceCase):
    """
    ⚠⚠ "THE SUPERSEDED ONE IS OFTEN THE ONE AN INSPECTOR ASKS ABOUT." This is an
      evidence trail somebody may be asked to produce years later.
    """

    def test_a_second_upload_is_a_new_version_and_keeps_the_first(self):
        self.upload()
        self.upload()
        held = ComplianceDocument.objects.filter(project=self.project, item=self.item)
        self.assertEqual(held.count(), 2)

    def test_the_newest_is_the_current_one_and_the_rest_are_history(self):
        first = self.upload() and ComplianceDocument.objects.latest("id")
        second = self.upload() and ComplianceDocument.objects.latest("id")
        rows = status.rows_for(self.project, [self.item],
                               list(ComplianceDocument.objects.filter(item=self.item)))
        self.assertEqual(rows[0]["latest"].pk, second.pk)
        self.assertEqual([old.pk for old in rows[0]["history"]], [first.pk])

    def test_every_earlier_version_is_still_downloadable(self):
        self.upload()
        first = ComplianceDocument.objects.latest("id")
        self.upload()
        self.assertEqual(self.client.get(
            reverse("compliance_download", args=[first.pk])).status_code, 200)


class WhatMayBeUploaded(ComplianceCase):

    def test_a_document_with_a_validity_is_refused_without_an_expiry(self):
        """
        ⚠ REFUSED RATHER THAN SAVED BLANK. An expiry nobody typed never reaches
          the timeline, and a document that quietly lapsed is the exact failure
          this module exists to prevent.
        """
        self.upload(self.expiring_item)
        self.assertFalse(ComplianceDocument.objects.filter(item=self.expiring_item).exists())

        self.upload(self.expiring_item, expires_on="2027-08-14")
        self.assertTrue(ComplianceDocument.objects.filter(item=self.expiring_item).exists())

    def test_an_executable_is_refused(self):
        self.client.post(
            reverse("compliance_upload", args=[self.project.pk, self.item.pk]),
            {"file": SimpleUploadedFile("nasty.exe", b"MZ", content_type="application/exe")})
        self.assertFalse(ComplianceDocument.objects.exists())

    def test_something_too_large_is_refused(self):
        big = SimpleUploadedFile("huge.pdf", b"x" * (11 * 1024 * 1024),
                                 content_type="application/pdf")
        self.client.post(
            reverse("compliance_upload", args=[self.project.pk, self.item.pk]), {"file": big})
        self.assertFalse(ComplianceDocument.objects.exists())

    def test_the_original_name_and_size_are_kept(self):
        self.upload()
        document = ComplianceDocument.objects.get()
        self.assertEqual(document.original_name, "approval.pdf")
        self.assertGreater(document.size_bytes, 0)
        self.assertEqual(document.uploaded_by, self.user)


class WhoMayDoWhat(ComplianceCase):
    """
    ⚠ THE PERMISSION AMENDMENT: "give compliance access to project manager and
      site manager as well as the workers or labours can ask for proof." A site
      engineer in front of an inspector needs the licence on their phone, and
      that is a READ.
    """

    def test_five_roles_may_read_and_purchase_may_not(self):
        for role in (Role.ADMIN, Role.PROJECT_MANAGER, Role.ACCOUNTANT,
                     Role.SITE, Role.COMPLIANCE):
            self.client.force_login(self.make_user(f"{role}.reader", role=role))
            self.assertEqual(self.client.get(reverse("compliance_home")).status_code, 200, role)

        self.client.force_login(self.make_user("pur.person", role=Role.PURCHASE))
        self.assertEqual(self.client.get(reverse("compliance_home")).status_code, 403)

    def test_a_site_engineer_may_download_and_may_not_upload(self):
        self.upload()
        document = ComplianceDocument.objects.get()
        engineer = self.make_user("mistry", role=Role.SITE, name="Ramesh Mistry")
        self.client.force_login(engineer)

        self.assertEqual(self.client.get(
            reverse("compliance_download", args=[document.pk])).status_code, 200)
        self.assertEqual(self.client.post(
            reverse("compliance_upload", args=[self.project.pk, self.item.pk]),
            {"file": a_pdf()}).status_code, 403)

    def test_only_admin_and_compliance_may_upload(self):
        for role, allowed in [(Role.ADMIN, True), (Role.COMPLIANCE, True),
                              (Role.PROJECT_MANAGER, False), (Role.ACCOUNTANT, False),
                              (Role.SITE, False), (Role.PURCHASE, False)]:
            self.client.force_login(self.make_user(f"{role}.up", role=role))
            response = self.client.post(
                reverse("compliance_upload", args=[self.project.pk, self.item.pk]),
                {"file": a_pdf()})
            self.assertEqual(response.status_code != 403, allowed, role)

    def test_the_upload_button_is_not_drawn_for_somebody_who_cannot_upload(self):
        self.client.force_login(self.make_user("site.person", role=Role.SITE))
        body = self.client.get(
            reverse("compliance_project", args=[self.project.pk])).content.decode()
        self.assertNotIn("askUpload", body)
        self.assertIn("Download", body) if ComplianceDocument.objects.exists() else None


class DocumentsAreNotOnAPublicAddress(ComplianceCase):
    """
    ⚠⚠ THE WORST MISTAKE THIS MODULE COULD MAKE would be a signed municipal
      approval readable by anybody holding a link.
    """

    def test_there_is_no_media_url_setting_serving_the_folder(self):
        from django.conf import settings
        self.assertFalse(getattr(settings, "MEDIA_URL", "") not in ("", "/"),
                         "MEDIA_URL is set — compliance documents may be publicly reachable")

    def test_a_signed_out_visitor_gets_the_login_page_and_not_the_file(self):
        self.upload()
        document = ComplianceDocument.objects.get()
        self.client.logout()
        response = self.client.get(reverse("compliance_download", args=[document.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_a_missing_file_is_a_404_and_not_a_crash(self):
        # ⚠ A restore that brought back the rows and not the media folder would
        #   otherwise take every screen down. See OPEN-BEFORE-GO-LIVE.md.
        self.upload()
        document = ComplianceDocument.objects.get()
        document.file.storage.delete(document.file.name)
        self.assertEqual(self.client.get(
            reverse("compliance_download", args=[document.pk])).status_code, 404)


class TheScreens(ComplianceCase):

    def test_the_overview_leads_with_what_needs_attention(self):
        response = self.client.get(reverse("compliance_home"))
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.context["attention"], 0,
                           "a fresh project should be missing its whole checklist")

    def test_uploading_reduces_what_needs_attention(self):
        before = self.client.get(reverse("compliance_home")).context["attention"]
        self.upload()
        after = self.client.get(reverse("compliance_home")).context["attention"]
        self.assertEqual(after, before - 1)

    def test_turning_rera_on_adds_its_checklist_to_the_project(self):
        self.client.post(reverse("compliance_applies", args=[self.project.pk]),
                         {"type": self.rera.pk, "applicable": "yes"})
        regimes = self.client.get(
            reverse("compliance_project", args=[self.project.pk])).context["regimes"]
        self.assertIn("RERA", [regime["type"].code for regime in regimes])

    def test_no_screen_leaks_template_syntax(self):
        self.upload()
        for url in (reverse("compliance_home"),
                    reverse("compliance_project", args=[self.project.pk])):
            body = self.client.get(url).content.decode()
            for leak in ("{#", "#}", "{%", "%}"):
                self.assertNotIn(leak, body, f"{url} printed raw template syntax")


class TheSuggestionIsVisiblyAGuess(ComplianceCase):
    """
    ⚠ NOTHING ON THEIR SERVER CAN READ A PDF — no model on that machine and, by
      their own choice, no internet. So the expiry is typed. What the system can
      do is arithmetic: issue date plus the master's typical validity, shown as a
      suggestion and overwritable. A guess that looks like a fact is the failure
      to avoid.
    """

    def test_the_master_carries_the_typical_validity_to_the_screen(self):
        self.expiring_item.validity_days = 365
        self.expiring_item.save()
        body = self.client.get(
            reverse("compliance_project", args=[self.project.pk])).content.decode()
        self.assertIn('data-validity="365"', body)

    def test_an_item_with_no_typical_validity_offers_nothing(self):
        self.expiring_item.validity_days = None
        self.expiring_item.save()
        body = self.client.get(
            reverse("compliance_project", args=[self.project.pk])).content.decode()
        self.assertIn('data-validity=""', body)

    def test_the_typed_date_is_what_is_stored(self):
        # ⚠ The suggestion never reaches the database — only what was in the box
        #   when Save was pressed.
        self.expiring_item.validity_days = 365
        self.expiring_item.save()
        self.upload(self.expiring_item, expires_on="2028-01-31")
        self.assertEqual(ComplianceDocument.objects.get(item=self.expiring_item).expires_on,
                         date(2028, 1, 31))


class CorrectingTheTyping(ComplianceCase):
    """
    ⚠ TWO DIFFERENT THINGS HIDE UNDER "CHANGE AN APPROVAL", and they have
      different answers. The PAPER is superseded → Replace, a new version. The
      TYPING beside it is wrong → this, and the file is untouched.
    """

    def setUp(self):
        super().setUp()
        self.upload(self.expiring_item, expires_on="2027-01-01", reference="WRONG/1")
        self.document = ComplianceDocument.objects.get(item=self.expiring_item)

    def correct(self, **data):
        payload = {"reference": "AMC/2026/1", "expires_on": "2027-06-30"}
        payload.update(data)
        return self.client.post(reverse("compliance_correct", args=[self.document.pk]), payload)

    def test_a_correction_changes_the_details_and_not_the_file(self):
        was = self.document.file.name
        self.correct()
        self.document.refresh_from_db()
        self.assertEqual(self.document.reference, "AMC/2026/1")
        self.assertEqual(self.document.expires_on, date(2027, 6, 30))
        self.assertEqual(self.document.file.name, was)

    def test_a_correction_does_not_create_a_version(self):
        self.correct()
        self.assertEqual(ComplianceDocument.objects.filter(item=self.expiring_item).count(), 1)

    def test_who_corrected_it_is_recorded(self):
        self.correct()
        self.document.refresh_from_db()
        self.assertEqual(self.document.corrected_by, self.user)
        self.assertIsNotNone(self.document.corrected_at)

    def test_a_validity_item_cannot_be_corrected_to_a_blank_expiry(self):
        self.correct(expires_on="")
        self.document.refresh_from_db()
        self.assertEqual(self.document.expires_on, date(2027, 1, 1))

    def test_only_somebody_who_may_upload_may_correct(self):
        self.client.force_login(self.make_user("site.fix", role=Role.SITE))
        self.assertEqual(self.correct().status_code, 403)


class TheChecklistMasterIsAScreen(ComplianceCase):
    """
    ⚠ SAAHIL'S QUESTION, ANSWERED: *"what is this meant for, because in the same
      one project I can review everything based on project"*. A line typed here
      appears on every project of that type — ten sites, one typing.
    """

    def test_a_title_and_an_item_can_be_added_on_screen(self):
        # ⚠ NAMES THE SEEDED CHECKLIST DOES NOT ALREADY USE. Picking "Environment
        #   and safety" here failed the first time this was written — the seed
        #   already has it, the duplicate title was correctly refused, and the
        #   item then collided under the EXISTING title. The app was right and
        #   the test was wrong, which is the good way round.
        self.client.post(reverse("compliance_master_title"),
                         {"type": self.amc.pk, "name": "Lender conditions"})
        title = ComplianceTitle.objects.get(type=self.amc, name="Lender conditions")

        self.client.post(reverse("compliance_master_item"), {
            "title": title.pk, "name": "Quarterly drawdown certificate",
            "kind": Kind.VALID, "validity_days": "1825"})
        item = ComplianceItem.objects.get(name="Quarterly drawdown certificate")
        self.assertEqual((item.kind, item.validity_days), (Kind.VALID, 1825))
        self.assertIsNone(item.project, "a new item should apply to every project by default")

    def test_a_new_item_lands_on_every_project_as_missing(self):
        # ⚠ Which is exactly why the dialog states the blast radius before saving.
        title = ComplianceTitle.objects.filter(type=self.amc).first()
        before = self.client.get(reverse("compliance_home")).context["attention"]
        self.client.post(reverse("compliance_master_item"),
                         {"title": title.pk, "name": "Brand new rule", "kind": Kind.ONE})
        after = self.client.get(reverse("compliance_home")).context["attention"]
        self.assertEqual(after, before + 1)

    def test_an_item_can_belong_to_one_project_only(self):
        other = Project.objects.create(name="Shilaj Villas", bua_sqft=D("18400"),
                                       status=Project.Status.WON)
        title = ComplianceTitle.objects.filter(type=self.amc).first()
        self.client.post(reverse("compliance_master_item"), {
            "title": title.pk, "name": "Lake-margin NOC", "kind": Kind.ONE,
            "project": self.project.pk})

        mine = self.client.get(reverse("compliance_project", args=[self.project.pk]))
        theirs = self.client.get(reverse("compliance_project", args=[other.pk]))
        names = lambda response: [row["item"].name
                                  for regime in response.context["regimes"] for row in regime["rows"]]
        self.assertIn("Lake-margin NOC", names(mine))
        self.assertNotIn("Lake-margin NOC", names(theirs))

    def test_a_duplicate_title_is_refused(self):
        existing = ComplianceTitle.objects.filter(type=self.amc).first()
        before = ComplianceTitle.objects.filter(type=self.amc).count()
        self.client.post(reverse("compliance_master_title"),
                         {"type": self.amc.pk, "name": existing.name.upper()})
        self.assertEqual(ComplianceTitle.objects.filter(type=self.amc).count(), before)

    def test_deactivating_keeps_every_document(self):
        """⚠ There is no delete, here or anywhere in this system."""
        self.upload()
        self.client.post(reverse("compliance_master_off", args=[self.item.pk]))
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_active)
        self.assertEqual(ComplianceDocument.objects.filter(item=self.item).count(), 1)

    def test_a_new_regime_needs_one_decision(self):
        self.client.post(reverse("compliance_master_type"),
                         {"code": "fire", "name": "Fire department", "every": "no"})
        type = ComplianceType.objects.get(code="FIRE")
        self.assertFalse(type.applies_to_every_project)
        # Optional, so it applies to nobody until it is ticked.
        self.assertFalse(applies_to(self.project, type))

    def test_only_admin_and_compliance_may_edit_the_master(self):
        for role, allowed in [(Role.ADMIN, True), (Role.COMPLIANCE, True),
                              (Role.PROJECT_MANAGER, False), (Role.SITE, False)]:
            self.client.force_login(self.make_user(f"{role}.master", role=role))
            self.assertEqual(self.client.get(reverse("compliance_master")).status_code != 403,
                             allowed, role)


class TheExpiryTimeline(ComplianceCase):

    def test_it_lists_only_things_with_a_validity(self):
        self.upload()                                    # a one-time document
        self.upload(self.expiring_item, expires_on="2027-01-01")
        rows = self.client.get(reverse("compliance_timeline")).context["rows"]
        self.assertEqual([row["item"].pk for row in rows], [self.expiring_item.pk])

    def test_expired_first_and_never_dropped(self):
        # ⚠ A list that only looked forward would hide the exact failure this
        #   module exists to prevent.
        past = (timezone.localdate() - timedelta(days=30)).isoformat()
        self.upload(self.expiring_item, expires_on=past)
        response = self.client.get(reverse("compliance_timeline"))
        self.assertEqual(len(response.context["expired"]), 1)
        self.assertEqual(response.context["rows"][0]["state"], status.EXPIRED)

    def test_a_replaced_certificate_shows_only_its_current_version(self):
        old = (timezone.localdate() - timedelta(days=10)).isoformat()
        new = (timezone.localdate() + timedelta(days=300)).isoformat()
        self.upload(self.expiring_item, expires_on=old)
        self.upload(self.expiring_item, expires_on=new)
        rows = self.client.get(reverse("compliance_timeline")).context["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], status.VALID)

    def test_a_site_engineer_can_open_it(self):
        self.client.force_login(self.make_user("site.tl", role=Role.SITE))
        self.assertEqual(self.client.get(reverse("compliance_timeline")).status_code, 200)
