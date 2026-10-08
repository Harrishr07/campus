"""P2-T04 (M02-05) tests: an External Member's Honorarium Claim for a Body Meeting they attended is approved through
the approval engine (never by its own requester) and drafts a Purchase Invoice for the member's Supplier, with TDS
withheld by ERPNext / india_compliance per the Tax Withholding Category threshold. One claim per member per meeting."""

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
APPROVER, OTHER_APPROVER = "hon-approver@example.com", "hon-other-approver@example.com"
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
		for setting, code in (("honorarium_item", "HON-TEST-FEE"), ("travel_item", "HON-TEST-TADA")):
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

	def held_meeting(self):
		employee = frappe.get_doc(
			{
				"doctype": "Employee", "first_name": "Hon", "last_name": frappe.generate_hash(length=6), "gender": "Male",
				"date_of_birth": "1980-01-01", "date_of_joining": "2010-01-01", "company": COLLEGE,
			}
		).insert().name  # fmt: skip
		start = add_days(today(), -400)
		members = [{"category": "Internal", "employee": employee, "from_date": start}]
		members += [{"category": "University Nominee", "external_member": m, "from_date": start} for m in (self.attendee, self.absentee)]
		body = frappe.get_doc(
			{"doctype": "Body", "body_name": "Honorarium Test GB", "company": COLLEGE, "body_type": "Governing Body", "members": members}
		).insert()  # fmt: skip
		meeting = frappe.get_doc({"doctype": "Body Meeting", "body": body.name, "meeting_date": add_days(today(), -1), "venue": "Hall"}).insert()
		for row in meeting.attendance:
			row.present = int(row.external_member != self.absentee)
		meeting.save()
		return meeting.name

	def claim(self, member=None, honorarium=30000, ta_da=2000, **values):
		return frappe.get_doc(
			{
				"doctype": "Honorarium Claim", "external_member": member or self.attendee, "body_meeting": self.meeting,
				"honorarium": honorarium, "ta_da": ta_da, **values,
			}
		).insert()  # fmt: skip

	def approved(self, claim, approver=APPROVER):
		request = request_approval("Honorarium Claim", claim.name)
		frappe.set_user(approver)
		approve(request, None)
		frappe.set_user("Administrator")
		return frappe.get_doc("Honorarium Claim", claim.name)

	@staticmethod
	def withheld(invoice):
		return sum(row.base_tax_amount for row in invoice.taxes if row.is_tax_withholding_account)

	# AC1: approval drafts the Purchase Invoice, TDS per the section threshold
	def test_a_claim_below_the_threshold_drafts_an_invoice_without_tds(self):
		claim = self.approved(self.claim(honorarium=30000, ta_da=2000))
		self.assertEqual(claim.docstatus, 1)
		invoice = frappe.get_doc("Purchase Invoice", claim.purchase_invoice)
		supplier = frappe.db.get_value("External Member", self.attendee, "supplier")
		self.assertEqual((invoice.docstatus, invoice.supplier, invoice.company), (0, supplier, COLLEGE))
		self.assertEqual(sorted((row.item_code, row.amount) for row in invoice.items), [("HON-TEST-FEE", 30000), ("HON-TEST-TADA", 2000)])
		self.assertEqual(self.withheld(invoice), 0)
		self.assertEqual((claim.tds_amount, claim.net_payable), (0, 32000))

	def test_a_claim_above_the_threshold_withholds_tds_on_the_honorarium(self):
		claim = self.approved(self.claim(honorarium=60000, ta_da=3000))
		invoice = frappe.get_doc("Purchase Invoice", claim.purchase_invoice)
		self.assertEqual(invoice.docstatus, 0)
		self.assertTrue(invoice.apply_tds)
		self.assertEqual(self.withheld(invoice), 6000)  # 10% of the honorarium; TA/DA is a reimbursement
		self.assertEqual({row.tax_withholding_category for row in invoice.tax_withholding_entries}, {CATEGORY})
		self.assertEqual((claim.tds_amount, claim.net_payable), (6000, 57000))

	def test_the_tds_section_defaults_from_the_supplier(self):
		self.assertEqual(self.claim().tds_section, CATEGORY)

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

	def test_a_member_who_did_not_attend_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self.claim(member=self.absentee)
		self.assertIn("attend", str(caught.exception))

	def test_a_member_without_a_supplier_is_refused(self):
		member = self.external_member("Dr. No Supplier", supplier=False)
		with self.assertRaises(frappe.ValidationError) as caught:
			frappe.get_doc({"doctype": "Honorarium Claim", "external_member": member, "body_meeting": self.meeting, "honorarium": 100}).insert()
		self.assertIn("Supplier", str(caught.exception))

	def test_the_company_and_supplier_come_from_the_meeting_and_member(self):
		claim = self.claim(company=OTHER, supplier=frappe.db.get_value("External Member", self.absentee, "supplier"))
		self.assertEqual(claim.company, COLLEGE)
		self.assertEqual(claim.supplier, frappe.db.get_value("External Member", self.attendee, "supplier"))

	# print
	def test_the_voucher_escapes_the_member_name(self):
		member = self.external_member("<b>Dr. Bold</b>", supplier=False)
		frappe.db.set_value("External Member", member, "supplier", new_supplier("HON Bold Supplier"))
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
