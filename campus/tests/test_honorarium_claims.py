"""P2-T04 (M02-05) tests: an External Member's Honorarium Claim for a Body Meeting they attended is approved through
the approval engine (never by its own requester) and drafts a Purchase Invoice for the member's Supplier, with TDS
withheld by ERPNext / india_compliance per the Supplier's Tax Withholding Category threshold, on the honorarium, DA and
TA (TA is exempt only at actuals with a bill). One claim per member per meeting; the creator must be able to read the
meeting. The claim follows its invoice when Accounts submits or cancels it."""

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe.utils import add_days, today

from campus.academic_governance.doctype.external_member.external_member import new_supplier
from campus.campus_finance.fee_heads import ensure_sac_code
from campus.campus_platform.approvals import approve, request_approval
from campus.tests.factories import make_company, make_user
from campus.tests.finance_factories import ensure_fiscal_years, make_account, make_company_with_accounts
from campus.tests.utils import CampusTestCase

COLLEGE, ABBR = "Honorarium Test College", "HONC"
OTHER = "Honorarium Other College"
APPROVER, OTHER_APPROVER, CLERK = "hon-approver@example.com", "hon-other-approver@example.com", "hon-clerk@example.com"
CATEGORY = "HON Test Professional Fees"
THRESHOLD, RATE = 50000, 10


class TestHonorariumClaim(CampusTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_fiscal_years()
		make_company_with_accounts(COLLEGE, ABBR)
		make_company(OTHER, "HONO")
		if not frappe.db.exists("Gender", "Male"):
			frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert()
		make_user(APPROVER, [COLLEGE])
		make_user(OTHER_APPROVER, [OTHER])
		make_user(CLERK, [COLLEGE])  # Academics User, sits on no body
		for user in (APPROVER, OTHER_APPROVER):
			frappe.get_doc("User", user).add_roles("Accounts Manager", "Accounts User")

	def setUp(self):
		frappe.db.savepoint("honorarium_test")
		self.addCleanup(frappe.db.rollback, save_point="honorarium_test")
		self.addCleanup(frappe.set_user, "Administrator")
		from campus.academic_governance.honorarium import seed_honorarium_policy
		from campus.academic_governance.seed import seed_body_types

		seed_body_types()
		seed_honorarium_policy()
		self.set_up_items()
		self.set_up_tds_category()
		self.attendee = self.external_member("Dr. Attendee")
		self.absentee = self.external_member("Dr. Absentee")
		self.meeting = self.held_meeting()

	# fixtures
	def set_up_items(self):
		group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		for setting, code in (("honorarium_item", "HON-TEST-FEE"), ("travel_item", "HON-TEST-TA"), ("daily_allowance_item", "HON-TEST-DA")):
			if not frappe.db.exists("Item", code):
				frappe.get_doc(
					{"doctype": "Item", "item_code": code, "item_group": group, "stock_uom": "Nos", "is_stock_item": 0, "gst_hsn_code": ensure_sac_code()}
				).insert()
			frappe.db.set_single_value("Governance Settings", setting, code)

	def set_up_tds_category(self):
		account = make_account(COLLEGE, ABBR, "TDS Payable", "Duties and Taxes", account_type="Tax")
		year = get_fiscal_year(today(), company=COLLEGE, as_dict=True)
		frappe.get_doc(
			{
				"doctype": "Tax Withholding Category", "name": CATEGORY, "category_name": CATEGORY,
				"accounts": [{"company": COLLEGE, "account": account}],
				"rates": [{
					"from_date": year.year_start_date, "to_date": year.year_end_date, "tax_withholding_rate": RATE,
					"single_threshold": THRESHOLD, "cumulative_threshold": THRESHOLD,
				}],
			}
		).insert()  # fmt: skip

	def external_member(self, name, supplier=True):
		member = frappe.get_doc({"doctype": "External Member", "member_name": name, "email": f"{frappe.generate_hash(length=8)}@example.com"}).insert()
		if supplier:
			member.create_supplier()
			frappe.db.set_value("Supplier", member.supplier, "tax_withholding_category", CATEGORY)
		return member.name

	def held_meeting(self, body_type="Governing Body", category="University Nominee"):
		employee = frappe.get_doc(
			{
				"doctype": "Employee", "first_name": "Hon", "last_name": frappe.generate_hash(length=6), "gender": "Male",
				"date_of_birth": "1980-01-01", "date_of_joining": "2010-01-01", "company": COLLEGE,
			}
		).insert().name  # fmt: skip
		start = add_days(today(), -400)
		members = [{"category": "Internal", "employee": employee, "from_date": start}]
		members += [{"category": category, "external_member": m, "from_date": start} for m in (self.attendee, self.absentee)]
		body = frappe.get_doc(
			{"doctype": "Body", "body_name": f"Honorarium Test {body_type}", "company": COLLEGE, "body_type": body_type, "members": members}
		).insert()  # fmt: skip
		return self.meeting_of(body.name)

	def meeting_of(self, body, days_ago=1):
		meeting = frappe.get_doc({"doctype": "Body Meeting", "body": body, "meeting_date": add_days(today(), -days_ago), "venue": "Hall"}).insert()
		for row in meeting.attendance:
			row.present = int(row.external_member != self.absentee)
		meeting.save()
		return meeting.name

	def claim(self, member=None, honorarium=30000, travel_allowance=2000, daily_allowance=1000, meeting=None, **values):
		return frappe.get_doc(
			{
				"doctype": "Honorarium Claim", "external_member": member or self.attendee, "body_meeting": meeting or self.meeting,
				"honorarium": honorarium, "travel_allowance": travel_allowance, "daily_allowance": daily_allowance, **values,
			}
		).insert()  # fmt: skip

	def approved(self, claim, approver=APPROVER):
		request = request_approval("Honorarium Claim", claim.name)
		frappe.set_user(approver)
		approve(request, None)
		frappe.set_user("Administrator")
		return frappe.get_doc("Honorarium Claim", claim.name)

	def bill(self, claim=None, doctype="Honorarium Claim"):
		"""A bill file, attached to `claim` when given; owned by the session user."""
		return frappe.get_doc(
			{
				"doctype": "File", "file_name": f"ta-{frappe.generate_hash(length=6)}.txt", "content": "train fare",
				"attached_to_doctype": doctype if claim else None, "attached_to_name": claim,
			}
		).insert().file_url  # fmt: skip

	def at_actuals(self, claim, bill):
		claim = frappe.get_doc("Honorarium Claim", claim.name)
		claim.update({"ta_actuals": 1, "ta_bill": bill})
		return claim.save()

	@staticmethod
	def withheld(invoice):
		return sum(row.base_tax_amount for row in invoice.taxes if row.is_tax_withholding_account)

	# AC1: approval drafts the Purchase Invoice, TDS per the section threshold
	def test_a_claim_below_the_threshold_drafts_an_invoice_without_tds(self):
		claim = self.approved(self.claim(honorarium=30000, travel_allowance=2000, daily_allowance=1000))
		self.assertEqual(claim.docstatus, 1)
		invoice = frappe.get_doc("Purchase Invoice", claim.purchase_invoice)
		supplier = frappe.db.get_value("External Member", self.attendee, "supplier")
		self.assertEqual((invoice.docstatus, invoice.supplier, invoice.company), (0, supplier, COLLEGE))
		self.assertEqual(sorted(row.amount for row in invoice.items), [1000, 2000, 30000])
		self.assertEqual(self.withheld(invoice), 0)
		self.assertEqual((claim.tds_amount, claim.net_payable), (0, 33000))

	def test_above_the_threshold_tds_is_withheld_on_the_honorarium_ta_and_da(self):
		claim = self.approved(self.claim(honorarium=60000, travel_allowance=3000, daily_allowance=2000))
		invoice = frappe.get_doc("Purchase Invoice", claim.purchase_invoice)
		self.assertEqual(invoice.docstatus, 0)
		self.assertTrue(invoice.apply_tds)
		self.assertEqual(self.withheld(invoice), 6500)  # 10% of the gross (194J)
		self.assertEqual({row.tax_withholding_category for row in invoice.tax_withholding_entries}, {CATEGORY})
		self.assertEqual((claim.tds_amount, claim.net_payable), (6500, 58500))

	def test_ta_at_actuals_with_a_bill_is_left_out_of_tds_but_da_is_not(self):
		claim = self.claim(honorarium=60000, travel_allowance=3000, daily_allowance=2000)
		claim = self.approved(self.at_actuals(claim, self.bill(claim.name)))
		self.assertEqual(self.withheld(frappe.get_doc("Purchase Invoice", claim.purchase_invoice)), 6200)

	def test_ta_at_actuals_needs_the_bill(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.claim(ta_actuals=1)
		self.assertIn("bill", str(caught.exception))
		with self.assertRaises(frappe.ValidationError):
			self.claim(ta_actuals=1, ta_bill="/files/no-such-bill.pdf")
		with self.assertRaises(frappe.ValidationError):
			self.claim(ta_actuals=1, ta_bill=self.bill())  # a new claim has nothing attached yet

	def test_the_ta_bill_must_be_attached_to_this_claim(self):
		claim = self.claim()
		with self.assertRaises(frappe.ValidationError) as caught:
			self.at_actuals(claim, self.bill())  # unattached
		self.assertIn("attach", str(caught.exception).lower())
		with self.assertRaises(frappe.ValidationError):
			self.at_actuals(claim, self.bill(self.meeting, doctype="Body Meeting"))

	def test_the_ta_bill_must_be_uploaded_by_the_claimant_or_accounts(self):
		claim = self.claim()
		frappe.set_user(CLERK)  # neither the claim's owner nor Accounts
		bill = self.bill(claim.name)
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			self.at_actuals(claim, bill)
		frappe.set_user(APPROVER)  # Accounts
		bill = self.bill(claim.name)
		frappe.set_user("Administrator")
		self.assertEqual(self.at_actuals(claim, bill).ta_actuals, 1)

	def test_the_cumulative_threshold_counts_earlier_submitted_invoices(self):
		first = self.approved(self.claim(honorarium=30000, travel_allowance=0, daily_allowance=0))
		frappe.get_doc("Purchase Invoice", first.purchase_invoice).submit()
		second_meeting = self.meeting_of(frappe.db.get_value("Body Meeting", self.meeting, "body"), days_ago=2)
		second = self.approved(self.claim(honorarium=30000, travel_allowance=0, daily_allowance=0, meeting=second_meeting))
		self.assertGreater(second.tds_amount, 0)  # 60,000 in the year crosses the 50,000 cumulative threshold
		self.assertEqual(second.tds_amount, self.withheld(frappe.get_doc("Purchase Invoice", second.purchase_invoice)))

	# the claim follows its invoice
	def test_submitting_the_invoice_refreshes_the_claim_figures(self):
		claim = self.approved(self.claim(honorarium=30000, travel_allowance=0, daily_allowance=0))
		invoice = frappe.get_doc("Purchase Invoice", claim.purchase_invoice)
		invoice.items[0].rate = 60000  # Accounts corrects the draft
		invoice.save()
		invoice.submit()
		claim.reload()
		self.assertEqual((claim.tds_amount, claim.net_payable), (6000, 54000))
		invoice.cancel()
		claim.reload()
		self.assertEqual((claim.tds_amount, claim.net_payable), (0, 0))  # nothing is payable on a cancelled invoice

	def test_the_voucher_shows_the_live_invoice_figures(self):
		claim = self.approved(self.claim(honorarium=30000, travel_allowance=0, daily_allowance=0))
		invoice = frappe.get_doc("Purchase Invoice", claim.purchase_invoice)
		invoice.items[0].rate = 60000
		invoice.save()  # still draft: no doc event, the claim's stored figures are stale
		html = frappe.get_print("Honorarium Claim", claim.name, "Honorarium Voucher")
		self.assertIn("54,000", html)
		self.assertIn("6,000", html)

	# TDS section from the Supplier only
	def test_the_tds_section_comes_from_the_supplier_only(self):
		self.assertEqual(self.claim(tds_section="Professional Fees - Company").tds_section, CATEGORY)

	def test_a_supplier_without_a_tds_category_is_refused(self):
		frappe.db.set_value("Supplier", frappe.db.get_value("External Member", self.attendee, "supplier"), "tax_withholding_category", None)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.claim()
		self.assertIn("TDS category", str(caught.exception))

	# approval engine
	def test_the_requester_cannot_approve_their_own_claim(self):
		claim = self.claim()
		request = request_approval("Honorarium Claim", claim.name)  # Administrator owns and requests
		with self.assertRaises(frappe.PermissionError):
			approve(request, None)
		self.assertEqual(frappe.db.get_value("Honorarium Claim", claim.name, "docstatus"), 0)
		self.assertFalse(frappe.db.exists("Purchase Invoice", {"supplier": claim.supplier}))

	def test_a_claim_cannot_be_submitted_without_approval(self):
		with self.assertRaises(frappe.ValidationError):
			self.claim().submit()

	def test_the_seeded_policy_needs_an_accounts_manager_of_the_company(self):
		policy = frappe.get_doc("Approval Policy", frappe.db.get_value("Approval Policy", {"document_type": "Honorarium Claim"}))
		self.assertEqual([(l.approver_type, l.approver, l.limit_to_company) for l in policy.levels], [("Role", "Accounts Manager", 1)])
		request = request_approval("Honorarium Claim", self.claim().name)
		frappe.set_user(OTHER_APPROVER)
		with self.assertRaises(frappe.PermissionError):
			approve(request, None)

	# the creator must be able to read the meeting
	def test_a_non_member_cannot_claim_for_a_confidential_meeting(self):
		icc_meeting = self.held_meeting("Internal Complaints Committee", "External Expert")
		frappe.set_user(CLERK)
		self.assertTrue(self.claim().name)  # an open body's meeting is fine
		with self.assertRaises(frappe.PermissionError):
			self.claim(meeting=icc_meeting)

	# one claim per member per meeting, attendees only
	def test_a_second_claim_for_the_same_member_and_meeting_is_refused(self):
		self.claim()
		with self.assertRaises(frappe.ValidationError) as caught:
			self.claim(honorarium=1000)
		self.assertIn("already", str(caught.exception))

	def test_a_cancelled_claim_frees_the_meeting_and_drops_its_draft_invoice(self):
		claim = self.approved(self.claim())
		invoice = claim.purchase_invoice
		claim.cancel()
		self.assertFalse(frappe.db.exists("Purchase Invoice", invoice))
		self.assertTrue(self.claim(honorarium=25000).name)

	def test_a_claim_cannot_be_cancelled_once_its_invoice_is_submitted(self):
		claim = self.approved(self.claim())
		frappe.db.set_value("Purchase Invoice", claim.purchase_invoice, "docstatus", 1)
		with self.assertRaises(frappe.ValidationError):
			claim.cancel()

	def test_a_cancelled_invoice_is_kept_when_the_claim_is_cancelled(self):
		claim = self.approved(self.claim())
		frappe.db.set_value("Purchase Invoice", claim.purchase_invoice, "docstatus", 2)
		claim.cancel()
		self.assertTrue(frappe.db.exists("Purchase Invoice", claim.purchase_invoice))

	def test_a_member_who_did_not_attend_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.claim(member=self.absentee)
		self.assertIn("attend", str(caught.exception))

	def test_a_member_without_a_supplier_is_refused(self):
		member = self.external_member("Dr. No Supplier", supplier=False)
		with self.assertRaises(frappe.ValidationError) as caught:
			frappe.get_doc({"doctype": "Honorarium Claim", "external_member": member, "body_meeting": self.meeting, "honorarium": 100}).insert()
		self.assertIn("Supplier", str(caught.exception))

	def test_the_company_supplier_and_currency_come_from_the_masters(self):
		claim = self.claim(company=OTHER, supplier=frappe.db.get_value("External Member", self.absentee, "supplier"), currency="USD")
		self.assertEqual(claim.company, COLLEGE)
		self.assertEqual(claim.supplier, frappe.db.get_value("External Member", self.attendee, "supplier"))
		self.assertEqual(claim.currency, "INR")

	# settings
	def test_a_missing_item_or_sac_code_is_named(self):
		frappe.db.set_single_value("Governance Settings", "travel_item", None)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.claim()
		self.assertIn("Travel Allowance Item", str(caught.exception))
		frappe.db.set_single_value("Governance Settings", "travel_item", "HON-TEST-TA")
		frappe.db.set_value("Item", "HON-TEST-FEE", "gst_hsn_code", None)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.claim()
		self.assertIn("HON-TEST-FEE", str(caught.exception))

	def test_accounts_managers_can_set_the_items(self):
		self.assertTrue(frappe.has_permission("Governance Settings", "write", user=APPROVER))

	# print
	def test_the_voucher_escapes_the_member_name(self):
		member = self.external_member("<b>Dr. Bold</b>", supplier=False)
		supplier = new_supplier("HON Bold Supplier")
		frappe.db.set_value("Supplier", supplier, "tax_withholding_category", CATEGORY)
		frappe.db.set_value("External Member", member, "supplier", supplier)
		frappe.get_doc(
			{
				"doctype": "Meeting Attendance", "parent": self.meeting, "parenttype": "Body Meeting", "parentfield": "attendance",
				"idx": 99, "category": "University Nominee", "external_member": member, "present": 1,
			}
		).db_insert()  # fmt: skip
		claim = self.claim(member=member)
		html = frappe.get_print("Honorarium Claim", claim.name, "Honorarium Voucher")
		self.assertIn("&lt;b&gt;Dr. Bold&lt;/b&gt;", html)
		self.assertNotIn("<b>Dr. Bold</b>", html)
		self.assertIn("30,000", html)

	def test_the_voucher_of_a_cancelled_invoice_shows_no_payable_figures(self):
		claim = self.approved(self.claim(honorarium=60000, travel_allowance=0, daily_allowance=0))
		invoice = frappe.get_doc("Purchase Invoice", claim.purchase_invoice)
		invoice.submit()
		invoice.cancel()
		html = frappe.get_print("Honorarium Claim", claim.name, "Honorarium Voucher")
		self.assertIn("Invoice cancelled", html)
		self.assertNotIn("54,000", html)
		self.assertNotIn("6,000", html)

	def test_the_invoice_link_is_indexed(self):
		self.assertTrue(frappe.get_meta("Honorarium Claim").get_field("purchase_invoice").search_index)
